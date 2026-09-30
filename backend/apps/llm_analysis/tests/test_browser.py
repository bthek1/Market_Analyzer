"""Browser agent tests.

NOTHING here launches a browser: every test patches ``browser.build_agent``, which is the
single seam over browser-use's API. A test that really drives Chromium belongs behind the
``browser_live`` marker (excluded from the default run, like ``llm_live``).
"""

import asyncio
import base64
import json
from unittest.mock import patch

import pytest
from django.core.cache import cache

from apps.llm_analysis import browser
from apps.llm_analysis.models import AgentRun, AgentStep
from apps.llm_analysis.services import create_browser_run

BROWSER_URL = "/api/llm/browser/"
BROWSER_LIST_URL = "/api/llm/browser/history/"

# 1x1 transparent PNG.
PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


def _events(generator):
    return [json.loads(e[len("data: ") :].strip()) for e in generator]


# --- fakes standing in for browser-use ----------------------------------------------------


class FakeAction:
    def __init__(self, name, args):
        self._d = {name: args}

    def model_dump(self, exclude_unset=False):
        return dict(self._d)


class FakeState:
    def __init__(self, url="https://example.com", title="Example", screenshot=None):
        self.url = url
        self.title = title
        self.screenshot = screenshot


class FakeOutput:
    def __init__(self, action="go_to_url", args=None, goal="next", evaluation="ok", memory="m"):
        self.action = [FakeAction(action, args or {"url": "https://example.com"})]
        self.next_goal = goal
        self.evaluation_previous_goal = evaluation
        self.memory = memory


class FakeHistory:
    def __init__(self, result="the answer", urls=None, done=True):
        self._result = result
        self._urls = urls if urls is not None else ["about:blank", "https://example.com"]
        self._done = done

    def final_result(self):
        return self._result

    def urls(self):
        return list(self._urls)

    def is_done(self):
        return self._done


class FakeAgent:
    """Replays scripted steps through the step callback, then returns a history."""

    def __init__(
        self, steps, history=None, error=None, on_step=None, should_stop=None, delay_s=0.0
    ):
        self._steps = steps
        self._history = history
        self._error = error
        self._on_step = on_step
        self._should_stop = should_stop
        self._delay_s = delay_s
        self.closed = False

    async def run(self, max_steps=10):
        if self._delay_s:
            # Emit nothing for long enough that the consumer's queue poll times out - the
            # only way to reach the loop's own deadline check.
            await asyncio.sleep(self._delay_s)
        for i, (state, output) in enumerate(self._steps[:max_steps], start=1):
            if self._should_stop is not None and await self._should_stop():
                raise InterruptedError
            self._on_step(state, output, i)
        if self._error:
            raise RuntimeError(self._error)
        return self._history

    async def close(self):
        self.closed = True


def _agent_factory(steps, history=None, error=None, record=None, delay_s=0.0):
    def _build(task, *, llm, allowed_domains, headless, on_step, should_stop, use_vision=True):
        agent = FakeAgent(steps, history, error, on_step, should_stop, delay_s)
        if record is not None:
            record.append(
                {
                    "task": task,
                    "allowed_domains": allowed_domains,
                    "use_vision": use_vision,
                    "agent": agent,
                }
            )
        return agent

    return _build


def _step(n=1, screenshot=None):
    return (
        FakeState(url=f"https://example.com/{n}", title=f"Page {n}", screenshot=screenshot),
        FakeOutput(goal=f"goal {n}"),
    )


# --- pure helpers -------------------------------------------------------------------------


class TestParseDomains:
    def test_blank_means_unrestricted(self):
        assert browser.parse_domains("") == []

    def test_splits_newlines_and_commas(self):
        raw = "*.google.com\n *.sec.gov , example.com\n\n"
        assert browser.parse_domains(raw) == ["*.google.com", "*.sec.gov", "example.com"]


class TestDefaults:
    def test_provider_defaults_to_ollama(self, settings):
        # Ollama is the out-of-the-box provider: free, local, no API key required.
        assert settings.BROWSER_PROVIDER == "ollama"

    def test_settings_row_seeds_from_the_env_defaults(self, llm_settings):
        assert llm_settings.browser_provider == "ollama"


class TestBuildLLM:
    def test_anthropic_without_key_raises(self, settings):
        settings.ANTHROPIC_API_KEY = ""
        with pytest.raises(browser.BrowserAgentError, match="ANTHROPIC_API_KEY"):
            browser.build_llm("anthropic", "claude-sonnet-5")

    def test_blank_model_falls_back_per_provider(self, settings, llm_settings):
        settings.ANTHROPIC_API_KEY = "sk-test"
        llm_settings.main_model = "qwen3:14b"
        assert browser.build_llm("ollama", "").model == "qwen3:14b"
        assert browser.build_llm("anthropic", "").model == browser.DEFAULT_ANTHROPIC_MODEL

    def test_anthropic_with_key(self, settings):
        settings.ANTHROPIC_API_KEY = "sk-test"
        llm = browser.build_llm("anthropic", "claude-sonnet-5")
        assert llm.model == "claude-sonnet-5"

    def test_ollama_uses_configured_host(self, llm_settings):
        llm_settings.base_url = "http://ollama.local:11434"
        llm = browser.build_llm("ollama", "qwen3:8b")
        assert llm.host == "http://ollama.local:11434"

    def test_unknown_provider_raises(self):
        with pytest.raises(browser.BrowserAgentError, match="provider"):
            browser.build_llm("gpt5", "x")


class _ShowResponse:
    """Minimal stand-in for the httpx response from Ollama's /api/show."""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class TestVisionGate:
    """browser-use attaches a screenshot to every step when ``use_vision`` is on. Against a
    text-only model that is not degraded output, it is a 400 on EVERY step - the agent burns
    its whole budget without seeing a page. Regression cover for exactly that run."""

    @pytest.mark.parametrize(
        ("capabilities", "expected"),
        [
            # What the server actually returns for qwen3:8b - the all-400 run.
            (["completion", "tools", "thinking"], False),
            (["completion", "tools", "vision"], True),
            ([], False),
        ],
    )
    def test_asks_ollama_for_capabilities(self, llm_settings, capabilities, expected):
        with patch.object(browser.httpx, "post") as post:
            post.return_value = _ShowResponse({"capabilities": capabilities})
            assert browser.provider_supports_vision("ollama", "some-model") is expected
        assert post.call_args.kwargs["json"] == {"model": "some-model"}

    @pytest.mark.parametrize(
        ("model", "expected"),
        [
            ("qwen3:8b", False),
            ("llama3.1", False),
            ("llava:13b", True),
            ("qwen2.5vl:7b", True),
            ("qwen3-vl:8b", True),
            ("gemma3:12b", True),
        ],
    )
    def test_falls_back_to_the_name_when_ollama_is_down(self, llm_settings, model, expected):
        """An Ollama outage must degrade to the heuristic, not fail the run."""
        with patch.object(browser.httpx, "post", side_effect=browser.httpx.ConnectError("down")):
            assert browser.provider_supports_vision("ollama", model) is expected

    def test_blank_name_is_not_probed(self, llm_settings):
        """No model name means nothing to ask about - and no reason to hit the network."""
        with patch.object(browser.httpx, "post", side_effect=AssertionError("must not call")):
            assert browser.model_has_vision("") is False

    def test_anthropic_never_probes_ollama(self, llm_settings):
        with patch.object(browser.httpx, "post", side_effect=AssertionError("must not call")):
            assert browser.provider_supports_vision("anthropic", "") is True
            assert browser.provider_supports_vision("unknown", "x") is False

    def test_blank_ollama_model_falls_back_to_configured_main(self, llm_settings):
        llm_settings.main_model = "qwen3:8b"
        with patch.object(browser.httpx, "post") as post:
            post.return_value = _ShowResponse({"capabilities": ["completion"]})
            assert browser.provider_supports_vision("ollama", "") is False
        assert post.call_args.kwargs["json"] == {"model": "qwen3:8b"}

    def test_agent_receives_the_flag(self, llm_settings):
        agent = browser.build_agent(
            "q",
            llm=browser.build_llm("ollama", "qwen3:8b"),
            allowed_domains=[],
            headless=True,
            on_step=lambda *a: None,
            should_stop=None,
            use_vision=False,
        )
        assert agent.settings.use_vision is False


class TestOllamaContextWindow:
    """Ollama defaults num_ctx to 4096. A browser-use step prompt (system prompt + DOM +
    a 1920x1080 screenshot) measures ~15k tokens, so at the default the model has no room
    to generate and returns an EMPTY string - surfacing as browser-use's
    "Invalid JSON: EOF while parsing a value at line 1 column 0". browser-use never sets
    num_ctx itself, so this is ours to get right."""

    def test_num_ctx_is_passed_to_ollama(self, llm_settings, settings):
        settings.BROWSER_NUM_CTX = 32768
        llm = browser.build_llm("ollama", "qwen3-vl:8b")
        assert llm.ollama_options == {"num_ctx": 32768}

    def test_num_ctx_is_configurable(self, llm_settings, settings):
        settings.BROWSER_NUM_CTX = 8192
        assert browser.build_llm("ollama", "qwen3-vl:8b").ollama_options == {"num_ctx": 8192}

    def test_default_is_far_above_the_ollama_default(self):
        """Regression guard: anything at or near 4096 reintroduces the empty-output bug."""
        from django.conf import settings as django_settings

        assert django_settings.BROWSER_NUM_CTX >= 16384


class TestBuildAgent:
    """Constructing a browser-use Agent does not launch anything - the browser starts on
    ``run()``. Worth covering: a typo here would otherwise only fail in production."""

    def test_wires_profile_and_task(self, llm_settings):
        agent = browser.build_agent(
            "find NVDA revenue",
            llm=browser.build_llm("ollama", "qwen3:8b"),
            allowed_domains=["*.sec.gov"],
            headless=True,
            on_step=lambda *a: None,
            should_stop=None,
        )
        profile = agent.browser_session.browser_profile
        assert profile.allowed_domains == ["*.sec.gov"]
        assert profile.headless is True
        # A throwaway profile: the agent can never act as a logged-in user. Passing None
        # makes browser-use mint a fresh temp dir (Chrome needs one to attach over CDP);
        # what matters is that it is never the operator's real Chrome profile.
        assert "browser-use-user-data-dir" in str(profile.user_data_dir)

    def test_blank_allow_list_means_unrestricted(self, llm_settings):
        agent = browser.build_agent(
            "q",
            llm=browser.build_llm("ollama", "qwen3:8b"),
            allowed_domains=[],
            headless=True,
            on_step=lambda *a: None,
            should_stop=None,
        )
        assert agent.browser_session.browser_profile.allowed_domains is None

    def test_telemetry_is_disabled(self):
        import os

        assert os.environ["ANONYMIZED_TELEMETRY"] == "false"
        assert os.environ["BROWSER_USE_CLOUD_SYNC"] == "false"


class TestResolveBrowserBinary:
    """The lookup preflight depends on. Every other test stubs it out, so without this it
    is the one link in the chain never actually exercised - and it is the link that broke
    (a Playwright download present, but nothing able to point at it)."""

    def _disable_system_chrome(self, monkeypatch):
        """Force the Playwright-glob branch: otherwise a dev box with real Chrome installed
        short-circuits on find_chrome_executable and the glob path stays untested."""
        import browser_use.browser.chrome as chrome_mod

        monkeypatch.setattr(chrome_mod, "find_chrome_executable", lambda: None)

    def test_finds_the_playwright_download(self, monkeypatch, tmp_path):
        self._disable_system_chrome(monkeypatch)
        binary = tmp_path / "chromium-1234" / "chrome-linux64" / "chrome"
        binary.parent.mkdir(parents=True)
        binary.touch()
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
        assert browser.resolve_browser_binary() == str(binary)

    def test_prefers_the_highest_versioned_build(self, monkeypatch, tmp_path):
        self._disable_system_chrome(monkeypatch)
        for build in ("chromium-1000", "chromium-1234"):
            p = tmp_path / build / "chrome-linux64" / "chrome"
            p.parent.mkdir(parents=True)
            p.touch()
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
        assert browser.resolve_browser_binary().endswith("chromium-1234/chrome-linux64/chrome")

    def test_finds_the_headless_shell_build(self, monkeypatch, tmp_path):
        self._disable_system_chrome(monkeypatch)
        p = tmp_path / "chromium_headless_shell-1234" / "chrome-linux64" / "chrome-headless-shell"
        p.parent.mkdir(parents=True)
        p.touch()
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
        assert browser.resolve_browser_binary() == str(p)

    def test_none_when_nothing_is_installed(self, monkeypatch, tmp_path):
        self._disable_system_chrome(monkeypatch)
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
        assert browser.resolve_browser_binary() is None

    def test_system_chrome_wins_over_the_download(self, monkeypatch, tmp_path):
        import browser_use.browser.chrome as chrome_mod

        monkeypatch.setattr(chrome_mod, "find_chrome_executable", lambda: "/usr/bin/chrome")
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
        assert browser.resolve_browser_binary() == "/usr/bin/chrome"

    def test_a_broken_browser_use_lookup_falls_through(self, monkeypatch, tmp_path):
        """browser-use's helper is private API; if it moves or raises we degrade to globs."""
        import browser_use.browser.chrome as chrome_mod

        def _boom():
            raise RuntimeError("moved in a browser-use release")

        monkeypatch.setattr(chrome_mod, "find_chrome_executable", _boom)
        binary = tmp_path / "chromium-1234" / "chrome-linux64" / "chrome"
        binary.parent.mkdir(parents=True)
        binary.touch()
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
        assert browser.resolve_browser_binary() == str(binary)


class TestPreflight:
    """Without this, a Chromium that cannot start surfaces only as browser-use's
    "on_BrowserStartEvent timed out after 30.0s" - 30 seconds of nothing useful."""

    def test_no_binary_names_the_install_command(self, monkeypatch):
        monkeypatch.setattr(browser, "resolve_browser_binary", lambda: None)
        with pytest.raises(browser.BrowserAgentError, match="playwright install chromium"):
            browser.preflight()

    def test_missing_libraries_are_listed_with_the_fix(self, monkeypatch):
        monkeypatch.setattr(browser, "resolve_browser_binary", lambda: "/opt/chrome")
        monkeypatch.setattr(
            browser, "missing_shared_libraries", lambda _b: ["libnss3.so", "libgbm.so.1"]
        )
        with pytest.raises(browser.BrowserAgentError) as exc:
            browser.preflight()
        assert "libnss3.so" in str(exc.value)
        assert browser.INSTALL_DEPS_CMD in str(exc.value)

    def test_healthy_binary_passes(self, monkeypatch):
        monkeypatch.setattr(browser, "resolve_browser_binary", lambda: "/opt/chrome")
        monkeypatch.setattr(browser, "missing_shared_libraries", lambda _b: [])
        browser.preflight()

    def test_missing_libraries_parses_ldd_output(self, monkeypatch):
        import subprocess

        out = "\tlibnspr4.so => not found\n\tlibc.so.6 => /lib/libc.so.6 (0x00007f)\n"
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=out, stderr=""),
        )
        assert browser.missing_shared_libraries("/opt/chrome") == ["libnspr4.so"]

    def test_missing_libraries_is_silent_without_ldd(self, monkeypatch):
        import subprocess

        def _boom(*a, **k):
            raise OSError("no ldd here")

        monkeypatch.setattr(subprocess, "run", _boom)
        # No ldd (macOS, minimal image) must never block a working install.
        assert browser.missing_shared_libraries("/opt/chrome") == []

    def test_launch_timeout_gets_an_actionable_hint(self):
        raw = (
            "Event handler browser_use.browser.watchdog_base.BrowserSession."
            "on_BrowserStartEvent#9920 timed out after 30.0s"
        )
        hinted = browser._launch_hint(raw)
        assert browser.INSTALL_DEPS_CMD in hinted
        assert raw in hinted

    def test_unrelated_errors_pass_through_untouched(self):
        assert browser._launch_hint("model refused") == "model refused"


class TestStepPayload:
    def test_flattens_state_and_output(self):
        payload = browser.step_payload(_step(3)[0], _step(3)[1], 3)
        assert payload["order"] == 2
        assert payload["action"] == "go_to_url"
        assert payload["action_args"] == {"url": "https://example.com"}
        assert payload["url"] == "https://example.com/3"
        assert payload["title"] == "Page 3"
        assert payload["goal"] == "goal 3"

    def test_first_step_is_order_zero(self):
        assert browser.step_payload(FakeState(), FakeOutput(), 1)["order"] == 0

    def test_tolerates_missing_action(self):
        output = FakeOutput()
        output.action = []
        payload = browser.step_payload(FakeState(), output, 1)
        assert payload["action"] == ""
        assert payload["action_args"] == {}

    def test_scalar_action_args_are_wrapped(self):
        output = FakeOutput()
        output.action = [FakeAction("scroll", 400)]
        assert browser.step_payload(FakeState(), output, 1)["action_args"] == {"value": 400}

    def test_skips_null_and_undumpable_actions(self):
        output = FakeOutput()
        output.action = [object(), FakeAction("noop", None), FakeAction("click", {"index": 2})]
        payload = browser.step_payload(FakeState(), output, 1)
        assert payload["action"] == "click"


class TestSources:
    def test_dedupes_preserving_order(self):
        history = FakeHistory(urls=["https://a.com", "https://b.com", "https://a.com"])
        assert browser._sources(history) == ["https://a.com", "https://b.com"]

    def test_unreadable_history_yields_no_sources(self):
        class Broken:
            def urls(self):
                raise RuntimeError("gone")

        assert browser._sources(Broken()) == []


class TestSaveScreenshot:
    def test_writes_png_and_returns_key(self, settings, tmp_path):
        settings.BROWSER_SCREENSHOT_ROOT = str(tmp_path)
        key = browser.save_screenshot("run-1", 2, PNG_B64)
        assert key == "run-1/2.png"
        assert (tmp_path / "run-1" / "2.png").read_bytes() == base64.b64decode(PNG_B64)

    def test_missing_screenshot_is_not_an_error(self, settings, tmp_path):
        settings.BROWSER_SCREENSHOT_ROOT = str(tmp_path)
        assert browser.save_screenshot("run-1", 0, None) == ""

    def test_bad_payload_degrades_to_empty(self, settings, tmp_path):
        settings.BROWSER_SCREENSHOT_ROOT = str(tmp_path)
        assert browser.save_screenshot("run-1", 0, "!!!not base64!!!") == ""


# --- the loop -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestRunBrowser:
    @pytest.fixture(autouse=True)
    def _skip_preflight(self, monkeypatch):
        """The loop tests use a fake agent, so the real Chromium check is irrelevant here
        (and would fail on any machine without a browser installed)."""
        monkeypatch.setattr(browser, "preflight", lambda: None)

    def _run(self, user, query="who won?", max_steps=5):
        return create_browser_run(
            user=user,
            query=query,
            model="",
            provider="anthropic",
            max_steps=max_steps,
            allowed_domains=["*.example.com"],
        )

    def test_streams_and_persists_steps(self, user, llm_settings, settings, tmp_path):
        settings.ANTHROPIC_API_KEY = "sk-test"
        settings.BROWSER_SCREENSHOT_ROOT = str(tmp_path)
        run = self._run(user)
        steps = [_step(1, PNG_B64), _step(2)]
        with patch.object(browser, "build_agent", _agent_factory(steps, FakeHistory())):
            events = _events(browser.run_browser(run))

        assert events[0]["event"] == "started"
        assert events[0]["allowed_domains"] == ["*.example.com"]
        step_events = [e for e in events if e["event"] == "step"]
        assert [e["order"] for e in step_events] == [0, 1]
        assert step_events[0]["screenshot"] == f"{run.id}/0.png"
        assert step_events[1]["screenshot"] == ""

        assert events[-1]["event"] == "result"
        assert events[-1]["output"] == "the answer"
        # about:blank is not a source.
        assert events[-1]["sources"] == ["https://example.com"]
        assert events[-1]["stop_reason"] == "complete"

        run.refresh_from_db()
        assert run.status == AgentRun.Status.DONE
        assert run.output == "the answer"
        assert run.meta["stop_reason"] == "complete"
        assert run.meta["urls_visited"] == ["https://example.com"]
        rows = list(run.steps.order_by("order"))
        assert len(rows) == 2
        assert rows[0].meta["url"] == "https://example.com/1"
        assert rows[0].meta["title"] == "Page 1"
        assert rows[0].status == AgentStep.Status.DONE

    def test_task_and_domains_reach_the_agent(self, user, llm_settings, settings, tmp_path):
        settings.ANTHROPIC_API_KEY = "sk-test"
        settings.BROWSER_SCREENSHOT_ROOT = str(tmp_path)
        run = self._run(user, query="find NVDA revenue")
        record = []
        with patch.object(
            browser, "build_agent", _agent_factory([_step(1)], FakeHistory(), record=record)
        ):
            _events(browser.run_browser(run))

        assert record[0]["task"] == "find NVDA revenue"
        assert record[0]["allowed_domains"] == ["*.example.com"]
        assert record[0]["agent"].closed is True
        # Anthropic is multimodal, so the screenshots are worth sending.
        assert record[0]["use_vision"] is True

    def test_text_only_ollama_model_runs_without_vision(
        self, user, llm_settings, settings, tmp_path
    ):
        """The all-400 run: qwen3 cannot take an image, so browser-use must not send one."""
        settings.BROWSER_SCREENSHOT_ROOT = str(tmp_path)
        llm_settings.main_model = "qwen3:8b"
        run = create_browser_run(
            user=user,
            query="best stocks to buy",
            model="qwen3:8b",
            provider="ollama",
            max_steps=5,
            allowed_domains=["*.example.com"],
        )
        record = []
        with (
            patch.object(
                browser, "build_agent", _agent_factory([_step(1)], FakeHistory(), record=record)
            ),
            # Patched so the suite never depends on a reachable Ollama: unpatched this
            # makes a real /api/show call and waits out the timeout when the host is down.
            patch.object(
                browser.httpx, "post", return_value=_ShowResponse({"capabilities": ["completion"]})
            ),
        ):
            # model=run.model is how BrowserView calls it - the per-run override, not the
            # configured default.
            _events(browser.run_browser(run, model=run.model))

        assert record[0]["use_vision"] is False

    def test_default_config_model_is_used_when_the_run_has_no_override(
        self, user, llm_settings, settings, tmp_path
    ):
        """A run with no explicit model gets the configured browser_model, which now
        defaults to a vision tag rather than the text-only main model."""
        settings.BROWSER_SCREENSHOT_ROOT = str(tmp_path)
        llm_settings.browser_model = "qwen3-vl:8b"
        run = create_browser_run(
            user=user,
            query="q",
            model="",
            provider="ollama",
            max_steps=5,
            allowed_domains=["*.example.com"],
        )
        record = []
        with (
            patch.object(
                browser, "build_agent", _agent_factory([_step(1)], FakeHistory(), record=record)
            ),
            patch.object(
                browser.httpx,
                "post",
                return_value=_ShowResponse({"capabilities": ["completion", "vision"]}),
            ) as post,
        ):
            _events(browser.run_browser(run, model=run.model))

        assert post.call_args.kwargs["json"] == {"model": "qwen3-vl:8b"}
        assert record[0]["use_vision"] is True

    def test_agent_error_finishes_run_with_error(self, user, llm_settings, settings, tmp_path):
        settings.ANTHROPIC_API_KEY = "sk-test"
        settings.BROWSER_SCREENSHOT_ROOT = str(tmp_path)
        run = self._run(user)
        with patch.object(browser, "build_agent", _agent_factory([_step(1)], error="chrome died")):
            events = _events(browser.run_browser(run))

        assert events[-1]["event"] == "error"
        assert "chrome died" in events[-1]["error"]
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR
        assert run.meta["stop_reason"] == "error"
        # The step that did complete is still persisted.
        assert run.steps.count() == 1

    def test_no_answer_is_a_budget_stop(self, user, llm_settings, settings, tmp_path):
        settings.ANTHROPIC_API_KEY = "sk-test"
        settings.BROWSER_SCREENSHOT_ROOT = str(tmp_path)
        run = self._run(user, max_steps=2)
        history = FakeHistory(result="", done=False)
        with patch.object(browser, "build_agent", _agent_factory([_step(1)], history)):
            events = _events(browser.run_browser(run))

        assert events[-1]["event"] == "error"
        assert "without producing an answer" in events[-1]["error"]
        run.refresh_from_db()
        assert run.meta["stop_reason"] == "budget"
        assert run.status == AgentRun.Status.ERROR

    def test_deadline_stops_the_agent(self, user, llm_settings, settings, tmp_path):
        settings.ANTHROPIC_API_KEY = "sk-test"
        settings.BROWSER_SCREENSHOT_ROOT = str(tmp_path)
        llm_settings.browser_timeout_s = 0  # already expired when the loop starts
        run = self._run(user)
        with patch.object(browser, "build_agent", _agent_factory([_step(1)], FakeHistory())):
            events = _events(browser.run_browser(run))

        # should_stop fires on the agent's first step, so it never reports one.
        assert [e["event"] for e in events if e["event"] == "step"] == []
        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.meta["stop_reason"] == "timeout"

    def test_a_silent_agent_still_hits_the_wall_clock(self, user, llm_settings, settings, tmp_path):
        """The deadline must fire even when the agent emits NOTHING - otherwise a browser
        wedged before its first step would hold the single slot until the process died.
        The other deadline test is short-circuited by should_stop on step 1; this one
        exercises the consumer loop's own timeout check."""
        settings.ANTHROPIC_API_KEY = "sk-test"
        settings.BROWSER_SCREENSHOT_ROOT = str(tmp_path)
        llm_settings.browser_timeout_s = 0  # already expired when the loop starts
        run = self._run(user)
        # Longer than the 0.5s queue poll, so the consumer sees an empty queue first.
        factory = _agent_factory([], FakeHistory(result=None), delay_s=browser._POLL_S + 0.2)
        with patch.object(browser, "build_agent", factory):
            events = _events(browser.run_browser(run))

        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.meta["stop_reason"] == "timeout"

    def test_unreadable_result_degrades_to_no_answer(self, user, llm_settings, settings, tmp_path):
        settings.ANTHROPIC_API_KEY = "sk-test"
        settings.BROWSER_SCREENSHOT_ROOT = str(tmp_path)
        run = self._run(user)

        class Broken(FakeHistory):
            def final_result(self):
                raise RuntimeError("bad history")

        with patch.object(browser, "build_agent", _agent_factory([_step(1)], Broken())):
            events = _events(browser.run_browser(run))
        assert events[-1]["event"] == "error"

    def test_close_failure_does_not_break_the_run(self, user, llm_settings, settings, tmp_path):
        settings.ANTHROPIC_API_KEY = "sk-test"
        settings.BROWSER_SCREENSHOT_ROOT = str(tmp_path)
        run = self._run(user)

        def _build(task, **kwargs):
            agent = FakeAgent(
                [_step(1)],
                FakeHistory(),
                on_step=kwargs["on_step"],
                should_stop=kwargs["should_stop"],
            )

            async def _boom():
                raise RuntimeError("close failed")

            agent.close = _boom
            return agent

        with patch.object(browser, "build_agent", _build):
            events = _events(browser.run_browser(run))
        assert events[-1]["event"] == "result"

    def test_failed_preflight_ends_the_run_before_launching(
        self, user, llm_settings, settings, monkeypatch
    ):
        settings.ANTHROPIC_API_KEY = "sk-test"

        def _fail():
            raise browser.BrowserAgentError("missing system libraries (libnss3.so)")

        monkeypatch.setattr(browser, "preflight", _fail)
        run = self._run(user)
        with patch.object(browser, "build_agent", side_effect=AssertionError("must not launch")):
            events = _events(browser.run_browser(run))

        assert events[0]["event"] == "error"
        assert "libnss3.so" in events[0]["error"]
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR
        assert run.meta["stop_reason"] == "error"

    def test_launch_failure_reaches_the_client_with_a_hint(
        self, user, llm_settings, settings, tmp_path
    ):
        settings.ANTHROPIC_API_KEY = "sk-test"
        settings.BROWSER_SCREENSHOT_ROOT = str(tmp_path)
        run = self._run(user)
        raw = "Event handler ... on_BrowserStartEvent#9920 timed out after 30.0s"
        with patch.object(browser, "build_agent", _agent_factory([], error=raw)):
            events = _events(browser.run_browser(run))

        assert events[-1]["event"] == "error"
        assert browser.INSTALL_DEPS_CMD in events[-1]["error"]

    def test_missing_api_key_fails_before_launching(self, user, llm_settings, settings):
        settings.ANTHROPIC_API_KEY = ""
        run = self._run(user)
        with patch.object(browser, "build_agent", side_effect=AssertionError("must not launch")):
            events = _events(browser.run_browser(run))

        assert events[0]["event"] == "error"
        assert "ANTHROPIC_API_KEY" in events[0]["error"]
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR


# --- API ----------------------------------------------------------------------------------


@pytest.fixture
def other_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(email="browser-other@x.com", password="pass")


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
class TestBrowserAPI:
    def test_requires_auth(self, api_client):
        assert api_client.post(BROWSER_URL, {"query": "x"}, format="json").status_code == 401

    def test_disabled_returns_503(self, auth_client, llm_settings):
        llm_settings.browser_enabled = False
        response = auth_client.post(BROWSER_URL, {"query": "x"}, format="json")
        assert response.status_code == 503
        assert "hint" in response.data

    def test_missing_query(self, auth_client, llm_settings):
        llm_settings.browser_enabled = True
        assert auth_client.post(BROWSER_URL, {}, format="json").status_code == 400

    def test_max_steps_out_of_range(self, auth_client, llm_settings):
        llm_settings.browser_enabled = True
        response = auth_client.post(BROWSER_URL, {"query": "x", "max_steps": 99}, format="json")
        assert response.status_code == 400

    def test_busy_slot_returns_429(self, auth_client, llm_settings):
        llm_settings.browser_enabled = True
        assert browser.acquire_slot() is True
        try:
            response = auth_client.post(BROWSER_URL, {"query": "x"}, format="json")
            assert response.status_code == 429
        finally:
            browser.release_slot()
        # The slot is free again for the next caller.
        assert browser.acquire_slot() is True
        browser.release_slot()

    @pytest.mark.django_db(transaction=True)
    def test_streams_sse(self, auth_client, llm_settings, settings, tmp_path, monkeypatch):
        llm_settings.browser_enabled = True
        settings.ANTHROPIC_API_KEY = "sk-test"
        settings.BROWSER_SCREENSHOT_ROOT = str(tmp_path)
        # The agent is faked, so the real Chromium check does not apply.
        monkeypatch.setattr(browser, "preflight", lambda: None)
        with patch.object(
            browser, "build_agent", _agent_factory([_step(1, PNG_B64)], FakeHistory())
        ):
            response = auth_client.post(BROWSER_URL, {"query": "test"}, format="json")
            assert response.status_code == 200
            assert "text/event-stream" in response.get("Content-Type", "")
            content = b"".join(response.streaming_content).decode()

        events = [
            json.loads(line[len("data: ") :])
            for line in content.splitlines()
            if line.startswith("data:")
        ]
        kinds = [e["event"] for e in events]
        assert kinds[0] == "started"
        assert "step" in kinds
        assert kinds[-1] == "result"
        assert events[-1]["output"] == "the answer"
        # The slot must be free once the stream ends.
        assert browser.acquire_slot() is True
        browser.release_slot()

    def test_history_is_owner_scoped(self, auth_client, user, other_user):
        create_browser_run(
            user=user, query="mine", model="", provider="anthropic", max_steps=5, allowed_domains=[]
        )
        create_browser_run(
            user=other_user,
            query="theirs",
            model="",
            provider="anthropic",
            max_steps=5,
            allowed_domains=[],
        )
        response = auth_client.get(BROWSER_LIST_URL)
        assert response.status_code == 200
        assert [r["query"] for r in response.data["results"]] == ["mine"]

    def test_detail_serializes_meta(self, auth_client, user, settings, tmp_path):
        settings.BROWSER_SCREENSHOT_ROOT = str(tmp_path)
        run = create_browser_run(
            user=user,
            query="q",
            model="",
            provider="anthropic",
            max_steps=5,
            allowed_domains=["*.sec.gov"],
        )
        from apps.llm_analysis import store

        store.create_step(run, 0, action="go_to_url", url="https://sec.gov", title="SEC")
        response = auth_client.get(f"/api/llm/browser/{run.id}/")
        assert response.status_code == 200
        assert response.data["provider"] == "anthropic"
        assert response.data["allowed_domains"] == ["*.sec.gov"]
        assert response.data["steps"][0]["url"] == "https://sec.gov"

    def test_detail_404_for_other_user(self, auth_client, other_user):
        run = create_browser_run(
            user=other_user,
            query="q",
            model="",
            provider="anthropic",
            max_steps=5,
            allowed_domains=[],
        )
        assert auth_client.get(f"/api/llm/browser/{run.id}/").status_code == 404

    def test_stop_flips_status(self, auth_client, user):
        run = create_browser_run(
            user=user, query="q", model="", provider="anthropic", max_steps=5, allowed_domains=[]
        )
        response = auth_client.post(
            "/api/llm/runs/stop/", {"type": "browser", "id": str(run.id)}, format="json"
        )
        assert response.status_code == 200
        assert response.data["stopped"] is True
        run.refresh_from_db()
        assert run.status == "stopped"


@pytest.mark.django_db
class TestScreenshotView:
    def _run_with_shot(self, user, tmp_path):
        run = create_browser_run(
            user=user, query="q", model="", provider="anthropic", max_steps=5, allowed_domains=[]
        )
        browser.save_screenshot(run.id, 0, PNG_B64)
        return run

    def test_serves_owner_screenshot(self, auth_client, user, settings, tmp_path):
        settings.BROWSER_SCREENSHOT_ROOT = str(tmp_path)
        run = self._run_with_shot(user, tmp_path)
        response = auth_client.get(f"/api/llm/browser/{run.id}/screenshot/0/")
        assert response.status_code == 200
        assert response["Content-Type"] == "image/png"

    def test_404_for_other_users_run(self, auth_client, other_user, settings, tmp_path):
        settings.BROWSER_SCREENSHOT_ROOT = str(tmp_path)
        run = self._run_with_shot(other_user, tmp_path)
        assert auth_client.get(f"/api/llm/browser/{run.id}/screenshot/0/").status_code == 404

    def test_404_for_missing_file(self, auth_client, user, settings, tmp_path):
        settings.BROWSER_SCREENSHOT_ROOT = str(tmp_path)
        run = create_browser_run(
            user=user, query="q", model="", provider="anthropic", max_steps=5, allowed_domains=[]
        )
        assert auth_client.get(f"/api/llm/browser/{run.id}/screenshot/7/").status_code == 404


@pytest.mark.django_db
class TestScreenshotSweep:
    def test_removes_old_run_dirs_and_keeps_fresh(self, user, settings, tmp_path):
        from datetime import UTC, timedelta
        from datetime import datetime as dt

        from apps.llm_analysis.tasks import sweep_browser_screenshots

        settings.BROWSER_SCREENSHOT_ROOT = str(tmp_path)
        settings.BROWSER_SCREENSHOT_RETENTION_DAYS = 7

        fresh = create_browser_run(
            user=user, query="new", model="", provider="anthropic", max_steps=5, allowed_domains=[]
        )
        stale = create_browser_run(
            user=user, query="old", model="", provider="anthropic", max_steps=5, allowed_domains=[]
        )
        AgentRun.objects.filter(pk=stale.pk).update(created_at=dt.now(UTC) - timedelta(days=30))
        browser.save_screenshot(fresh.id, 0, PNG_B64)
        browser.save_screenshot(stale.id, 0, PNG_B64)
        # A directory whose run no longer exists is swept too.
        orphan = tmp_path / "00000000-0000-0000-0000-000000000000"
        orphan.mkdir()
        (tmp_path / "stray.txt").write_text("not a run dir")

        assert sweep_browser_screenshots() == {"removed": 2, "kept": 1}
        assert (tmp_path / str(fresh.id)).is_dir()
        assert not (tmp_path / str(stale.id)).exists()
        assert not orphan.exists()
        assert (tmp_path / "stray.txt").exists()

    def test_no_screenshot_root_is_a_noop(self, settings, tmp_path):
        from apps.llm_analysis.tasks import sweep_browser_screenshots

        settings.BROWSER_SCREENSHOT_ROOT = str(tmp_path / "never-used")
        assert sweep_browser_screenshots() == {"removed": 0, "kept": 0}
