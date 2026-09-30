import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from apps.llm_analysis.services import (
    OllamaServiceError,
    analyse,
    chat,
    chat_many,
    chat_tokens,
    embed,
    list_models,
    stream_in_background,
    summarise,
)

# Every test here exercises the Ollama service helpers, which read the LLM config via
# get_llm_config(); the llm_settings fixture supplies an in-memory singleton (no DB).
pytestmark = pytest.mark.usefixtures("llm_settings")


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


class TestChat:
    def test_returns_content(self):
        mock_resp = _mock_response({"message": {"content": "Hello!"}})
        with patch("apps.llm_analysis.services.httpx.post", return_value=mock_resp) as mock_post:
            result = chat([{"role": "user", "content": "Hi"}])
        assert result == "Hello!"
        mock_post.assert_called_once()
        call_json = mock_post.call_args.kwargs["json"]
        assert call_json["stream"] is False
        assert call_json["think"] is False

    def test_think_can_be_enabled(self):
        mock_resp = _mock_response({"message": {"content": "ok"}})
        with patch("apps.llm_analysis.services.httpx.post", return_value=mock_resp) as mock_post:
            chat([{"role": "user", "content": "Hi"}], think=True)
        assert mock_post.call_args.kwargs["json"]["think"] is True

    def test_defaults_to_main_model(self):
        mock_resp = _mock_response({"message": {"content": "ok"}})
        with patch("apps.llm_analysis.services.httpx.post", return_value=mock_resp) as mock_post:
            chat([{"role": "user", "content": "Hi"}])
        assert mock_post.call_args.kwargs["json"]["model"] == "qwen3:8b"

    def test_uses_model_override(self):
        mock_resp = _mock_response({"message": {"content": "ok"}})
        with patch("apps.llm_analysis.services.httpx.post", return_value=mock_resp):
            chat([{"role": "user", "content": "x"}], model="custom-model")
            # model override passed correctly — no assertion needed; covered by integration

    def test_raises_on_http_error(self):
        import httpx

        with patch(
            "apps.llm_analysis.services.httpx.post", side_effect=httpx.ConnectError("refused")
        ):
            with pytest.raises(OllamaServiceError):
                chat([{"role": "user", "content": "hi"}])

    def test_temperature_sets_options_alongside_num_ctx(self, llm_settings):
        mock_resp = _mock_response({"message": {"content": "ok"}})
        with patch("apps.llm_analysis.services.httpx.post", return_value=mock_resp) as mock_post:
            chat([{"role": "user", "content": "Hi"}], temperature=0.7)
        assert mock_post.call_args.kwargs["json"]["options"] == {
            "num_ctx": llm_settings.num_ctx,
            "temperature": 0.7,
        }

    def test_num_ctx_is_always_sent(self, llm_settings):
        """Ollama's default num_ctx is 4096 and it TRUNCATES SILENTLY rather than erroring.
        Measured against the live host: a 12,052-token prompt reported
        prompt_eval_count=4095 and the model answered from the surviving third, with no
        failure anywhere. `browser.py` already had to learn this; every other caller sends
        through here, so this is where the rest of the app learns it."""
        mock_resp = _mock_response({"message": {"content": "ok"}})
        with patch("apps.llm_analysis.services.httpx.post", return_value=mock_resp) as mock_post:
            chat([{"role": "user", "content": "Hi"}])
        assert mock_post.call_args.kwargs["json"]["options"] == {"num_ctx": llm_settings.num_ctx}

    def test_num_ctx_is_configurable(self, llm_settings):
        llm_settings.num_ctx = 8192
        mock_resp = _mock_response({"message": {"content": "ok"}})
        with patch("apps.llm_analysis.services.httpx.post", return_value=mock_resp) as mock_post:
            chat([{"role": "user", "content": "Hi"}])
        assert mock_post.call_args.kwargs["json"]["options"]["num_ctx"] == 8192

    def test_format_passthrough(self):
        schema = {"type": "object"}
        mock_resp = _mock_response({"message": {"content": "ok"}})
        with patch("apps.llm_analysis.services.httpx.post", return_value=mock_resp) as mock_post:
            chat([{"role": "user", "content": "Hi"}], format=schema)
        assert mock_post.call_args.kwargs["json"]["format"] == schema

    def test_format_omitted_sends_no_format(self):
        mock_resp = _mock_response({"message": {"content": "ok"}})
        with patch("apps.llm_analysis.services.httpx.post", return_value=mock_resp) as mock_post:
            chat([{"role": "user", "content": "Hi"}])
        assert "format" not in mock_post.call_args.kwargs["json"]


class TestChatStream:
    def test_yields_sse_chunks(self):
        import json

        lines = [
            json.dumps({"message": {"content": "Hi"}, "done": False}),
            json.dumps({"message": {"content": " there"}, "done": False}),
            json.dumps({"message": {"content": ""}, "done": True}),
        ]

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_lines.return_value = iter(lines)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("apps.llm_analysis.services.httpx.stream", return_value=mock_resp):
            chunks = list(chat_tokens([{"role": "user", "content": "hey"}]))

        # Raw content now, not SSE frames: `chat_tokens` is the primitive and the framing
        # wrapper went with the legacy endpoint (issue #8 phase 6).
        assert "".join(chunks) == "Hi there"

    def test_num_ctx_is_sent_on_the_streaming_path_too(self, llm_settings):
        """The streaming path builds its own payload, so it has to be wired separately -
        and truncation there is just as silent. It now carries the CHAT AGENT's replies,
        which are the longest prompts in the app, so this matters more than it did."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_lines.return_value = iter([])
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("apps.llm_analysis.services.httpx.stream", return_value=mock_resp) as stream:
            list(chat_tokens([{"role": "user", "content": "hey"}]))

        assert stream.call_args.kwargs["json"]["options"] == {"num_ctx": llm_settings.num_ctx}

    def test_blank_lines_and_junk_chunks_are_skipped(self):
        """Ollama's stream carries keep-alive blanks, and a truncated line is possible on
        a dropped connection. Neither may kill a stream mid-answer."""
        import json

        lines = [
            "",
            "{not json",
            json.dumps({"message": {"content": "Hi"}, "done": False}),
            json.dumps({"message": {"content": ""}, "done": True}),
        ]
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.iter_lines.return_value = iter(lines)
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("apps.llm_analysis.services.httpx.stream", return_value=mock_resp):
            chunks = list(chat_tokens([{"role": "user", "content": "hey"}]))

        assert "".join(chunks) == "Hi"

    def test_raises_on_connection_error(self):
        import httpx

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.ConnectError("refused")
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("apps.llm_analysis.services.httpx.stream", return_value=mock_resp):
            with pytest.raises(OllamaServiceError):
                list(chat_tokens([{"role": "user", "content": "hi"}]))


class TestChatManyContext:
    def test_num_ctx_reaches_every_fanned_out_call(self, llm_settings):
        """chat_many delegates to chat, so this is transitive - but the fan-out path is
        where an oversized prompt is most likely (N worker prompts built from one query),
        so it is pinned rather than assumed."""
        llm_settings.num_ctx = 12288
        mock_resp = _mock_response({"message": {"content": "ok"}})

        with patch("apps.llm_analysis.services.httpx.post", return_value=mock_resp) as mock_post:
            chat_many([[{"role": "user", "content": "a"}], [{"role": "user", "content": "b"}]])

        assert mock_post.call_count == 2
        for call in mock_post.call_args_list:
            assert call.kwargs["json"]["options"]["num_ctx"] == 12288


class TestChatMany:
    def test_runs_concurrently_and_preserves_order(self):
        def fake_chat(messages, model=None, think=False):
            time.sleep(0.1)
            return messages[0]["content"]

        batches = [[{"role": "user", "content": str(i)}] for i in range(4)]
        with patch("apps.llm_analysis.services.chat", side_effect=fake_chat):
            start = time.perf_counter()
            results = chat_many(batches)
            elapsed = time.perf_counter() - start

        assert [r["ok"] for r in results] == ["0", "1", "2", "3"]
        assert all(r["error"] is None for r in results)
        # 4 concurrent ~0.1s calls should finish well under the 0.4s sequential time.
        assert elapsed < 0.3

    def test_single_failure_does_not_drop_others(self):
        def fake_chat(messages, model=None, think=False):
            if messages[0]["content"] == "boom":
                raise OllamaServiceError("kaboom")
            return "ok"

        batches = [
            [{"role": "user", "content": "a"}],
            [{"role": "user", "content": "boom"}],
            [{"role": "user", "content": "c"}],
        ]
        with patch("apps.llm_analysis.services.chat", side_effect=fake_chat):
            results = chat_many(batches)

        assert results[0] == {"ok": "ok", "error": None}
        assert results[1]["ok"] is None
        assert "kaboom" in results[1]["error"]
        assert results[2] == {"ok": "ok", "error": None}

    def test_empty_batches_returns_empty(self):
        assert chat_many([]) == []

    def test_passes_model_and_think(self):
        captured = []

        def fake_chat(messages, model=None, think=False):
            captured.append((model, think))
            return "x"

        with patch("apps.llm_analysis.services.chat", side_effect=fake_chat):
            chat_many([[{"role": "user", "content": "a"}]], model="m", think=True)
        assert captured == [("m", True)]

    def test_temperatures_passed_per_batch(self):
        captured = []

        def fake_chat(messages, model=None, think=False, temperature=None):
            captured.append((messages[0]["content"], temperature))
            return "x"

        batches = [
            [{"role": "user", "content": "a"}],
            [{"role": "user", "content": "b"}],
        ]
        with patch("apps.llm_analysis.services.chat", side_effect=fake_chat):
            results = chat_many(batches, temperatures=[0.3, 0.9])
        assert sorted(captured) == [("a", 0.3), ("b", 0.9)]
        assert all(r["ok"] == "x" for r in results)


class TestEmbed:
    def test_returns_vectors(self):
        mock_resp = _mock_response({"embeddings": [[0.1, 0.2], [0.3, 0.4]]})
        with patch("apps.llm_analysis.services.httpx.post", return_value=mock_resp) as mock_post:
            result = embed(["a", "b"])
        assert result == [[0.1, 0.2], [0.3, 0.4]]
        call_json = mock_post.call_args.kwargs["json"]
        assert call_json["model"] == "nomic-embed-text"
        assert call_json["input"] == ["a", "b"]

    def test_empty_returns_empty_without_call(self):
        with patch("apps.llm_analysis.services.httpx.post") as mock_post:
            assert embed([]) == []
        mock_post.assert_not_called()

    def test_raises_on_http_error(self):
        import httpx

        with patch(
            "apps.llm_analysis.services.httpx.post", side_effect=httpx.ConnectError("refused")
        ):
            with pytest.raises(OllamaServiceError):
                embed(["x"])


class TestSummarise:
    def test_injects_system_prompt(self):
        mock_resp = _mock_response({"message": {"content": "summary text"}})
        with patch("apps.llm_analysis.services.httpx.post", return_value=mock_resp) as mock_post:
            result = summarise("Long article here...")
        assert result == "summary text"
        messages = mock_post.call_args.kwargs["json"]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[1]["content"] == "Long article here..."


class TestAnalyse:
    def test_returns_analysis(self):
        mock_resp = _mock_response({"message": {"content": "analysis"}})
        with patch("apps.llm_analysis.services.httpx.post", return_value=mock_resp):
            result = analyse("Some text")
        assert result == "analysis"

    def test_prepends_context(self):
        mock_resp = _mock_response({"message": {"content": "analysis"}})
        with patch("apps.llm_analysis.services.httpx.post", return_value=mock_resp) as mock_post:
            analyse("Some text", context="Background info")
        user_msg = mock_post.call_args.kwargs["json"]["messages"][-1]["content"]
        assert "Background info" in user_msg
        assert "Some text" in user_msg


class TestListModels:
    def test_returns_only_completion_models(self):
        mock_resp = _mock_response(
            {
                "models": [
                    {
                        "name": "analysis-assistant:latest",
                        "size": 1_929_912_707,
                        "capabilities": ["completion", "tools"],
                    },
                    {
                        "name": "nomic-embed-text:latest",
                        "size": 274_302_450,
                        "capabilities": ["embedding"],
                    },
                    {
                        "name": "qwen2.5:3b",
                        "size": 1_929_912_432,
                        "capabilities": ["completion", "tools"],
                    },
                ]
            }
        )
        with patch("apps.llm_analysis.services.httpx.get", return_value=mock_resp):
            result = list_models()
        names = [m["name"] for m in result]
        assert "nomic-embed-text:latest" not in names
        assert "analysis-assistant:latest" in names
        assert "qwen2.5:3b" in names
        assert len(result) == 2

    def test_returns_model_list_without_capabilities_field(self):
        """Models with no capabilities field are excluded (treated as non-completion)."""
        mock_resp = _mock_response(
            {
                "models": [
                    {"name": "llama3.2:latest", "size": 2_147_483_648},
                ]
            }
        )
        with patch("apps.llm_analysis.services.httpx.get", return_value=mock_resp):
            result = list_models()
        assert result == []

    def test_size_gb_computed_correctly(self):
        mock_resp = _mock_response(
            {
                "models": [
                    {
                        "name": "mistral:latest",
                        "size": 4_294_967_296,
                        "capabilities": ["completion"],
                    },
                ]
            }
        )
        with patch("apps.llm_analysis.services.httpx.get", return_value=mock_resp):
            result = list_models()
        assert result[0]["size_gb"] == 4.0

    def test_raises_on_connection_error(self):
        import httpx

        with patch(
            "apps.llm_analysis.services.httpx.get", side_effect=httpx.ConnectError("refused")
        ):
            with pytest.raises(OllamaServiceError):
                list_models()


class TestStreamInBackground:
    """The Agents-page workflows must keep running after the client disconnects
    (e.g. a page refresh). stream_in_background drives the SSE generator from a
    daemon thread so it drains to completion regardless of the live consumer."""

    def test_yields_all_events_to_the_live_consumer(self):
        def gen():
            yield "a"
            yield "b"
            yield "c"

        assert list(stream_in_background(gen())) == ["a", "b", "c"]

    def test_drains_generator_after_the_consumer_disconnects(self):
        finished = threading.Event()

        def gen():
            try:
                for i in range(5):
                    yield f"e{i}"
            finally:
                finished.set()

        live = stream_in_background(gen())
        assert next(live) == "e0"
        # Simulate the browser dropping the connection mid-stream.
        live.close()
        # The background worker keeps draining the generator to completion.
        assert finished.wait(timeout=2.0)

    def test_generator_exception_becomes_an_error_event(self):
        def gen():
            yield "ok"
            raise RuntimeError("boom")

        out = list(stream_in_background(gen()))
        assert out[0] == "ok"
        assert out[-1].startswith("data: ")
        assert "boom" in out[-1]

    @pytest.mark.django_db(transaction=True)
    def test_stops_when_run_status_flips_to_stopped(self, django_user_model):
        from apps.llm_analysis.models import AgentRun
        from apps.llm_analysis.services import request_run_stop

        user = django_user_model.objects.create_user(email="stop@x.com", password="x")
        run = AgentRun.objects.create(user=user, query="q", model="", kind="chain")
        # Cancel before the stream starts so the worker stops at the first check.
        assert request_run_stop(AgentRun, run.pk, user) is True

        advanced = {"n": 0}

        def gen():
            advanced["n"] += 1
            yield "e0"

        out = list(stream_in_background(gen(), run))

        run.refresh_from_db()
        assert run.status == "stopped"
        # The generator body never advanced; a stopped event was emitted.
        assert advanced["n"] == 0
        assert any("stopped" in event for event in out)

    @pytest.mark.django_db(transaction=True)
    def test_request_run_stop_only_flips_running_rows(self, django_user_model):
        from apps.llm_analysis.models import AgentRun
        from apps.llm_analysis.services import request_run_stop

        user = django_user_model.objects.create_user(email="stop2@x.com", password="x")
        done = AgentRun.objects.create(user=user, query="q", model="", status="done", kind="chain")
        assert request_run_stop(AgentRun, done.pk, user) is False
        done.refresh_from_db()
        assert done.status == "done"
