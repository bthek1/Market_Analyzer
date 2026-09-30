import json

import pytest

from apps.codegraph import services


class TestLoadGraph:
    def test_missing_file_raises_graph_not_built(self, no_graph_file):
        with pytest.raises(services.GraphNotBuiltError):
            services.load_graph()

    def test_corrupt_file_raises_graph_unreadable(self, tmp_path, settings):
        path = tmp_path / "graph.json"
        path.write_text("{not json", encoding="utf-8")
        settings.GRAPHIFY_GRAPH_PATH = str(path)
        with pytest.raises(services.GraphUnreadableError):
            services.load_graph()

    def test_normalises_graphify_field_names(self, graph_file):
        graph = services.load_graph()
        node = next(n for n in graph["nodes"] if n["id"] == "tools_run_tool")
        assert node["label"] == "run_tool()"
        assert node["file"] == "backend/apps/llm_analysis/tools.py"
        assert node["line"] == "L363"
        # graphify's `file_type` is the node kind, not a MIME type.
        assert node["kind"] == "code"
        assert node["community"] == 8
        assert node["layer"] == "backend"
        assert node["module"] == "backend/apps/llm_analysis"

    def test_reads_links_key_as_edges(self, graph_file):
        graph = services.load_graph()
        assert graph["edges"]
        assert {"source", "target", "relation", "confidence"} <= set(graph["edges"][0])

    def test_drops_edges_pointing_at_unknown_nodes(self, graph_file):
        graph = services.load_graph()
        assert not [e for e in graph["edges"] if e["target"] == "missing_node"]
        assert len(graph["edges"]) == 4

    def test_memoises_until_file_changes(self, graph_file):
        first = services.load_graph()
        assert services.load_graph() is first

        payload = json.loads(graph_file.read_text(encoding="utf-8"))
        payload["nodes"] = payload["nodes"][:1]
        payload["links"] = []
        graph_file.write_text(json.dumps(payload), encoding="utf-8")
        # Force a distinct mtime so the cache key changes on filesystems with coarse clocks.
        import os

        stat = graph_file.stat()
        os.utime(graph_file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

        assert len(services.load_graph()["nodes"]) == 1


class TestGetSubgraph:
    def test_returns_all_nodes_when_unfiltered(self, graph_file):
        result = services.get_subgraph()
        assert result["stats"]["total_nodes"] == 5
        assert result["stats"]["returned_nodes"] == 5
        assert result["stats"]["truncated"] is False

    def test_orders_by_degree_descending(self, graph_file):
        result = services.get_subgraph()
        # run_tool is called by react and dag and calls orphan -> the highest-degree node.
        assert result["nodes"][0]["id"] == "tools_run_tool"
        assert result["nodes"][0]["degree"] == 3

    def test_limit_truncates_and_flags_it(self, graph_file):
        result = services.get_subgraph(limit=2)
        assert result["stats"]["returned_nodes"] == 2
        assert result["stats"]["matched_nodes"] == 5
        assert result["stats"]["truncated"] is True

    def test_limit_prunes_edges_to_surviving_nodes(self, graph_file):
        result = services.get_subgraph(limit=2)
        kept = {n["id"] for n in result["nodes"]}
        for edge in result["edges"]:
            assert edge["source"] in kept
            assert edge["target"] in kept

    def test_limit_is_clamped_to_max(self, graph_file):
        assert services.get_subgraph(limit=999_999)["stats"]["limit"] == services.MAX_LIMIT

    def test_zero_limit_falls_back_to_the_default(self, graph_file):
        # 0 means "unspecified", same as omitting it - only a negative is clamped to 1.
        assert services.get_subgraph(limit=0)["stats"]["limit"] == services.DEFAULT_LIMIT
        assert services.get_subgraph(limit=-5)["stats"]["limit"] == 1

    def test_confidence_filter_drops_inferred_edges(self, graph_file):
        result = services.get_subgraph(confidence="EXTRACTED")
        assert all(e["confidence"] == "EXTRACTED" for e in result["edges"])
        assert len(result["edges"]) == 3

    def test_degree_reflects_edge_filters(self, graph_file):
        # run_dag has 2 edges overall but only 1 EXTRACTED one.
        result = services.get_subgraph(confidence="EXTRACTED")
        node = next(n for n in result["nodes"] if n["id"] == "dag_run_dag")
        assert node["degree"] == 1

    def test_relation_filter(self, graph_file):
        result = services.get_subgraph(relation="references")
        assert all(e["relation"] == "references" for e in result["edges"])

    def test_kind_filter(self, graph_file):
        result = services.get_subgraph(kind="concept")
        assert [n["id"] for n in result["nodes"]] == ["base_ui_react"]

    def test_community_filter(self, graph_file):
        result = services.get_subgraph(community=8)
        assert [n["id"] for n in result["nodes"]] == ["tools_run_tool"]

    def test_search_matches_label_or_path(self, graph_file):
        assert {n["id"] for n in services.get_subgraph(search="run_dag")["nodes"]} == {
            "dag_run_dag"
        }
        assert {n["id"] for n in services.get_subgraph(search="companies/")["nodes"]} == {
            "orphan_node"
        }

    def test_search_is_case_insensitive(self, graph_file):
        assert services.get_subgraph(search="RUN_TOOL")["nodes"][0]["id"] == "tools_run_tool"

    def test_layer_is_derived_from_the_path(self, graph_file):
        result = services.get_subgraph()
        by_id = {n["id"]: n for n in result["nodes"]}
        assert by_id["base_ui_react"]["layer"] == "frontend"
        assert by_id["tools_run_tool"]["layer"] == "backend"

    def test_layer_filter(self, graph_file):
        result = services.get_subgraph(layer="frontend")
        assert [n["id"] for n in result["nodes"]] == ["base_ui_react"]

    def test_module_filter(self, graph_file):
        result = services.get_subgraph(module="backend/apps/companies")
        assert [n["id"] for n in result["nodes"]] == ["orphan_node"]

    def test_layer_facet_is_bounded(self, graph_file):
        # The colour encoding must stay at a handful of values, unlike community (~400 here).
        layers = dict(services.get_subgraph()["facets"]["layers"])
        assert layers == {"backend": 4, "frontend": 1}

    def test_path_prefix_filter(self, graph_file):
        result = services.get_subgraph(path_prefix="frontend/")
        assert [n["id"] for n in result["nodes"]] == ["base_ui_react"]

    def test_facets_are_computed_over_the_whole_graph(self, graph_file):
        # Facets must not shrink when the view narrows, or the UI dropdowns would vanish.
        result = services.get_subgraph(kind="concept")
        kinds = dict(result["facets"]["kinds"])
        assert kinds == {"code": 4, "concept": 1}
        assert dict(result["facets"]["confidences"]) == {"EXTRACTED": 3, "INFERRED": 1}

    def test_missing_file_raises(self, no_graph_file):
        with pytest.raises(services.GraphNotBuiltError):
            services.get_subgraph()


class TestGetNodeDetail:
    def test_returns_neighbours_split_by_direction(self, graph_file):
        detail = services.get_node_detail("tools_run_tool")
        assert detail["label"] == "run_tool()"
        assert {e["node"]["id"] for e in detail["incoming"]} == {"react_run_react", "dag_run_dag"}
        assert [e["node"]["id"] for e in detail["outgoing"]] == ["orphan_node"]
        assert detail["degree"] == 3

    def test_unknown_node_returns_none(self, graph_file):
        assert services.get_node_detail("nope") is None
