from unittest.mock import patch

import pytest
from django.db.utils import OperationalError

from apps.llm_analysis.config import get_llm_config
from apps.llm_analysis.models import (
    AgentRun,
    LLMSettings,
)

SETTINGS_URL = "/api/llm/settings/"
REACT_URL = "/api/llm/react/"
EVALUATE_URL = "/api/llm/evaluate/"
PLAN_URL = "/api/llm/plan/"
ORCH_URL = "/api/llm/orchestrate/"
MULTIAGENT_URL = "/api/llm/multiagent/"


@pytest.mark.django_db
class TestLLMSettingsModel:
    def test_get_solo_creates_single_row(self):
        first = LLMSettings.get_solo()
        second = LLMSettings.get_solo()
        assert first.pk == second.pk
        assert LLMSettings.objects.count() == 1

    def test_defaults_match_settings_env_defaults(self, settings):
        cfg = LLMSettings.get_solo()
        assert cfg.main_model == settings.OLLAMA_MAIN_MODEL
        assert cfg.classifier_model == settings.OLLAMA_CLASSIFIER_MODEL
        assert cfg.embed_model == settings.OLLAMA_EMBED_MODEL
        assert cfg.timeout == settings.OLLAMA_TIMEOUT
        assert cfg.num_parallel == settings.OLLAMA_NUM_PARALLEL
        assert cfg.route_mode == settings.OLLAMA_ROUTE_MODE
        assert cfg.route_threshold == settings.OLLAMA_ROUTE_THRESHOLD

    def test_summary_freshness_defaults_match_settings(self, settings):
        cfg = LLMSettings.get_solo()
        assert cfg.summary_snapshot_max_age_days == settings.SUMMARY_SNAPSHOT_MAX_AGE_DAYS
        assert cfg.summary_price_max_age_days == settings.SUMMARY_PRICE_MAX_AGE_DAYS
        assert cfg.summary_financials_max_age_days == settings.SUMMARY_FINANCIALS_MAX_AGE_DAYS


@pytest.mark.django_db
class TestGetLLMConfig:
    def test_returns_singleton(self):
        assert get_llm_config().pk == LLMSettings.get_solo().pk

    def test_falls_back_to_defaults_without_db(self, settings):
        with patch.object(LLMSettings, "get_solo", side_effect=OperationalError("no table")):
            cfg = get_llm_config()
        assert cfg.pk is None  # unsaved fallback instance
        assert cfg.main_model == settings.OLLAMA_MAIN_MODEL


@pytest.mark.django_db
class TestLLMSettingsEndpoint:
    def test_get_requires_auth(self, api_client):
        assert api_client.get(SETTINGS_URL).status_code == 401

    def test_get_returns_current_config(self, auth_client):
        resp = auth_client.get(SETTINGS_URL)
        assert resp.status_code == 200
        assert resp.data["main_model"] == "qwen3:8b"
        assert resp.data["route_mode"] == "llm"
        assert "updated_at" in resp.data

    def test_put_updates_config(self, auth_client):
        payload = {
            "base_url": "http://ollama:11434",
            "main_model": "qwen3:14b",
            "classifier_model": "qwen3:1.7b",
            "embed_model": "nomic-embed-text",
            "timeout": 90,
            "num_parallel": 6,
            "route_mode": "semantic",
            "route_threshold": 0.8,
            "react_max_steps": 8,
            "eval_max_iterations": 4,
            "eval_threshold": 7,
            "plan_max_steps": 12,
            "plan_max_replans": 3,
            "orch_max_workers": 5,
            "multiagent_max_tools": 5,
            "dag_max_nodes": 5,
            "auto_max_cycles": 10,
            "auto_max_subagents": 2,
            "auto_subagent_steps": 4,
            "auto_no_progress": 3,
            "browser_enabled": True,
            "browser_provider": "anthropic",
            "browser_model": "claude-sonnet-5",
            "browser_max_steps": 12,
            "browser_timeout_s": 240,
            "browser_headless": True,
            "browser_allowed_domains": "*.sec.gov",
        }
        resp = auth_client.put(SETTINGS_URL, payload, format="json")
        assert resp.status_code == 200
        cfg = LLMSettings.get_solo()
        assert cfg.main_model == "qwen3:14b"
        assert cfg.route_mode == "semantic"
        assert cfg.route_threshold == 0.8
        assert cfg.orch_max_workers == 5
        assert cfg.browser_enabled is True
        assert cfg.browser_max_steps == 12
        assert LLMSettings.objects.count() == 1

    def test_patch_orch_max_workers_round_trip(self, auth_client):
        resp = auth_client.patch(SETTINGS_URL, {"orch_max_workers": 6}, format="json")
        assert resp.status_code == 200
        assert resp.data["orch_max_workers"] == 6
        assert LLMSettings.get_solo().orch_max_workers == 6

    def test_patch_multiagent_max_tools_round_trip(self, auth_client):
        resp = auth_client.patch(SETTINGS_URL, {"multiagent_max_tools": 6}, format="json")
        assert resp.status_code == 200
        assert resp.data["multiagent_max_tools"] == 6
        assert LLMSettings.get_solo().multiagent_max_tools == 6

    def test_get_returns_summary_freshness_windows(self, auth_client):
        resp = auth_client.get(SETTINGS_URL)
        assert resp.data["summary_snapshot_max_age_days"] == 7
        assert resp.data["summary_price_max_age_days"] == 3
        assert resp.data["summary_financials_max_age_days"] == 120

    def test_patch_summary_freshness_window_round_trip(self, auth_client):
        resp = auth_client.patch(SETTINGS_URL, {"summary_snapshot_max_age_days": 14}, format="json")
        assert resp.status_code == 200
        assert resp.data["summary_snapshot_max_age_days"] == 14
        assert LLMSettings.get_solo().summary_snapshot_max_age_days == 14

    def test_patch_rejects_out_of_range_freshness_window(self, auth_client):
        resp = auth_client.patch(SETTINGS_URL, {"summary_price_max_age_days": 0}, format="json")
        assert resp.status_code == 400
        assert "summary_price_max_age_days" in resp.data

    def test_put_without_the_new_windows_still_validates(self, auth_client):
        """A full PUT written before these fields existed must not 400."""
        current = auth_client.get(SETTINGS_URL).data
        payload = {
            k: v for k, v in current.items() if k != "updated_at" and not k.startswith("summary_")
        }
        resp = auth_client.put(SETTINGS_URL, payload, format="json")
        assert resp.status_code == 200
        assert LLMSettings.get_solo().summary_snapshot_max_age_days == 7

    def test_patch_auto_max_cycles_round_trip(self, auth_client):
        resp = auth_client.patch(SETTINGS_URL, {"auto_max_cycles": 12}, format="json")
        assert resp.status_code == 200
        assert resp.data["auto_max_cycles"] == 12
        assert LLMSettings.get_solo().auto_max_cycles == 12

    def test_patch_dag_max_nodes_round_trip(self, auth_client):
        resp = auth_client.patch(SETTINGS_URL, {"dag_max_nodes": 8}, format="json")
        assert resp.status_code == 200
        assert resp.data["dag_max_nodes"] == 8
        assert LLMSettings.get_solo().dag_max_nodes == 8

    def test_patch_updates_single_field(self, auth_client):
        resp = auth_client.patch(SETTINGS_URL, {"main_model": "llama3:8b"}, format="json")
        assert resp.status_code == 200
        assert LLMSettings.get_solo().main_model == "llama3:8b"

    def test_invalid_route_mode_rejected(self, auth_client):
        resp = auth_client.patch(SETTINGS_URL, {"route_mode": "magic"}, format="json")
        assert resp.status_code == 400

    def test_out_of_range_threshold_rejected(self, auth_client):
        resp = auth_client.patch(SETTINGS_URL, {"route_threshold": 1.5}, format="json")
        assert resp.status_code == 400

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("timeout", 0),
            ("timeout", 601),
            ("num_parallel", 0),
            ("num_parallel", 33),
            ("react_max_steps", 0),
            ("react_max_steps", 21),
            ("eval_max_iterations", 11),
            ("eval_threshold", 0),
            ("plan_max_steps", 21),
            ("plan_max_replans", -1),
            ("orch_max_workers", 1),
            ("orch_max_workers", 9),
            ("multiagent_max_tools", 0),
            ("multiagent_max_tools", 11),
            ("dag_max_nodes", 1),
            ("dag_max_nodes", 13),
            ("route_threshold", -0.1),
        ],
    )
    def test_out_of_range_numeric_fields_rejected(self, auth_client, field, value):
        resp = auth_client.patch(SETTINGS_URL, {field: value}, format="json")
        assert resp.status_code == 400, f"{field}={value} should be rejected"

    def test_put_with_missing_field_rejected(self, auth_client):
        # PUT is a full update: an incomplete body must 400 (partial updates use PATCH).
        resp = auth_client.put(SETTINGS_URL, {"main_model": "qwen3:14b"}, format="json")
        assert resp.status_code == 400

    def test_updated_at_is_read_only(self, auth_client):
        resp = auth_client.patch(
            SETTINGS_URL, {"updated_at": "2000-01-01T00:00:00Z"}, format="json"
        )
        assert resp.status_code == 200
        # The supplied value is ignored; auto_now stamps the real save time.
        assert not resp.data["updated_at"].startswith("2000")


@pytest.mark.django_db
class TestAgentViewsDefaultFromSingleton:
    """The agent endpoints resolve omitted caps/thresholds from the singleton."""

    def _drain(self, response):
        b"".join(response.streaming_content)

    def test_react_omitted_max_steps_uses_singleton(self, auth_client, llm_settings):
        llm_settings.react_max_steps = 9
        with patch("apps.llm_analysis.react.run_react", return_value=iter([])):
            resp = auth_client.post(REACT_URL, {"query": "x"}, format="json")
        assert resp.status_code == 200
        self._drain(resp)
        run = AgentRun.objects.filter(kind="react").latest("created_at")
        assert run.meta["max_steps"] == 9

    def test_react_explicit_max_steps_overrides_singleton(self, auth_client, llm_settings):
        llm_settings.react_max_steps = 9
        with patch("apps.llm_analysis.react.run_react", return_value=iter([])):
            resp = auth_client.post(REACT_URL, {"query": "x", "max_steps": 3}, format="json")
        assert resp.status_code == 200
        self._drain(resp)
        run = AgentRun.objects.filter(kind="react").latest("created_at")
        assert run.meta["max_steps"] == 3

    def test_evaluate_omitted_params_use_singleton(self, auth_client, llm_settings):
        llm_settings.eval_max_iterations = 5
        llm_settings.eval_threshold = 6
        with patch("apps.llm_analysis.eval_opt.run_eval_opt", return_value=iter([])):
            resp = auth_client.post(EVALUATE_URL, {"query": "x"}, format="json")
        assert resp.status_code == 200
        self._drain(resp)
        run = AgentRun.objects.filter(kind="eval_opt").latest("created_at")
        assert run.meta["max_iterations"] == 5
        assert run.meta["threshold"] == 6

    def test_plan_omitted_max_steps_uses_singleton(self, auth_client, llm_settings):
        llm_settings.plan_max_steps = 15
        with patch("apps.llm_analysis.plan_execute.run_plan", return_value=iter([])):
            resp = auth_client.post(PLAN_URL, {"query": "x"}, format="json")
        assert resp.status_code == 200
        self._drain(resp)
        run = AgentRun.objects.filter(kind="plan_exec").latest("created_at")
        assert run.meta["max_steps"] == 15

    def test_orchestrate_omitted_max_workers_uses_singleton(self, auth_client, llm_settings):
        llm_settings.orch_max_workers = 7
        with patch("apps.llm_analysis.orchestrator.run_orchestrator", return_value=iter([])):
            resp = auth_client.post(ORCH_URL, {"query": "x"}, format="json")
        assert resp.status_code == 200
        self._drain(resp)
        run = AgentRun.objects.filter(kind="orchestrator").latest("created_at")
        assert run.meta["max_workers"] == 7

    def test_multiagent_omitted_max_tools_uses_singleton(self, auth_client, llm_settings):
        llm_settings.multiagent_max_tools = 6
        with patch("apps.llm_analysis.multiagent.run_multiagent", return_value=iter([])):
            resp = auth_client.post(MULTIAGENT_URL, {"query": "x"}, format="json")
        assert resp.status_code == 200
        self._drain(resp)
        run = AgentRun.objects.filter(kind="multiagent").latest("created_at")
        assert run.meta["max_tools"] == 6

    def test_multiagent_explicit_max_tools_overrides_singleton(self, auth_client, llm_settings):
        llm_settings.multiagent_max_tools = 6
        with patch("apps.llm_analysis.multiagent.run_multiagent", return_value=iter([])):
            resp = auth_client.post(MULTIAGENT_URL, {"query": "x", "max_tools": 2}, format="json")
        assert resp.status_code == 200
        self._drain(resp)
        run = AgentRun.objects.filter(kind="multiagent").latest("created_at")
        assert run.meta["max_tools"] == 2

    def test_orchestrate_explicit_max_workers_overrides_singleton(self, auth_client, llm_settings):
        llm_settings.orch_max_workers = 7
        with patch("apps.llm_analysis.orchestrator.run_orchestrator", return_value=iter([])):
            resp = auth_client.post(ORCH_URL, {"query": "x", "max_workers": 3}, format="json")
        assert resp.status_code == 200
        self._drain(resp)
        run = AgentRun.objects.filter(kind="orchestrator").latest("created_at")
        assert run.meta["max_workers"] == 3


class TestLLMSettingsIsTheOnlySourceOfTruth:
    """`OLLAMA_*` env vars only SEED the singleton's field defaults on first creation.
    Once the row exists it wins, and a reader that goes to `settings` instead silently
    diverges from what the app is actually configured to do.

    This cost real time in production on 2026-09-25: `OLLAMA_NUM_CTX` was reverted from
    16384 to 4096 in code, migration 0038 had already baked 16384 into the row, and the
    deployed app kept using 16384 because the row is the source of truth. A second case
    was live at the same time - the health probe read `settings.OLLAMA_BASE_URL`, so
    changing the host in LLM Settings would have left it probing the old one.
    """

    # models.py defines the seeding defaults, so it reads settings by design. Everything
    # under settings/ IS the settings. Tests may assert against either.
    ALLOWED = ("apps/llm_analysis/models.py", "core/settings/", "/tests/", "/conftest.py")

    def test_no_module_reads_settings_ollama_directly(self):
        """AST, not grep. A regex that strips string literals to avoid matching prose also
        blanks f-STRINGS - and `f"{settings.OLLAMA_BASE_URL}/api/tags"` is exactly how the
        live offender was written, so the regex version of this guard passed while the bug
        was in the tree. The AST sees the interpolated attribute access and not the prose.
        """
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parents[3]
        offenders = []
        for path in sorted(root.rglob("*.py")):
            rel = str(path.relative_to(root)).replace("\\", "/")
            if any(a.strip("/") in rel for a in self.ALLOWED):
                continue
            if ".venv" in rel or "/migrations/" in rel or "/node_modules/" in rel:
                continue
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "settings"
                    and node.attr.startswith("OLLAMA_")
                ):
                    offenders.append(f"{rel}:{node.lineno} ({node.attr})")

        assert not offenders, (
            "read LLM config through apps.llm_analysis.config.get_llm_config(), not "
            f"settings.OLLAMA_* - the row is the source of truth: {offenders}"
        )
