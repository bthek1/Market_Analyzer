from __future__ import annotations

import json
import queue
import threading
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor

import httpx
from django.contrib.auth import get_user_model
from django.db import connection, transaction

from core.tracing import attached, current_context, record_error, set_attributes, span

from .config import get_llm_config


class OllamaServiceError(Exception):
    pass


def _base_url() -> str:
    return get_llm_config().base_url.rstrip("/")


def _model(override: str | None) -> str:
    return override or get_llm_config().main_model


def _classifier_model() -> str:
    """The cheap, fast model used for classification regardless of the run's main model."""
    return get_llm_config().classifier_model


def _timeout() -> int:
    return get_llm_config().timeout


def chat(
    messages: list[dict],
    model: str | None = None,
    *,
    think: bool = False,
    temperature: float | None = None,
    format: dict | str | None = None,
) -> str:
    """Single blocking chat round-trip. Returns assistant content string.

    ``think=False`` disables qwen3-style thinking (harmless on models that ignore it).
    ``temperature`` (when provided) is passed through as an Ollama sampling option so
    callers can spread samples (e.g. voting); omitting it leaves behaviour unchanged.
    ``format`` (when provided) is forwarded as Ollama's structured-output constraint -
    a JSON schema dict or the literal string ``"json"``; omitting it is unchanged.
    """
    payload = {
        "model": _model(model),
        "messages": messages,
        "stream": False,
        "think": think,
    }
    # num_ctx is ALWAYS sent. Ollama's default is 4096 and it truncates silently rather
    # than erroring - measured against the live host, a 12,052-token prompt reported
    # prompt_eval_count=4095 and the model answered from the surviving third. Nothing
    # upstream sees a failure, so the symptom is quietly degraded answers.
    options: dict = {"num_ctx": get_llm_config().num_ctx}
    if temperature is not None:
        options["temperature"] = temperature
    payload["options"] = options
    if format is not None:
        payload["format"] = format

    # This span is the reason phase 4 exists. A prometheus histogram could not cover
    # these calls: they run in gunicorn workers AND Celery prefork children, whose
    # registries cannot be merged without PROMETHEUS_MULTIPROC_DIR, so a web-only
    # metric would look complete while missing every AI summary and KG expansion.
    with span(
        "ollama.chat",
        **{
            "llm.model": payload["model"],
            "llm.temperature": temperature,
            "llm.structured_output": format is not None,
            "llm.messages": len(messages),
        },
    ) as sp:
        try:
            resp = httpx.post(
                f"{_base_url()}/api/chat",
                json=payload,
                timeout=_timeout(),
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            error = OllamaServiceError(str(exc))
            record_error(sp, error)
            raise error from exc

        body = resp.json()
        # Ollama reports token counts per call. They are the closest thing to a cost
        # signal we have, and they are free here - already in the response body.
        set_attributes(
            sp,
            **{
                "llm.tokens.prompt": body.get("prompt_eval_count"),
                "llm.tokens.completion": body.get("eval_count"),
            },
        )
        return body["message"]["content"]


def chat_tokens(
    messages: list[dict], model: str | None = None, *, think: bool = False
) -> Generator[str]:
    """Yield the assistant's content as it arrives, one chunk per token batch.

    The RAW primitive: no SSE framing, no JSON envelope, just text. The chat agent feeds
    these to ``_events.delta`` - a workflow module may not hand-roll a ``data:`` line, and
    should not have to know that one exists in order to stream a reply.

    The span is still named ``ollama.chat_stream``: it names the OPERATION (a streaming chat
    call to Ollama), not the Python function, and renaming it would silently empty the
    tracing dashboard panels and span metrics that key on it.
    """
    payload = {
        "model": _model(model),
        "messages": messages,
        "stream": True,
        "think": think,
        # See `chat` - the 4096 default truncates silently on the streaming path too.
        "options": {"num_ctx": get_llm_config().num_ctx},
    }
    # The span covers the WHOLE stream, not just the request: for a streaming call the
    # interesting duration is time-to-last-token, and chunks are counted so a stream
    # that died early is distinguishable from one that simply had little to say.
    with span("ollama.chat_stream", **{"llm.model": payload["model"]}) as sp:
        chunks = 0
        try:
            with httpx.stream(
                "POST",
                f"{_base_url()}/api/chat",
                json=payload,
                timeout=_timeout(),
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        chunks += 1
                        yield content
                    if chunk.get("done"):
                        set_attributes(sp, **{"llm.chunks": chunks})
                        return
            set_attributes(sp, **{"llm.chunks": chunks})
        except httpx.HTTPError as exc:
            set_attributes(sp, **{"llm.chunks": chunks})
            error = OllamaServiceError(str(exc))
            record_error(sp, error)
            raise error from exc


def chat_many(
    batches: list[list[dict]],
    model: str | None = None,
    *,
    think: bool = False,
    temperatures: list[float | None] | None = None,
    max_workers: int | None = None,
) -> list[dict]:
    """Run several independent chat calls concurrently. Order preserved.

    Bounded to ``OLLAMA_NUM_PARALLEL`` so we never oversubscribe the server's slots.
    Returns one result dict per input batch: ``{"ok": <content>, "error": None}`` on
    success or ``{"ok": None, "error": <message>}`` on failure. A single failed call
    never drops the others.

    ``temperatures`` (when provided) must hold one entry per batch and is passed through
    to each call (e.g. to spread voting samples). When omitted, behaviour is unchanged.
    """
    if not batches:
        return []

    workers = max_workers or get_llm_config().num_parallel
    workers = max(1, min(workers, len(batches)))

    if temperatures is None:
        temps: list[float | None] = [None] * len(batches)
    else:
        temps = list(temperatures)

    # ThreadPoolExecutor workers do NOT inherit the OTel context (it rides a
    # ContextVar), so without carrying it across explicitly every fan-out call would
    # start its own ROOT trace and the concurrency would be invisible - the whole point
    # of instrumenting this function. Same root cause as the daemon-thread gap in
    # stream_in_background below.
    with span("ollama.chat_many", **{"llm.batches": len(batches), "llm.workers": workers}) as sp:
        # Captured INSIDE the span, not before it. Captured outside, the workers attach
        # to this function's CALLER and every fan-out call becomes a SIBLING of
        # ollama.chat_many rather than a child - so the span that exists purely to group
        # the fan-out contains none of it. Confirmed in prod before the fix: three
        # concurrent ollama.chat spans sat at the same depth as their chat_many.
        ctx = current_context()

        def _one(args: tuple[list[dict], float | None]) -> dict:
            messages, temperature = args
            with attached(ctx):
                try:
                    if temperature is None:
                        content = chat(messages, model=model, think=think)
                    else:
                        content = chat(messages, model=model, think=think, temperature=temperature)
                    return {"ok": content, "error": None}
                except OllamaServiceError as exc:
                    return {"ok": None, "error": str(exc)}

        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_one, zip(batches, temps, strict=True)))
        set_attributes(sp, **{"llm.failures": sum(1 for r in results if r["error"])})
        return results


def summarise(text: str, model: str | None = None) -> str:
    """Summarise arbitrary text using Ollama."""
    messages = [
        {
            "role": "system",
            "content": (
                "You are a concise summarisation assistant. "
                "Summarise the provided text clearly and briefly. "
                "Focus on the key points. Output only the summary."
            ),
        },
        {"role": "user", "content": text},
    ]
    return chat(messages, model=model)


def analyse(text: str, context: str | None = None, model: str | None = None) -> str:
    """Analyse text with optional user-provided context."""
    system = (
        "You are a financial and general analysis assistant. "
        "Analyse the provided content thoroughly. "
        "Be precise, structured, and highlight key insights."
    )
    user_content = text
    if context:
        user_content = f"Context: {context}\n\n{text}"
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]
    return chat(messages, model=model)


def embed(texts: list[str], model: str | None = None) -> list[list[float]]:
    """Embed one or more texts via Ollama /api/embed. Returns one vector per input."""
    if not texts:
        return []
    payload = {
        "model": model or get_llm_config().embed_model,
        "input": texts,
    }
    with span("ollama.embed", **{"llm.model": payload["model"], "llm.inputs": len(texts)}) as sp:
        try:
            resp = httpx.post(
                f"{_base_url()}/api/embed",
                json=payload,
                timeout=_timeout(),
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            error = OllamaServiceError(str(exc))
            record_error(sp, error)
            raise error from exc
        return resp.json()["embeddings"]


def list_models() -> list[dict]:
    """Return available Ollama models as [{name, size_gb}]."""
    try:
        resp = httpx.get(f"{_base_url()}/api/tags", timeout=10)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise OllamaServiceError(str(exc)) from exc
    models = resp.json().get("models", [])
    return [
        {
            "name": m["name"],
            "size_gb": round(m.get("size", 0) / 1_073_741_824, 2),
        }
        for m in models
        if "completion" in m.get("capabilities", [])
    ]


# Status value written when a run is cancelled by the user. Not in the model
# Status choices (no DB constraint enforces them) so adding it needs no migration;
# the value fits the column's max_length and is read back verbatim by serializers.
RUN_STATUS_STOPPED = "stopped"


def request_run_stop(model, run_id, user) -> bool:
    """Cooperatively cancel a still-running workflow by flipping its DB status.

    The background worker (``stream_in_background``) polls the run's status between
    events and unwinds the generator once it sees ``stopped``. Going through the DB
    (rather than an in-process flag) means the cancel request works even when it is
    served by a different process/worker than the one running the stream. Returns
    True if a running row was flipped, False if nothing was running to stop.
    """
    return (
        model.objects.filter(pk=run_id, user=user, status="running").update(
            status=RUN_STATUS_STOPPED
        )
        > 0
    )


def stream_in_background(gen: Generator[str], run=None) -> Generator[str]:
    """Drive an SSE workflow generator from a daemon thread so the run completes
    even if the HTTP client disconnects, and so it can be cancelled mid-flight.

    The workflow generators persist every step and the terminal run status to the
    DB as they execute. Running them directly inside the streaming response ties
    that work to the client connection: when the user refreshes the Agents page
    the browser aborts the fetch, the generator is closed mid-flight, and the run
    is orphaned at ``status="running"``.

    Here a background thread drains the generator to completion (so all DB writes
    happen regardless of the client), bridging each event to the connected client
    through an unbounded queue. If the client goes away the queue simply stops
    being read while the worker keeps draining to the DB. The frontend reconnects
    to the persisted run on the next page load.

    When ``run`` is given the worker also polls the run's status between events;
    if a cancel request has flipped it to ``stopped`` (see ``request_run_stop``)
    the worker closes the generator at the current step boundary, persists the
    ``stopped`` status, and ends the stream. ``GeneratorExit`` is a ``BaseException``
    (not ``Exception``), so it unwinds cleanly through the workflows' per-step
    ``except Exception`` guards.
    """
    events: queue.Queue = queue.Queue()
    sentinel = object()
    model = type(run) if run is not None else None
    run_pk = run.pk if run is not None else None

    # The OTel context rides a ContextVar, which a bare Thread does not inherit - so
    # without capturing it here every agent run would start its own root trace,
    # detached from the request that launched it. This is the SAME gap that forced
    # agent runs to be correlated by AgentRun.id instead of request_id (see
    # core.middleware), closed for traces.
    ctx = current_context()

    def _stop_requested() -> bool:
        if model is None:
            return False
        try:
            status = model.objects.filter(pk=run_pk).values_list("status", flat=True).first()
        except Exception:
            return False
        return status == RUN_STATUS_STOPPED

    def _worker() -> None:
        iterator = iter(gen)
        # One span per RUN, wrapping the whole workflow. Every ollama.chat,
        # ollama.chat_many and agent.tool span below nests inside it, which is what
        # turns a fan-out workflow into a single readable waterfall instead of a pile
        # of unrelated traces. The run id is a high-cardinality attribute, which is
        # free in Tempo and would be ruinous as a Loki label.
        run_attrs = {}
        if run is not None:
            run_attrs = {
                "agent.run_id": str(run_pk),
                "agent.kind": getattr(run, "kind", None),
                "agent.model": getattr(run, "model", None),
            }
        with attached(ctx), span("agent.run", **run_attrs) as sp:
            _drain(iterator, sp)

    def _drain(iterator, sp) -> None:
        try:
            while True:
                if _stop_requested():
                    gen.close()
                    # Force the terminal status to stopped unless it already finished.
                    model.objects.filter(pk=run_pk).exclude(status__in=["done", "error"]).update(
                        status=RUN_STATUS_STOPPED
                    )
                    events.put(f"data: {json.dumps({'event': 'stopped'})}\n\n")
                    break
                try:
                    event = next(iterator)
                except StopIteration:
                    break
                events.put(event)
        except Exception as exc:  # defensive: a worker must never crash silently
            record_error(sp, exc)
            events.put(f"data: {json.dumps({'error': str(exc)})}\n\n")
        finally:
            events.put(sentinel)
            # Release this thread's own DB connection (ORM opens one lazily per thread).
            connection.close()

    threading.Thread(target=_worker, name="llm-stream", daemon=True).start()

    def _live() -> Generator[str]:
        while True:
            event = events.get()
            if event is sentinel:
                break
            yield event

    return _live()


def create_agent_run(user: get_user_model(), query: str, model: str, kind: str, **fields):
    """Create a unified ``AgentRun`` of the given ``kind``.

    Thin wrapper over ``store.create_run``: ``fields`` is the kind-specific meta, validated
    against ``meta_spec`` before it is stored in ``AgentRun.meta``. Child ``AgentStep`` rows
    are pre-seeded by the caller when needed (chain/parallel); the rest create them mid-run.
    """
    from . import store

    return store.create_run(user, query, model, kind=kind, **fields)


def create_chain_run(user: get_user_model(), query: str, model: str):
    """Create a chain AgentRun and pre-seed its step (AgentStep) rows from CHAIN_STEPS.

    The per-step ``step_id`` is stored in ``AgentStep.key``.
    """
    from . import store
    from .chain import CHAIN_STEPS

    with transaction.atomic():
        run = store.create_run(user, query, model, kind="chain")
        store.seed_steps(
            run, [{"order": s.order, "key": s.id, "label": s.label} for s in CHAIN_STEPS]
        )
    return run


def create_route_run(user: get_user_model(), query: str, model: str):
    from . import store

    return store.create_run(user, query, model, kind="route")


def create_react_run(
    user: get_user_model(),
    query: str,
    model: str,
    max_steps: int,
):
    from . import store

    return store.create_run(user, query, model, kind="react", max_steps=max_steps)


def create_chat_run(
    user: get_user_model(),
    query: str,
    model: str,
    max_steps: int,
    session=None,
):
    """One conversational TURN. ``query`` is the user message; the reply lands in ``output``.

    ``turn`` is derived from the session rather than passed in: the caller counting turns
    itself is how an off-by-one gets written, and the count is one indexed query.
    """
    from . import store

    turn = session.turns.filter(kind="chat").count() if session is not None else 0
    run = store.create_run(
        user, query, model, kind="chat", max_steps=max_steps, turn=turn, tools_used=[]
    )
    if session is not None:
        run.session = session
        run.save(update_fields=["session"])
        # Bumps ``updated_at``, which is the session sidebar's ordering.
        session.save(update_fields=["updated_at"])
    return run


def chat_session_has_running_turn(session) -> bool:
    """Whether a turn of ``session`` is still in flight.

    Two concurrent turns FORK the transcript: the second rehydrates without the first's reply,
    then both write. The guard is cheap and the failure is silent, which is a bad combination
    to leave to chance.
    """
    from .models import AgentRun

    return session.turns.filter(kind="chat", status=AgentRun.Status.RUNNING).exists()


def create_eo_run(
    user: get_user_model(),
    query: str,
    model: str,
    max_iterations: int,
    threshold: int,
):
    from . import store

    return store.create_run(
        user,
        query,
        model,
        kind="eval_opt",
        max_iterations=max_iterations,
        threshold=threshold,
    )


def create_plan_run(
    user: get_user_model(),
    query: str,
    model: str,
    max_steps: int,
    allow_replan: bool,
):
    from . import store

    return store.create_run(
        user,
        query,
        model,
        kind="plan_exec",
        max_steps=max_steps,
        allow_replan=allow_replan,
        replans=0,  # legacy PlanExecRun.replans defaulted to 0; preserve that contract
    )


def create_orchestrator_run(
    user: get_user_model(),
    query: str,
    model: str,
    max_workers: int,
):
    """Create an orchestrator AgentRun. Worker (AgentStep) rows are NOT pre-seeded - the
    loop creates them after the decomposition (the subtasks are not known upfront)."""
    from . import store

    return store.create_run(user, query, model, kind="orchestrator", max_workers=max_workers)


def create_multiagent_run(
    user: get_user_model(),
    query: str,
    model: str,
    max_tools: int,
):
    """Create a multiagent AgentRun. Step rows are NOT pre-seeded - the loop creates them
    after the supervisor's routing decision (the roster is decided per query)."""
    from . import store

    return store.create_run(user, query, model, kind="multiagent", max_tools=max_tools)


def create_dag_run(
    user: get_user_model(),
    query: str,
    model: str,
    max_nodes: int,
):
    """Create a dag AgentRun. Node (AgentStep) rows are NOT pre-seeded - the loop creates them
    after the orchestrator decomposes the query into a graph (the nodes are not known upfront)."""
    from . import store

    return store.create_run(user, query, model, kind="dag", max_nodes=max_nodes)


def create_autonomous_run(
    user: get_user_model(),
    query: str,
    model: str,
    max_cycles: int,
    max_subagents: int,
):
    """Create an autonomous AgentRun. Cycle (AgentStep) rows are NOT pre-seeded - the loop
    creates them as it runs (the cycle count and tasks are decided by the controller at runtime)."""
    from . import store

    return store.create_run(
        user,
        query,
        model,
        kind="autonomous",
        max_cycles=max_cycles,
        max_subagents=max_subagents,
    )


def create_browser_run(
    user: get_user_model(),
    query: str,
    model: str,
    provider: str,
    max_steps: int,
    allowed_domains: list[str],
):
    """Create a browser AgentRun. Step rows are NOT pre-seeded - browser-use decides how
    many actions the task takes, and each one is persisted as it happens."""
    from . import store

    return store.create_run(
        user,
        query,
        model,
        kind="browser",
        provider=provider,
        max_steps=max_steps,
        allowed_domains=allowed_domains,
    )


def create_parallel_run(
    user: get_user_model(),
    query: str,
    model: str,
    strategy: str,
    n: int,
):
    """Create a parallel AgentRun and pre-seed its task (AgentStep) rows.

    Sectioning seeds one task per ``ANALYSIS_ASPECTS`` entry; voting seeds ``n`` vote rows.
    The per-task ``task_id`` is stored in ``AgentStep.key``.
    """
    from . import store
    from .models import AgentRun
    from .router import ANALYSIS_ASPECTS

    with transaction.atomic():
        run = store.create_run(user, query, model, kind="parallel", strategy=strategy, n=n)
        if strategy == AgentRun.Strategy.VOTING:
            rows = [{"order": i, "key": f"vote_{i}", "label": f"Vote {i + 1}"} for i in range(n)]
        else:
            rows = [
                {"order": order, "key": name.lower(), "label": name}
                for order, (name, _) in enumerate(ANALYSIS_ASPECTS)
            ]
        store.seed_steps(run, rows)
    return run
