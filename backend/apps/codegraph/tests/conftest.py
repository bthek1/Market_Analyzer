"""Fixtures writing a miniature graphify graph.json to a tmp path.

The shape mirrors a real `graphify extract --code-only` dump (NetworkX node-link: `nodes` +
`links`, node `file_type`/`source_file`/`source_location`, edge `relation`/`confidence`), so
these tests pin the normalisation in services.py against graphify's actual output format.
"""

import json

import pytest

from apps.codegraph import services

RAW_GRAPH = {
    "directed": True,
    "built_at_commit": "abc1234",
    "nodes": [
        {
            "id": "tools_run_tool",
            "label": "run_tool()",
            "file_type": "code",
            "source_file": "backend/apps/llm_analysis/tools.py",
            "source_location": "L363",
            "community": 8,
            "community_name": "Community 8",
        },
        {
            "id": "react_run_react",
            "label": "run_react()",
            "file_type": "code",
            "source_file": "backend/apps/llm_analysis/react.py",
            "source_location": "L182",
            "community": 5,
            "community_name": "Community 5",
        },
        {
            "id": "dag_run_dag",
            "label": "run_dag()",
            "file_type": "code",
            "source_file": "backend/apps/llm_analysis/dag.py",
            "source_location": "L371",
            "community": 3,
            "community_name": "Community 3",
        },
        {
            "id": "base_ui_react",
            "label": "@base-ui/react",
            "file_type": "concept",
            "source_file": "frontend/package.json",
            "source_location": "L15",
            "community": 298,
            "community_name": "Community 298",
        },
        {
            "id": "orphan_node",
            "label": "orphan()",
            "file_type": "code",
            "source_file": "backend/apps/companies/services.py",
            "source_location": "L1",
            "community": 1,
            "community_name": "Community 1",
        },
    ],
    "links": [
        {
            "source": "react_run_react",
            "target": "tools_run_tool",
            "relation": "calls",
            "confidence": "EXTRACTED",
            "context": "call",
            "source_file": "backend/apps/llm_analysis/react.py",
            "source_location": "L182",
            "weight": 1.0,
        },
        {
            "source": "dag_run_dag",
            "target": "tools_run_tool",
            "relation": "calls",
            "confidence": "EXTRACTED",
            "context": "call",
            "source_file": "backend/apps/llm_analysis/dag.py",
            "source_location": "L371",
            "weight": 1.0,
        },
        {
            "source": "dag_run_dag",
            "target": "react_run_react",
            "relation": "references",
            "confidence": "INFERRED",
            "context": "heuristic",
            "source_file": "backend/apps/llm_analysis/dag.py",
            "source_location": "L400",
            "weight": 0.5,
        },
        {
            "source": "tools_run_tool",
            "target": "orphan_node",
            "relation": "calls",
            "confidence": "EXTRACTED",
            "context": "call",
            "source_file": "backend/apps/llm_analysis/tools.py",
            "source_location": "L367",
            "weight": 1.0,
        },
        # Dangling: `missing_node` is not in `nodes` - services must drop this edge.
        {
            "source": "tools_run_tool",
            "target": "missing_node",
            "relation": "calls",
            "confidence": "EXTRACTED",
            "weight": 1.0,
        },
    ],
}


@pytest.fixture(autouse=True)
def _clear_graph_cache():
    """services memoises on mtime; tmp files across tests can collide, so reset each test."""
    services._cache["key"] = None
    services._cache["graph"] = None
    yield
    services._cache["key"] = None
    services._cache["graph"] = None


@pytest.fixture
def graph_file(tmp_path, settings):
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(RAW_GRAPH), encoding="utf-8")
    settings.GRAPHIFY_GRAPH_PATH = str(path)
    return path


@pytest.fixture
def no_graph_file(tmp_path, settings):
    settings.GRAPHIFY_GRAPH_PATH = str(tmp_path / "does-not-exist.json")
