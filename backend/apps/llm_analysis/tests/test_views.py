from unittest.mock import patch

import pytest

from apps.llm_analysis.services import OllamaServiceError

CHAT_URL = "/api/llm/chat/"
SUMMARISE_URL = "/api/llm/summarise/"
ANALYSE_URL = "/api/llm/analyse/"
MODELS_URL = "/api/llm/models/"


@pytest.mark.django_db
class TestChatView:
    def test_unauthenticated_returns_401(self, api_client):
        response = api_client.post(CHAT_URL, {}, format="json")
        assert response.status_code == 401

    def test_returns_content(self, auth_client):
        with patch("apps.llm_analysis.views.services.chat", return_value="Hello!"):
            response = auth_client.post(
                CHAT_URL,
                {"messages": [{"role": "user", "content": "Hi"}]},
                format="json",
            )
        assert response.status_code == 200
        assert response.data["content"] == "Hello!"

    def test_invalid_payload_returns_400(self, auth_client):
        response = auth_client.post(CHAT_URL, {"messages": []}, format="json")
        assert response.status_code == 400

    def test_ollama_error_returns_503(self, auth_client):
        with patch(
            "apps.llm_analysis.views.services.chat", side_effect=OllamaServiceError("refused")
        ):
            response = auth_client.post(
                CHAT_URL,
                {"messages": [{"role": "user", "content": "Hi"}]},
                format="json",
            )
        assert response.status_code == 503

    def test_model_override_passed_through(self, auth_client):
        with patch("apps.llm_analysis.views.services.chat", return_value="ok") as mock_chat:
            auth_client.post(
                CHAT_URL,
                {"messages": [{"role": "user", "content": "Hi"}], "model": "mistral"},
                format="json",
            )
        mock_chat.assert_called_once_with([{"role": "user", "content": "Hi"}], model="mistral")


@pytest.mark.django_db
class TestSummariseView:
    def test_unauthenticated_returns_401(self, api_client):
        response = api_client.post(SUMMARISE_URL, {}, format="json")
        assert response.status_code == 401

    def test_returns_summary(self, auth_client):
        with patch("apps.llm_analysis.views.services.summarise", return_value="short summary"):
            response = auth_client.post(SUMMARISE_URL, {"text": "Long text here"}, format="json")
        assert response.status_code == 200
        assert response.data["content"] == "short summary"

    def test_missing_text_returns_400(self, auth_client):
        response = auth_client.post(SUMMARISE_URL, {}, format="json")
        assert response.status_code == 400

    def test_ollama_error_returns_503(self, auth_client):
        with patch(
            "apps.llm_analysis.views.services.summarise", side_effect=OllamaServiceError("err")
        ):
            response = auth_client.post(SUMMARISE_URL, {"text": "text"}, format="json")
        assert response.status_code == 503


@pytest.mark.django_db
class TestAnalyseView:
    def test_unauthenticated_returns_401(self, api_client):
        response = api_client.post(ANALYSE_URL, {}, format="json")
        assert response.status_code == 401

    def test_returns_analysis(self, auth_client):
        with patch("apps.llm_analysis.views.services.analyse", return_value="analysis result"):
            response = auth_client.post(ANALYSE_URL, {"text": "some text"}, format="json")
        assert response.status_code == 200
        assert response.data["content"] == "analysis result"

    def test_context_field_accepted(self, auth_client):
        with patch("apps.llm_analysis.views.services.analyse", return_value="ok") as mock_analyse:
            auth_client.post(
                ANALYSE_URL,
                {"text": "data", "context": "background"},
                format="json",
            )
        mock_analyse.assert_called_once_with("data", context="background", model=None)

    def test_ollama_error_returns_503(self, auth_client):
        with patch(
            "apps.llm_analysis.views.services.analyse", side_effect=OllamaServiceError("err")
        ):
            response = auth_client.post(ANALYSE_URL, {"text": "text"}, format="json")
        assert response.status_code == 503


@pytest.mark.django_db
class TestModelsView:
    def test_unauthenticated_returns_401(self, api_client):
        response = api_client.get(MODELS_URL)
        assert response.status_code == 401

    def test_returns_model_list(self, auth_client):
        models = [{"name": "llama3.2:latest", "size_gb": 2.0}]
        with patch("apps.llm_analysis.views.services.list_models", return_value=models):
            response = auth_client.get(MODELS_URL)
        assert response.status_code == 200
        assert response.data == models

    def test_ollama_error_returns_503(self, auth_client):
        with patch(
            "apps.llm_analysis.views.services.list_models", side_effect=OllamaServiceError("err")
        ):
            response = auth_client.get(MODELS_URL)
        assert response.status_code == 503


STOP_URL = "/api/llm/runs/stop/"


@pytest.mark.django_db
class TestStopRunView:
    def test_unauthenticated_returns_401(self, api_client):
        response = api_client.post(STOP_URL, {"type": "chain", "id": "x"}, format="json")
        assert response.status_code == 401

    def test_stops_a_running_chain_run(self, auth_client, user):
        from apps.llm_analysis.models import AgentRun

        run = AgentRun.objects.create(user=user, query="q", model="", kind="chain")
        response = auth_client.post(STOP_URL, {"type": "chain", "id": str(run.pk)}, format="json")
        assert response.status_code == 200
        assert response.data == {"stopped": True}
        run.refresh_from_db()
        assert run.status == "stopped"

    def test_already_finished_run_reports_not_stopped(self, auth_client, user):
        from apps.llm_analysis.models import AgentRun

        run = AgentRun.objects.create(user=user, query="q", model="", status="done", kind="chain")
        response = auth_client.post(STOP_URL, {"type": "chain", "id": str(run.pk)}, format="json")
        assert response.status_code == 200
        assert response.data == {"stopped": False}

    def test_unknown_type_returns_400(self, auth_client):
        response = auth_client.post(STOP_URL, {"type": "bogus", "id": "x"}, format="json")
        assert response.status_code == 400

    def test_missing_id_returns_400(self, auth_client):
        response = auth_client.post(STOP_URL, {"type": "chain"}, format="json")
        assert response.status_code == 400

    def test_malformed_id_returns_400(self, auth_client):
        response = auth_client.post(STOP_URL, {"type": "chain", "id": "not-a-uuid"}, format="json")
        assert response.status_code == 400

    def test_cannot_stop_another_users_run(self, auth_client, django_user_model):
        from apps.llm_analysis.models import AgentRun

        other = django_user_model.objects.create_user(email="other@x.com", password="x")
        run = AgentRun.objects.create(user=other, query="q", model="", kind="chain")
        response = auth_client.post(STOP_URL, {"type": "chain", "id": str(run.pk)}, format="json")
        assert response.status_code == 200
        assert response.data == {"stopped": False}
        run.refresh_from_db()
        assert run.status == "running"
