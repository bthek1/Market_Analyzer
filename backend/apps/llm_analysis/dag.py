"""Multi-Agent (Parallel / DAG) agent.

A lead orchestrator LLM dynamically decomposes the user's question into a dependency graph (DAG)
of subtasks. Each node carries an optional read-only tool and a ``depends_on`` list of upstream
node ids. The executor layers the graph into topological waves (Kahn) and runs each wave's nodes
CONCURRENTLY via ``services.chat_many`` - waves run in order, and each downstream node receives its
upstream nodes' outputs as context. A final synthesis call folds the terminal (sink) node outputs
into the answer.

What makes this distinct from its cousins:
  * vs ``orchestrator`` (Orchestrator-Workers): there every subtask is INDEPENDENT (a single
    parallel fan-out). Here nodes carry explicit ``depends_on`` edges, so the graph runs in waves
    and a downstream node sees its upstreams' outputs. Orchestrator-Workers is the single-wave case.
  * vs ``plan_execute``: that is a strictly sequential ordered plan. Here the dependency structure
    is a partial order (a DAG), so independent branches run in parallel; only true deps serialise.
  * vs ``multiagent`` (Sequential/Hierarchical): that is a fixed, role-specialised, width-1
    pipeline. This is a dynamic, arbitrary-width graph invented per query.

Tools are the same read-only DB lookups ReAct / plan-execute / orchestrator use (see ``tools.py``).
The only new primitive is ``topological_waves`` (pure code, no LLM).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC
from datetime import datetime as dt
from typing import TYPE_CHECKING

from . import tools
from ._events import event
from ._json import parse_json_object
from ._runtime import AbortedError, BaseStrategy, Outcome, Wave, drive_waves

if TYPE_CHECKING:
    from collections.abc import Generator

    from .models import AgentRun, AgentStep


# --- Node model (in-memory, parsed from the orchestrator) ----------------------------------


@dataclass
class Node:
    id: str
    task: str
    focus: str
    tool: str | None = None
    args: dict | None = None
    depends_on: list[str] = field(default_factory=list)


# --- Prompts -------------------------------------------------------------------------------


def _decompose_system(max_nodes: int) -> str:
    return (
        "You are a research orchestrator. Break the user's question into a DEPENDENCY GRAPH of at "
        f"most {max_nodes} subtasks. Give each node a short stable id (n1, n2, ...). For each node "
        "optionally pick ONE tool that fetches the data it needs (or use null for a pure-reasoning "
        "node). List in 'depends_on' ONLY the ids of nodes whose OUTPUT this node genuinely needs; "
        "leave it empty for independent nodes so they can run in parallel. Respond with ONLY a "
        "single JSON object, nothing else:\n"
        '  {"nodes": [{"id": "n1", "task": "<what this node should produce>", '
        '"focus": "<short label>", "tool": "<tool name or null>", "args": {<arguments>}, '
        '"depends_on": ["<id>", ...]}]}\n\n'
        "Available tools:\n" + tools.tool_catalogue() + "\n\n"
        "Rules: keep independent work in SEPARATE nodes (they parallelise). Only add a dependency "
        "when a node truly needs another's result. Do not create cycles. Tickers are uppercase."
    )


NODE_SYSTEM = (
    "You are a focused financial-analysis worker handling ONE node of a larger graph. Use the tool "
    "observation and any upstream results you are given to produce a concise, factual result for "
    "your node only. Do not answer the whole question; do not invent data."
)

SYNTH_SYSTEM = (
    "Several workers each handled one node of a dependency graph. Synthesise their outputs into "
    "one coherent, structured analysis; resolve overlaps and highlight the key takeaways. Write "
    "clean markdown."
)


# --- Parsing + graph hygiene ---------------------------------------------------------------


def parse_nodes(raw: str, max_nodes: int) -> list[Node]:
    """Parse an orchestrator response into a normalised, capped, acyclic list of ``Node``.

    Assigns missing ids, derives a missing focus, normalises tool/args, caps at ``max_nodes``, then
    prunes ``depends_on`` edges to unknown ids / self-loops and BREAKS cycles (drops the back-edge
    that closes each cycle) so the result is a valid DAG. Raises ``ValueError`` when no usable node
    remains.
    """
    items = None
    try:
        data = parse_json_object(raw)
        if isinstance(data.get("nodes"), list):
            items = data["nodes"]
    except ValueError:
        pass

    if items is None:
        # Tolerate a bare JSON list of nodes (no wrapping {"nodes": ...} object).
        text = raw.strip()
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end > start:
            try:
                items = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                items = None

    if not isinstance(items, list) or not items:
        raise ValueError("decomposition was empty")

    # First pass: normalise each entry and assign a unique id (cap to max_nodes).
    nodes: list[Node] = []
    raw_deps: list[list[str]] = []
    seen_ids: set[str] = set()
    for i, entry in enumerate(items[:max_nodes]):
        if not isinstance(entry, dict):
            continue
        task = str(entry.get("task", "")).strip()
        if not task:
            continue
        node_id = str(entry.get("id", "")).strip()
        if not node_id or node_id in seen_ids:
            node_id = f"n{i + 1}"
        while node_id in seen_ids:  # still colliding (e.g. a literal "n2") -> bump
            node_id = f"{node_id}_{len(seen_ids)}"
        seen_ids.add(node_id)

        tool = entry.get("tool")
        if tool in ("", "null", "none", "None"):
            tool = None
        args = entry.get("args")
        focus = str(entry.get("focus", "")).strip() or task[:40]
        deps = entry.get("depends_on")
        raw_deps.append([str(d).strip() for d in deps] if isinstance(deps, list) else [])
        nodes.append(
            Node(
                id=node_id,
                task=task,
                focus=focus,
                tool=tool,
                args=args if isinstance(args, dict) else None,
            )
        )

    if not nodes:
        raise ValueError("decomposition had no usable nodes")

    # Second pass: prune edges to unknown ids / self-loops.
    valid_ids = {n.id for n in nodes}
    for node, deps in zip(nodes, raw_deps, strict=True):
        node.depends_on = [d for d in deps if d in valid_ids and d != node.id]

    _break_cycles(nodes)
    return nodes


_WHITE, _GREY, _BLACK = 0, 1, 2  # DFS colours for cycle detection


def _break_cycles(nodes: list[Node]) -> None:
    """Remove back-edges so the dependency graph is acyclic. Mutates each node's ``depends_on``.

    Edge ``u -> v`` means *u depends on v* (v runs before u). A DFS over these edges: when a node's
    dependency points at a node currently on the recursion stack, that edge closes a cycle and is
    dropped. With <= max_nodes nodes the recursion depth is tiny.
    """
    deps = {n.id: n for n in nodes}
    color = {n.id: _WHITE for n in nodes}

    def visit(uid: str) -> None:
        color[uid] = _GREY
        for vid in list(deps[uid].depends_on):
            if color[vid] == _GREY:
                deps[uid].depends_on.remove(vid)  # back-edge closes a cycle -> drop it
            elif color[vid] == _WHITE:
                visit(vid)
        color[uid] = _BLACK

    for node in nodes:
        if color[node.id] == _WHITE:
            visit(node.id)


def topological_waves(nodes: list[Node]) -> list[list[Node]]:
    """Kahn-style layering. Wave 0 = nodes with no deps; wave k = nodes whose deps all sit in
    waves < k. Nodes within a wave are mutually independent (safe to run concurrently). Creation
    order is preserved within a wave. Assumes the graph is acyclic (see ``_break_cycles``); any
    node left unscheduled defensively forms a final wave so this never loops forever.
    """
    remaining = list(nodes)
    resolved: set[str] = set()
    waves: list[list[Node]] = []
    while remaining:
        ready = [n for n in remaining if all(d in resolved for d in n.depends_on)]
        if not ready:  # defensive: a residual cycle - schedule everything left at once
            ready = list(remaining)
        waves.append(ready)
        for n in ready:
            resolved.add(n.id)
        remaining = [n for n in remaining if n not in ready]
    return waves


def _node_prompt(query: str, node: Node, observation: str, upstream: dict[str, str]) -> list[dict]:
    parts = [f"Overall question (for context only): {query}", f"Your node: {node.task}"]
    if observation:
        parts.append(f"Tool observation: {observation}")
    if upstream:
        joined = "\n\n".join(f"[{dep_id}]: {out}" for dep_id, out in upstream.items())
        parts.append(f"Results from the nodes you depend on:\n{joined}")
    user = "\n\n".join(parts)
    return [
        {"role": "system", "content": NODE_SYSTEM},
        {"role": "user", "content": user},
    ]


# --- Persistence helpers ------------------------------------------------------------------


def _mark_running(node: AgentStep) -> None:
    from . import store
    from .models import AgentStep

    store.update_step(node, status=AgentStep.Status.RUNNING, started_at=dt.now(UTC))


def _mark_done(node: AgentStep, *, observation: str, output: str) -> None:
    from . import store
    from .models import AgentStep

    store.update_step(
        node,
        status=AgentStep.Status.DONE,
        output=output,
        completed_at=dt.now(UTC),
        kind="dag",
        observation=observation,
    )


def _mark_error(node: AgentStep, *, observation: str, error: str) -> None:
    from . import store
    from .models import AgentStep

    store.update_step(
        node,
        status=AgentStep.Status.ERROR,
        error=error,
        completed_at=dt.now(UTC),
        kind="dag",
        observation=observation,
    )


# --- Public entrypoint --------------------------------------------------------------------


class DagStrategy(BaseStrategy):
    """Policy only: decompose into a dependency graph, then one wave per topological layer.

    The multi-wave case the driver's ``Wave`` exists for - ``orchestrator`` is the
    single-wave special case of this shape.
    """

    kind = "dag"
    event = "node"

    def __init__(self, run: AgentRun, model: str = ""):
        from . import store

        self.run = run
        self.model = model or None
        self.max_nodes = store.run_meta(run).max_nodes
        self.nodes: list[Node] = []
        self.waves: list[list[Node]] = []
        self.rows: dict[str, AgentStep] = {}
        self.outputs: dict[str, str] = {}
        self.observations: dict[str, str] = {}
        self.any_ok = False

    def intro(self) -> Generator[str]:
        from . import store
        from .models import AgentStep

        raw = self._call(_decompose_system(self.max_nodes), self.run.query)
        try:
            self.nodes = parse_nodes(raw, self.max_nodes)
        except ValueError:
            raise AbortedError("Orchestrator did not return a usable decomposition.") from None

        self.waves = topological_waves(self.nodes)
        wave_of = {n.id: w for w, wave in enumerate(self.waves) for n in wave}

        for order, node in enumerate(self.nodes):
            self.rows[node.id] = store.create_step(
                self.run,
                order,
                status=AgentStep.Status.PENDING,
                key=node.id,
                label=node.focus,
                task=node.task,
                wave=wave_of[node.id],
                depends_on=node.depends_on,
                tool=node.tool or "",
                tool_args=node.args,
            )

        plan = {
            "nodes": [
                {
                    "id": n.id,
                    "task": n.task,
                    "focus": n.focus,
                    "tool": n.tool,
                    "args": n.args,
                    "depends_on": n.depends_on,
                    "wave": wave_of[n.id],
                }
                for n in self.nodes
            ],
            "waves": [[n.id for n in wave] for wave in self.waves],
        }
        store.update_run(self.run, plan=plan)
        yield event("plan", nodes=plan["nodes"], waves=plan["waves"])

    def next_wave(self, index: int) -> Wave | None:
        if index >= len(self.waves):
            return None

        wave = self.waves[index]
        for node in wave:
            _mark_running(self.rows[node.id])

        observations = [tools.run_tool(n.tool, n.args or {}) if n.tool else "" for n in wave]
        for node, obs in zip(wave, observations, strict=True):
            self.observations[node.id] = obs

        return Wave(
            rows=[self.rows[n.id] for n in wave],
            # Each downstream node's prompt is injected with its upstream nodes' outputs,
            # which is what makes this a graph rather than a single fan-out.
            prompts=[
                _node_prompt(
                    self.run.query, n, obs, {d: self.outputs.get(d, "") for d in n.depends_on}
                )
                for n, obs in zip(wave, observations, strict=True)
            ],
            events=(event("wave", index=index, node_ids=[n.id for n in wave]),),
        )

    def absorb(self, row: AgentStep, result: dict) -> None:
        obs = self.observations.get(row.key, "")
        if result["ok"] is not None:
            self.any_ok = True
            self.outputs[row.key] = result["ok"]
            _mark_done(row, observation=obs, output=result["ok"])
        else:
            # A failed node still leaves a placeholder so its dependents get input.
            self.outputs[row.key] = f"(node failed: {result['error']})"
            _mark_error(row, observation=obs, error=result["error"])

    def result(self) -> Generator[str, None, Outcome]:
        if not self.any_ok:
            raise AbortedError("All nodes failed.")

        depended_on = {d for n in self.nodes for d in n.depends_on}
        terminal = [n for n in self.nodes if n.id not in depended_on] or self.nodes
        synth_user = f'The user asked: "{self.run.query}"\n\n' + "\n\n".join(
            f"### {n.focus}\n{self.outputs[n.id]}" for n in terminal
        )
        answer = self._call(SYNTH_SYSTEM, synth_user)
        return Outcome(answer, fields={"nodes": len(self.nodes), "waves": len(self.waves)})
        yield  # pragma: no cover - makes this a generator; the return above always wins

    def _call(self, system: str, user: str) -> str:
        from . import services

        return services.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=self.model,
        )


def run_dag(run: AgentRun, model: str = "") -> Generator[str]:
    """SSE generator. Decompose into a graph, run it wave by wave, synthesise the sinks."""
    strategy = DagStrategy(run, model)
    return drive_waves(run, strategy, model=strategy.model)
