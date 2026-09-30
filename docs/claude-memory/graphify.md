# Graphify code graph

Set up 2026-08-05. `graphify extract . --code-only` indexes the repo into
`graphify-out/graph.json` (gitignored); a post-commit hook rebuilds it. Served by
`apps/codegraph`, rendered at `/code-graph`.

## Use it for the Python backend. Do NOT trust it on the frontend.

Measured 2026-08-05 on this repo — this is the single most important fact about the tool here:

| | nodes | real edges (excl. `contains`/`method`) | per node | isolated |
|---|---|---|---|---|
| Python | 3,301 | 6,122 | **1.85** | 24% |
| TypeScript | 1,055 | 271 | **0.26** | **73%** |

**Root cause: graphify does not resolve `tsconfig.json` path aliases.** This codebase mandates
`@/` imports (467 on disk vs 30 relative); graphify extracted 99 TS import edges — essentially
only the relative ones plus npm packages. There is no CLI flag or config for aliases.

Concretely: `frontend/src/routes/code-graph.tsx` calls `getCodeGraph` on line 74 and the graph
holds **zero** import or call edges out of that file. 76% of all TS edges are just `contains`
(file-holds-symbol). So a frontend answer from graphify is not evidence of anything — use grep.

There are also **~2 cross-language edges total**. No HTTP-boundary linking, so it can never
answer "which endpoint does this page call".

## What it answers better than grep (backend only)

- **`graphify affected "<symbol>"`** — the impact set of a change, *including indirect callers
  and every test that would break*, each with `file:line`. This is the one that beats grep
  outright: grep finds the name, `affected` finds the blast radius.
- **`graphify explain "<symbol>"`** — every call site with `file:line` and an
  `EXTRACTED` (AST fact) vs `INFERRED` (guess) tag per edge. Strongest on common-word symbols:
  `chat` gives 70 noisy grep hits vs 33 typed directed edges, and it surfaces cross-app callers
  in `companies/` and `knowledge_graph/` that scanning `llm_analysis/` alone would miss.
- **`graphify god-nodes`** — architectural hubs by degree.

## What it does NOT beat

`graphify query "<question>"` is a noisy BFS, and `graphify path A B` routes through whatever
trivially connects two nodes (`AgentRun`, or `run_llm_live.py`, a management command that
imports everything). Single-symbol lookups are still faster with grep. CLAUDE.md already
documents architecture in prose — graphify's edge is line numbers and transitive reach.

## Access from Claude Code

Three paths, all verified 2026-08-05:

- **Bash CLI** — always works, zero standing context cost. This is the default.
- **`/graphify` skill** — installed at `~/.claude/skills/graphify/SKILL.md` (user-global).
  Skills register at **startup**, so it is unavailable in the session that installed it.
- **MCP server** — `claude mcp add graphify -- graphify-mcp`, local scope. Needs
  `uv tool install "graphifyy[mcp]"` first; without the extra it fails with
  `ModuleNotFoundError: No module named 'mcp'`. Costs ~1,500 tokens of tool definitions in
  **every** session in this project.
  - 10 tools. `get_node`/`get_neighbors`/`god_nodes`/`graph_stats` mirror the CLI;
    `query_graph`/`shortest_path` inherit the CLI's weaknesses.
  - **No `affected` tool** — `get_neighbors` is depth-1 only, so the best capability still
    needs Bash.
  - Uniquely new: `list_prs` / `get_pr_impact` / `triage_prs` — PR blast radius by community.
    Untested against a real PR (none were open).

## Gotchas

- Always `--code-only`. Without it the doc/PDF/image pass ships file contents to an LLM.
- PyPI package is `graphifyy`; CLI is `graphify`.
- `graphify update .` is the cheap incremental rebuild (~6 s here, AST only, no LLM).
- `graphify hook install` also writes a `.gitattributes` merge-driver rule — pointless here
  (`graphify-out/` is gitignored) and it was deleted.

Colour encoding on the UI is **layer**, not graphify's Leiden `community` — this repo produces
~400 communities and a categorical scale is unreadable past a handful. See [[echarts]].
