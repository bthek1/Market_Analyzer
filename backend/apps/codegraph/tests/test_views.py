import pytest


@pytest.mark.django_db
class TestCodeGraphView:
    def test_unauthenticated_returns_401(self, api_client, graph_file):
        assert api_client.get("/api/codegraph/graph/").status_code == 401

    def test_returns_nodes_and_edges(self, auth_client, graph_file):
        response = auth_client.get("/api/codegraph/graph/")
        assert response.status_code == 200
        data = response.json()
        assert len(data["nodes"]) == 5
        assert len(data["edges"]) == 4
        assert data["built_at_commit"] == "abc1234"

    def test_missing_graph_returns_404_with_hint(self, auth_client, no_graph_file):
        # The state every fresh clone and prod deploy is in - must be a clean 404, not a 500.
        response = auth_client.get("/api/codegraph/graph/")
        assert response.status_code == 404
        assert "hint" in response.json()

    def test_corrupt_graph_returns_409(self, auth_client, tmp_path, settings):
        path = tmp_path / "graph.json"
        path.write_text("{broken", encoding="utf-8")
        settings.GRAPHIFY_GRAPH_PATH = str(path)
        assert auth_client.get("/api/codegraph/graph/").status_code == 409

    def test_confidence_filter(self, auth_client, graph_file):
        data = auth_client.get("/api/codegraph/graph/?confidence=EXTRACTED").json()
        assert all(e["confidence"] == "EXTRACTED" for e in data["edges"])

    def test_kind_filter(self, auth_client, graph_file):
        data = auth_client.get("/api/codegraph/graph/?kind=concept").json()
        assert [n["id"] for n in data["nodes"]] == ["base_ui_react"]

    def test_search_filter(self, auth_client, graph_file):
        data = auth_client.get("/api/codegraph/graph/?search=run_dag").json()
        assert [n["id"] for n in data["nodes"]] == ["dag_run_dag"]

    def test_community_filter(self, auth_client, graph_file):
        data = auth_client.get("/api/codegraph/graph/?community=8").json()
        assert [n["id"] for n in data["nodes"]] == ["tools_run_tool"]

    def test_layer_filter(self, auth_client, graph_file):
        data = auth_client.get("/api/codegraph/graph/?layer=frontend").json()
        assert [n["id"] for n in data["nodes"]] == ["base_ui_react"]

    def test_module_filter(self, auth_client, graph_file):
        data = auth_client.get("/api/codegraph/graph/?module=backend/apps/companies").json()
        assert [n["id"] for n in data["nodes"]] == ["orphan_node"]

    def test_path_filter(self, auth_client, graph_file):
        data = auth_client.get("/api/codegraph/graph/?path=frontend/").json()
        assert [n["id"] for n in data["nodes"]] == ["base_ui_react"]

    def test_limit_is_applied(self, auth_client, graph_file):
        data = auth_client.get("/api/codegraph/graph/?limit=2").json()
        assert data["stats"]["returned_nodes"] == 2
        assert data["stats"]["truncated"] is True

    def test_garbage_limit_falls_back_to_default(self, auth_client, graph_file):
        data = auth_client.get("/api/codegraph/graph/?limit=abc").json()
        assert data["stats"]["limit"] == 400

    def test_blank_params_are_ignored(self, auth_client, graph_file):
        data = auth_client.get("/api/codegraph/graph/?kind=&search=&community=").json()
        assert len(data["nodes"]) == 5


@pytest.mark.django_db
class TestCodeGraphNodeView:
    def test_unauthenticated_returns_401(self, api_client, graph_file):
        assert api_client.get("/api/codegraph/nodes/tools_run_tool/").status_code == 401

    def test_returns_node_with_neighbours(self, auth_client, graph_file):
        response = auth_client.get("/api/codegraph/nodes/tools_run_tool/")
        assert response.status_code == 200
        data = response.json()
        assert data["label"] == "run_tool()"
        assert len(data["incoming"]) == 2
        assert len(data["outgoing"]) == 1

    def test_unknown_node_returns_404(self, auth_client, graph_file):
        assert auth_client.get("/api/codegraph/nodes/nope/").status_code == 404

    def test_missing_graph_returns_404(self, auth_client, no_graph_file):
        assert auth_client.get("/api/codegraph/nodes/tools_run_tool/").status_code == 404
