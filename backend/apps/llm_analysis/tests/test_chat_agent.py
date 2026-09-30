"""The chat agent as a driven harness workflow (issue #8 phase 1).

The structural guards (test_events, test_registry, test_step_payload,
core/tests/test_tracing_spans) already assert that `chat` is wired into the harness at all.
What is tested HERE is the policy the structural tests cannot see: that a conversational turn
can answer without touching a tool, that it reaches the tools when it needs them, and that a
turn never ends blank.
"""

import json
from unittest.mock import patch

import pytest

from apps.llm_analysis.chat_agent import parse_chat_output, run_chat
from apps.llm_analysis.models import AgentRun, AgentStep
from apps.llm_analysis.services import OllamaServiceError, create_chat_run

CHAT_URL = "/api/llm/chat-agent/"
CHAT_LIST_URL = "/api/llm/chat-agent/history/"


@pytest.fixture(autouse=True)
def _no_eager_title(request):
    """Stop the title task running INSIDE the turn's request.

    `CELERY_TASK_ALWAYS_EAGER` is on in tests, so `generate_chat_title.delay(...)` executes
    inline - and it calls `services.chat`, which these tests patch with a finite
    `side_effect`. Left alone it eats the response queued for the turn itself, and the turn
    dies with "generator raised StopIteration" three frames away from the cause.

    Not a production concern (prod has a worker, so `delay` returns immediately and the
    title is computed concurrently on the classifier model), but it makes every test that
    posts a turn depend on a task it is not testing. Tests that ARE about the title opt out
    with `@pytest.mark.title_task`.
    """
    if request.node.get_closest_marker("title_task"):
        yield
        return
    with patch("apps.llm_analysis.tasks.generate_chat_title.delay"):
        yield


@pytest.fixture
def other_user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(email="chat-other@x.com", password="pass")


def _events(generator):
    return [json.loads(e[len("data: ") :].strip()) for e in generator]


def _action(tool, **args):
    return json.dumps({"thought": f"calling {tool}", "tool": tool, "args": args})


def _answer(text="hello there"):
    """An ANSWER is now plain prose, not a JSON envelope (issue #8 phase 5). That is what
    makes it streamable token by token, and it also stops the agent replying to "hello"
    with a JSON object."""
    return text


def _chunks(text, size=8):
    """Split a reply so the prose/JSON classifier and the delta path see a real stream
    rather than one blob - the classification happens on the FIRST chunk."""
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


def _patch_tokens(*replies):
    """Patch the model's token stream: one reply per turn, in order.

    An `Exception` in the list is raised instead of streamed, for the failure paths.
    """
    queue = list(replies)

    def side_effect(*_args, **_kwargs):
        if not queue:
            raise AssertionError("the strategy asked for more turns than the test supplied")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return iter(_chunks(item))

    return patch("apps.llm_analysis.services.chat_tokens", side_effect=side_effect)


def _deltas(events):
    return "".join(e["text"] for e in events if e.get("event") == "delta")


# ---------------------------------------------------------------------------
# parse_chat_output (pure)
# ---------------------------------------------------------------------------


class TestParse:
    def test_answer_turn(self):
        assert parse_chat_output('{"thought": "t", "answer": "hi"}')["answer"] == "hi"

    def test_strips_code_fences(self):
        assert parse_chat_output('```json\n{"answer": "hi"}\n```')["answer"] == "hi"

    def test_raises_on_garbage(self):
        with pytest.raises(ValueError):
            parse_chat_output("not json at all")


class TestGroundingPrompt:
    """Issue #9 phase 3: the rule covers CLAIMS, not only numbers."""

    def test_rule_names_rankings_and_comparisons(self):
        from apps.llm_analysis.chat_agent import _system_prompt

        prompt = _system_prompt()
        assert "NEVER state a number, ranking or comparison you were not given." in prompt

    def test_shared_catalogue_rule_reaches_chat(self):
        from apps.llm_analysis.chat_agent import _system_prompt
        from apps.llm_analysis.tools import GROUNDING_RULE

        assert GROUNDING_RULE in _system_prompt()


# ---------------------------------------------------------------------------
# The turn loop
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestChatTurn:
    def _run(self, user, query="hello", max_steps=4):
        return create_chat_run(user=user, query=query, model="", max_steps=max_steps)

    def test_answers_without_calling_a_tool(self, user):
        """The behaviour that separates chat from ReAct. Most turns are conversational, and
        an agent that fetched a company snapshot to say hello would be useless as a chat."""
        run = self._run(user)
        with (
            _patch_tokens(_answer("hi")),
            patch("apps.llm_analysis.tools.run_tool") as run_tool,
        ):
            events = _events(run_chat(run, model=""))

        run_tool.assert_not_called()
        steps = [e for e in events if e["event"] == "step"]
        assert len(steps) == 1
        assert steps[0]["is_answer"] is True
        assert events[-1]["event"] == "result"

        run.refresh_from_db()
        assert run.status == AgentRun.Status.DONE
        assert run.output == "hi"

    def test_tool_then_answer(self, user):
        run = self._run(user)
        with (
            _patch_tokens(_action("company_snapshot", symbol="AAPL"), _answer("31x")),
            patch("apps.llm_analysis.tools.run_tool", return_value='{"trailing_pe": 31}'),
        ):
            events = _events(run_chat(run, model=""))

        steps = [e for e in events if e["event"] == "step"]
        assert len(steps) == 2
        assert steps[0]["tool"] == "company_snapshot"
        assert steps[0]["tool_args"] == {"symbol": "AAPL"}
        assert steps[0]["is_answer"] is False
        assert steps[1]["is_answer"] is True

        run.refresh_from_db()
        assert run.output == "31x"
        # Recorded on the run so a UI can show what the turn touched without walking steps.
        assert run.meta["tools_used"] == ["company_snapshot"]

    def test_started_event_advertises_the_tools(self, user):
        """The old chat path told the model nothing about the tools, which is exactly why it
        could not use them. The UI reads this to render the tool affordance."""
        run = self._run(user)
        with _patch_tokens(_answer()):
            events = _events(run_chat(run, model=""))

        assert events[0]["event"] == "started"
        assert "company_snapshot" in events[0]["tools"]
        assert events[0]["max_steps"] == 4

    def test_tools_used_dedupes_and_keeps_order(self, user):
        run = self._run(user)
        calls = [
            _action("company_profile", symbol="AAPL"),
            _action("company_snapshot", symbol="AAPL"),
            _action("company_profile", symbol="AAPL"),
            _answer("done"),
        ]
        with (
            _patch_tokens(*calls),
            patch("apps.llm_analysis.tools.run_tool", return_value="{}"),
        ):
            list(run_chat(run, model=""))

        run.refresh_from_db()
        assert run.meta["tools_used"] == ["company_profile", "company_snapshot"]

    def test_unparseable_turn_is_recorded_nudged_and_retried(self, user):
        """Persisted AND streamed. A step written without an event is issue #7: the live
        transcript ends up one card shorter than the reloaded one."""
        run = self._run(user)
        with _patch_tokens('{"tool": broken', _answer("ok")):
            events = _events(run_chat(run, model=""))

        steps = [e for e in events if e["event"] == "step"]
        assert len(steps) == 2
        assert steps[0]["status"] == AgentStep.Status.ERROR
        assert steps[1]["is_answer"] is True
        # The stream and the DB agree on how many steps there were.
        assert run.steps.count() == len(steps)

        run.refresh_from_db()
        assert run.status == AgentRun.Status.DONE

    def test_a_tool_error_is_an_observation_not_a_failure(self, user):
        """`run_tool` never raises - a bad symbol is data the model reasons about next turn."""
        run = self._run(user)
        with (
            _patch_tokens(_action("company_profile", symbol="NOPE"), _answer("no such one")),
            patch("apps.llm_analysis.tools.run_tool", return_value='{"error": "unknown symbol"}'),
        ):
            events = _events(run_chat(run, model=""))

        steps = [e for e in events if e["event"] == "step"]
        assert steps[0]["status"] == AgentStep.Status.DONE
        assert "unknown symbol" in steps[0]["observation"]

        run.refresh_from_db()
        assert run.status == AgentRun.Status.DONE

    def test_budget_exhaustion_forces_an_answer(self, user):
        """A turn must never end blank: the user is waiting on a reply, not a status."""
        run = self._run(user, max_steps=2)
        calls = [
            _action("company_profile", symbol="AAPL"),
            _action("company_snapshot", symbol="AAPL"),
            _answer("forced reply"),
        ]
        with (
            _patch_tokens(*calls),
            patch("apps.llm_analysis.tools.run_tool", return_value="{}"),
        ):
            events = _events(run_chat(run, model=""))

        steps = [e for e in events if e["event"] == "step"]
        # 2 tool steps + the forced-answer step, so the transcript shows why the turn ended.
        assert len(steps) == 3
        assert steps[-1]["is_answer"] is True

        run.refresh_from_db()
        assert run.output == "forced reply"
        assert run.status == AgentRun.Status.DONE

    def test_budget_exhausted_and_the_forced_call_fails(self, user):
        run = self._run(user, max_steps=1)
        with (
            _patch_tokens(_action("company_profile", symbol="AAPL"), OllamaServiceError("down")),
            patch("apps.llm_analysis.tools.run_tool", return_value="{}"),
        ):
            events = _events(run_chat(run, model=""))

        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR

    def test_ollama_failure_ends_the_run_as_an_error(self, user):
        run = self._run(user)
        with _patch_tokens(OllamaServiceError("down")):
            events = _events(run_chat(run, model=""))

        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR
        # The partial tool record survives the failure for the timeline.
        assert run.meta["tools_used"] == []


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestChatAgentView:
    """`transaction=True`: stream_in_background drives the generator on a daemon thread with
    its own DB connection, so the committed row must be visible across threads."""

    def test_streams_sse_and_persists_a_terminal_run(self, auth_client, llm_settings):
        with _patch_tokens(_answer("hi")):
            response = auth_client.post(CHAT_URL, {"message": "hello"}, format="json")
            body = b"".join(response.streaming_content).decode()

        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/event-stream")
        assert '"event": "result"' in body

        run = AgentRun.objects.get(kind="chat")
        assert run.status == AgentRun.Status.DONE
        assert run.query == "hello"
        assert run.output == "hi"

    def test_max_steps_falls_back_to_the_settings_singleton(self, auth_client, llm_settings):
        llm_settings.chat_max_steps = 3
        with _patch_tokens(_answer()):
            response = auth_client.post(CHAT_URL, {"message": "hi"}, format="json")
            b"".join(response.streaming_content)

        assert AgentRun.objects.get(kind="chat").meta["max_steps"] == 3

    def test_requires_authentication(self, api_client):
        assert api_client.post(CHAT_URL, {"message": "hi"}, format="json").status_code == 401

    def test_rejects_a_blank_message(self, auth_client):
        assert auth_client.post(CHAT_URL, {"message": ""}, format="json").status_code == 400


@pytest.mark.django_db
class TestChatHistory:
    def test_history_lists_only_chat_runs_for_this_user(self, auth_client, user, other_user):
        create_chat_run(user=user, query="mine", model="", max_steps=4)
        create_chat_run(user=other_user, query="theirs", model="", max_steps=4)

        response = auth_client.get(CHAT_LIST_URL)

        assert response.status_code == 200
        assert [r["query"] for r in response.data["results"]] == ["mine"]

    def test_detail_exposes_the_turn_and_its_steps(self, auth_client, user):
        run = create_chat_run(user=user, query="q", model="", max_steps=4)
        run.steps.create(order=0, meta={"tool": "company_profile", "is_answer": False})

        response = auth_client.get(f"/api/llm/chat-agent/{run.id}/")

        assert response.status_code == 200
        assert response.data["turn"] == 0
        assert response.data["tools_used"] == []
        assert response.data["steps"][0]["tool"] == "company_profile"


# ---------------------------------------------------------------------------
# Sessions (phase 2)
# ---------------------------------------------------------------------------

SESSIONS_URL = "/api/llm/chat/sessions/"


def _session(user, **kw):
    from apps.llm_analysis.models import ChatSession

    return ChatSession.objects.create(user=user, **kw)


def _turn(user, session, query, output="", status=AgentRun.Status.DONE):
    run = create_chat_run(user=user, query=query, model="", max_steps=4, session=session)
    run.status = status
    run.output = output
    run.save(update_fields=["status", "output"])
    return run


@pytest.mark.django_db
class TestRehydration:
    """The prompt a turn actually sees. These are the tests that would catch a conversation
    silently losing its history - which looks like a dumb model, not a bug."""

    def _prompt_for(self, run):
        return self._strategy_for(run).pad.messages

    def _strategy_for(self, run):
        from apps.llm_analysis.chat_agent import ChatStrategy

        return ChatStrategy(run, model="")

    def test_a_turn_sees_the_previous_reply(self, user):
        session = _session(user)
        _turn(user, session, "what is AAPL's PE?", output="31x")
        current = _turn(user, session, "and its PB?", status=AgentRun.Status.RUNNING)

        contents = [m["content"] for m in self._prompt_for(current)]

        assert "what is AAPL's PE?" in contents
        assert "31x" in contents
        assert contents[-1] == "and its PB?"

    def test_turns_are_replayed_oldest_first(self, user):
        session = _session(user)
        _turn(user, session, "first", output="1st reply")
        _turn(user, session, "second", output="2nd reply")
        current = _turn(user, session, "third", status=AgentRun.Status.RUNNING)

        contents = [m["content"] for m in self._prompt_for(current)]
        assert contents.index("first") < contents.index("second") < contents.index("third")

    def test_a_stopped_turn_contributes_its_partial_output(self, user):
        """What the user saw on screen is what the model should believe it said."""
        session = _session(user)
        _turn(user, session, "explain", output="I was halfway thro", status="stopped")
        current = _turn(user, session, "go on", status=AgentRun.Status.RUNNING)

        contents = [m["content"] for m in self._prompt_for(current)]
        assert "I was halfway thro" in contents

    def test_a_turn_that_never_answered_still_contributes_its_question(self, user):
        """Dropping it would make the model answer a question that appears unasked."""
        session = _session(user)
        _turn(user, session, "what happened?", output="", status=AgentRun.Status.ERROR)
        current = _turn(user, session, "hello?", status=AgentRun.Status.RUNNING)

        contents = [m["content"] for m in self._prompt_for(current)]
        assert "what happened?" in contents
        assert "" not in contents[1:]  # no empty assistant turn was appended

    def test_the_last_turns_tool_data_is_carried_forward(self, user):
        """The regression a LIVE run caught, and the only test here written from a measured
        failure rather than a design intent.

        Rehydration replays `query`/`output` - the conversation as the USER saw it - and not
        the tool results behind it. So a follow-up about a figure the previous turn fetched
        but did not write out ("and its forward P/E?") cannot see the number. Under the
        phase-5 prose protocol the model does not call the tool again, it ESTIMATES: wrong
        in 2 of 3 measured runs, confidently, with no error anywhere. Carrying the data
        fixed 5 of 5.
        """
        session = _session(user)
        previous = _turn(user, session, "AAPL PE?", output="39.07")
        previous.steps.create(
            order=0,
            meta={"tool": "company_snapshot", "observation": '{"forward_pe": 35.58}'},
        )
        current = _turn(user, session, "and forward?", status=AgentRun.Status.RUNNING)

        joined = " ".join(m["content"] for m in self._prompt_for(current))

        assert "35.58" in joined
        assert "company_snapshot returned" in joined

    def test_only_the_most_recent_turn_carries_its_data(self, user):
        """A follow-up is nearly always about what was just looked up. Carrying every turn's
        observations would spend the conversation budget on numbers nobody asked about."""
        session = _session(user)
        old_turn = _turn(user, session, "KO?", output="ok")
        old_turn.steps.create(
            order=0, meta={"tool": "company_snapshot", "observation": "STALE-MARKER"}
        )
        recent = _turn(user, session, "AAPL?", output="ok")
        recent.steps.create(
            order=0, meta={"tool": "company_snapshot", "observation": "FRESH-MARKER"}
        )
        current = _turn(user, session, "and?", status=AgentRun.Status.RUNNING)

        joined = " ".join(m["content"] for m in self._prompt_for(current))

        assert "FRESH-MARKER" in joined
        assert "STALE-MARKER" not in joined

    def test_carried_data_is_truncated(self, user):
        """company_financials is ~1,180 tokens and would eat the whole TURN_RESERVE."""
        from apps.llm_analysis.chat_agent import CARRY_OBSERVATION_CHARS

        session = _session(user)
        previous = _turn(user, session, "financials?", output="ok")
        previous.steps.create(
            order=0, meta={"tool": "company_financials", "observation": "x" * 5000}
        )
        current = _turn(user, session, "and?", status=AgentRun.Status.RUNNING)

        joined = " ".join(m["content"] for m in self._prompt_for(current))

        assert "x" * CARRY_OBSERVATION_CHARS in joined
        assert "x" * (CARRY_OBSERVATION_CHARS + 1) not in joined

    def test_carried_data_is_droppable_under_budget_pressure(self, user):
        """It enters the pad as an OBSERVATION, which is what Scratchpad sheds first -
        so carrying it can never push the conversation itself out."""
        session = _session(user)
        previous = _turn(user, session, "AAPL?", output="ok")
        previous.steps.create(order=0, meta={"tool": "company_snapshot", "observation": "CARRIED"})
        current = _turn(user, session, "and?", status=AgentRun.Status.RUNNING)

        strategy = self._strategy_for(current)
        kinds = [kind for kind, _, _ in strategy.pad._entries]

        assert "observation" in kinds

    def test_a_turn_with_no_tool_calls_carries_nothing(self, user):
        session = _session(user)
        _turn(user, session, "hello", output="hi there")
        current = _turn(user, session, "and?", status=AgentRun.Status.RUNNING)

        joined = " ".join(m["content"] for m in self._prompt_for(current))

        assert "Data you looked up" not in joined

    def test_another_sessions_turns_are_not_replayed(self, user):
        mine, theirs = _session(user), _session(user)
        _turn(user, theirs, "unrelated", output="leak")
        current = _turn(user, mine, "hi", status=AgentRun.Status.RUNNING)

        assert "leak" not in [m["content"] for m in self._prompt_for(current)]

    def test_a_sessionless_turn_has_no_history(self, user):
        run = create_chat_run(user=user, query="hi", model="", max_steps=4)

        from apps.llm_analysis.chat_agent import ChatStrategy

        strategy = ChatStrategy(run, model="")
        assert strategy.replayed == 0
        assert [m["content"] for m in strategy.pad.messages][-1] == "hi"

    def test_the_summary_is_replayed_when_present(self, user):
        """Phase 3 writes it; the rehydration path has to honour it from the start or the
        compaction phase lands on an untested seam."""
        session = _session(user, summary="They asked about AAPL.", summarised_upto=2)
        current = _turn(user, session, "and now?", status=AgentRun.Status.RUNNING)

        joined = " ".join(m["content"] for m in self._prompt_for(current))
        assert "They asked about AAPL." in joined

    def test_the_started_event_reports_how_much_history_was_replayed(self, user):
        session = _session(user)
        _turn(user, session, "a", output="A")
        _turn(user, session, "b", output="B")
        current = _turn(user, session, "c", status=AgentRun.Status.RUNNING)

        with _patch_tokens(_answer()):
            events = _events(run_chat(current, model=""))

        assert events[0]["history"] == 2


@pytest.mark.django_db
class TestTurnNumbering:
    def test_turn_is_derived_from_the_session_not_the_caller(self, user):
        session = _session(user)
        first = _turn(user, session, "a")
        second = _turn(user, session, "b")

        assert first.meta["turn"] == 0
        assert second.meta["turn"] == 1

    def test_a_new_turn_bumps_the_session_ordering(self, user):
        session = _session(user)
        before = session.updated_at
        _turn(user, session, "a")

        session.refresh_from_db()
        assert session.updated_at > before


@pytest.mark.django_db(transaction=True)
class TestConcurrencyGuard:
    def test_a_second_turn_while_one_runs_is_rejected(self, auth_client, user, llm_settings):
        session = _session(user)
        _turn(user, session, "in flight", status=AgentRun.Status.RUNNING)

        response = auth_client.post(
            CHAT_URL, {"message": "me too", "session": str(session.id)}, format="json"
        )

        assert response.status_code == 409
        # And nothing was written - a rejected turn must not leave a row behind.
        assert session.turns.count() == 1

    def test_a_running_turn_in_another_session_does_not_block(
        self, auth_client, user, llm_settings
    ):
        busy, free = _session(user), _session(user)
        _turn(user, busy, "in flight", status=AgentRun.Status.RUNNING)

        with _patch_tokens(_answer()):
            response = auth_client.post(
                CHAT_URL, {"message": "hi", "session": str(free.id)}, format="json"
            )
            b"".join(response.streaming_content)

        assert response.status_code == 200


@pytest.mark.django_db(transaction=True)
class TestSessionOnTheTurnEndpoint:
    def test_omitting_the_session_creates_one(self, auth_client, llm_settings):
        from apps.llm_analysis.models import ChatSession

        with _patch_tokens(_answer()):
            response = auth_client.post(CHAT_URL, {"message": "hi"}, format="json")
            b"".join(response.streaming_content)

        assert response.status_code == 200
        session = ChatSession.objects.get()
        assert session.turns.count() == 1

    def test_another_users_session_is_404_not_403(self, auth_client, other_user, llm_settings):
        """403 would confirm the id exists. Same rule as AgentRunDetailView."""
        theirs = _session(other_user)

        response = auth_client.post(
            CHAT_URL, {"message": "hi", "session": str(theirs.id)}, format="json"
        )

        assert response.status_code == 404
        assert theirs.turns.count() == 0

    @pytest.mark.title_task
    def test_the_first_turn_queues_a_title_and_later_turns_do_not(self, auth_client, llm_settings):
        with (
            _patch_tokens(_answer(), _answer()),
            patch("apps.llm_analysis.tasks.generate_chat_title.delay") as delay,
        ):
            first = auth_client.post(CHAT_URL, {"message": "hi"}, format="json")
            b"".join(first.streaming_content)
            session_id = str(AgentRun.objects.get(kind="chat").session_id)

            second = auth_client.post(
                CHAT_URL, {"message": "again", "session": session_id}, format="json"
            )
            b"".join(second.streaming_content)

        assert delay.call_count == 1

    @pytest.mark.title_task
    def test_a_broker_failure_does_not_fail_the_turn(self, auth_client, llm_settings):
        """A dev box often has no worker. A cosmetic title must never cost a reply."""
        with (
            _patch_tokens(_answer("still works")),
            patch(
                "apps.llm_analysis.tasks.generate_chat_title.delay",
                side_effect=OSError("no broker"),
            ),
        ):
            response = auth_client.post(CHAT_URL, {"message": "hi"}, format="json")
            b"".join(response.streaming_content)

        assert response.status_code == 200
        assert AgentRun.objects.get(kind="chat").output == "still works"


@pytest.mark.django_db
class TestSessionEndpoints:
    def test_list_is_owner_scoped_and_newest_active_first(self, auth_client, user, other_user):
        old = _session(user, title="older")
        new = _session(user, title="newer")
        _session(other_user, title="theirs")
        # updated_at is auto_now, so touch `old` to make the ordering deterministic.
        new.save()

        response = auth_client.get(SESSIONS_URL)

        assert response.status_code == 200
        titles = [s["title"] for s in response.data["results"]]
        assert "theirs" not in titles
        assert titles == ["newer", "older"]
        assert old.title == "older"

    def test_list_rows_carry_a_turn_count(self, auth_client, user):
        session = _session(user)
        _turn(user, session, "a")
        _turn(user, session, "b")

        row = auth_client.get(SESSIONS_URL).data["results"][0]

        assert row["turn_count"] == 2
        assert row["last_message_at"] is not None

    def test_post_creates_an_empty_session_for_the_requester(self, auth_client, user):
        response = auth_client.post(SESSIONS_URL, {}, format="json")

        assert response.status_code == 201
        assert response.data["turn_count"] == 0

    def test_detail_returns_the_transcript_oldest_first(self, auth_client, user):
        session = _session(user)
        _turn(user, session, "first", output="1")
        _turn(user, session, "second", output="2")

        response = auth_client.get(f"{SESSIONS_URL}{session.id}/")

        assert response.status_code == 200
        assert [t["query"] for t in response.data["turns"]] == ["first", "second"]

    def test_detail_404s_another_users_session(self, auth_client, other_user):
        theirs = _session(other_user)

        assert auth_client.get(f"{SESSIONS_URL}{theirs.id}/").status_code == 404

    def test_patch_renames(self, auth_client, user):
        session = _session(user)

        response = auth_client.patch(
            f"{SESSIONS_URL}{session.id}/", {"title": "Valuation chat"}, format="json"
        )

        assert response.status_code == 200
        session.refresh_from_db()
        assert session.title == "Valuation chat"

    def test_patch_cannot_reassign_a_session_to_another_user(self, auth_client, user, other_user):
        session = _session(user)

        auth_client.patch(
            f"{SESSIONS_URL}{session.id}/", {"user": str(other_user.id)}, format="json"
        )

        session.refresh_from_db()
        assert session.user_id == user.id

    def test_delete_cascades_to_turns_and_steps(self, auth_client, user):
        session = _session(user)
        run = _turn(user, session, "a", output="1")
        run.steps.create(order=0, meta={"tool": "company_profile"})

        response = auth_client.delete(f"{SESSIONS_URL}{session.id}/")

        assert response.status_code == 204
        assert AgentRun.objects.filter(kind="chat").count() == 0
        assert AgentStep.objects.count() == 0

    def test_requires_authentication(self, api_client):
        assert api_client.get(SESSIONS_URL).status_code == 401


@pytest.mark.django_db
class TestTitleTask:
    def test_titles_a_session_from_its_first_message(self, user):
        from apps.llm_analysis.tasks import generate_chat_title

        session = _session(user)
        _turn(user, session, "How is Coca-Cola's dividend covered?")

        with patch("apps.llm_analysis.services.chat", return_value="KO dividend cover"):
            title = generate_chat_title(str(session.id))

        session.refresh_from_db()
        assert title == "KO dividend cover"
        assert session.title == "KO dividend cover"

    def test_runs_on_the_classifier_model(self, user):
        """A four-word summary is not worth swapping the main model in."""
        from apps.llm_analysis.tasks import generate_chat_title

        session = _session(user)
        _turn(user, session, "q")

        with (
            patch("apps.llm_analysis.services.chat", return_value="t") as chat,
            patch("apps.llm_analysis.services._classifier_model", return_value="qwen3:1.7b"),
        ):
            generate_chat_title(str(session.id))

        assert chat.call_args.kwargs["model"] == "qwen3:1.7b"

    def test_strips_quotes_and_takes_the_first_line(self, user):
        from apps.llm_analysis.tasks import generate_chat_title

        session = _session(user)
        _turn(user, session, "q")

        with patch("apps.llm_analysis.services.chat", return_value='"KO cover"\nHope that helps!'):
            assert generate_chat_title(str(session.id)) == "KO cover"

    def test_an_ollama_failure_leaves_the_title_blank(self, user):
        from apps.llm_analysis.tasks import generate_chat_title

        session = _session(user)
        _turn(user, session, "q")

        # The TITLE task uses the blocking services.chat, not the token stream.
        with patch("apps.llm_analysis.services.chat", side_effect=OllamaServiceError("down")):
            assert generate_chat_title(str(session.id)) == ""

        session.refresh_from_db()
        assert session.title == ""

    def test_does_not_overwrite_an_existing_title(self, user):
        from apps.llm_analysis.tasks import generate_chat_title

        session = _session(user, title="Renamed by the user")
        _turn(user, session, "q")

        with patch("apps.llm_analysis.services.chat") as chat:
            generate_chat_title(str(session.id))

        chat.assert_not_called()

    def test_tolerates_a_deleted_session(self, user):
        import uuid

        from apps.llm_analysis.tasks import generate_chat_title

        assert generate_chat_title(str(uuid.uuid4())) == ""

    def test_a_session_with_no_turns_yet_is_a_no_op(self, user):
        """The task is queued on the first turn, so it can lose the race with the row."""
        from apps.llm_analysis.tasks import generate_chat_title

        session = _session(user)

        with patch("apps.llm_analysis.services.chat") as chat:
            assert generate_chat_title(str(session.id)) == ""

        chat.assert_not_called()

    def test_a_blank_model_response_leaves_the_title_blank(self, user):
        from apps.llm_analysis.tasks import generate_chat_title

        session = _session(user)
        _turn(user, session, "q")

        with patch("apps.llm_analysis.services.chat", return_value='  "" \n'):
            assert generate_chat_title(str(session.id)) == ""

        session.refresh_from_db()
        assert session.title == ""


@pytest.mark.django_db
class TestPriorTurns:
    def test_a_run_with_no_session_has_no_prior_turns(self, user):
        """`_rehydrate` guards this too, so the check here is only reachable if something
        else calls the helper. Pinned so the guard is real rather than decorative."""
        from apps.llm_analysis.chat_agent import _prior_turns

        run = create_chat_run(user=user, query="hi", model="", max_steps=4)

        assert _prior_turns(run) == []


# ---------------------------------------------------------------------------
# Compaction (phase 3)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCompaction:
    """At num_ctx=4096 the Scratchpad budget is ~3,000 tokens and a chat session is the first
    workload here that exceeds it. Scratchpad cannot save us - it drops the oldest tool
    OBSERVATION and a transcript has none, so it reaches "nothing droppable left" and hands
    Ollama an oversized prompt to truncate silently. These tests are that safety net."""

    def _fill(self, user, session, n, size=600):
        for i in range(n):
            _turn(user, session, f"question {i} " + "x" * size, output=f"answer {i} " + "y" * size)

    def _strategy(self, run):
        from apps.llm_analysis.chat_agent import ChatStrategy

        return ChatStrategy(run, model="")

    def test_a_short_session_is_not_compacted(self, user):
        session = _session(user)
        self._fill(user, session, 2, size=20)
        current = _turn(user, session, "next", status=AgentRun.Status.RUNNING)

        with patch("apps.llm_analysis.services.chat") as chat:
            strategy = self._strategy(current)

        chat.assert_not_called()
        assert strategy.compacted == 0
        session.refresh_from_db()
        assert session.summary == ""

    def test_a_long_session_is_compacted_and_persisted(self, user):
        session = _session(user)
        self._fill(user, session, 12)
        current = _turn(user, session, "next", status=AgentRun.Status.RUNNING)

        with patch("apps.llm_analysis.services.chat", return_value="They asked about AAPL."):
            strategy = self._strategy(current)

        assert strategy.compacted > 0
        session.refresh_from_db()
        assert session.summary == "They asked about AAPL."
        assert session.summarised_upto > 0

    def test_the_prompt_stays_inside_the_context_budget(self, user):
        """The point of the whole phase. A 30-turn session must still fit."""
        from apps.llm_analysis._context import RESPONSE_RESERVE, estimate_tokens
        from apps.llm_analysis.config import get_llm_config

        session = _session(user)
        self._fill(user, session, 30)
        current = _turn(user, session, "next", status=AgentRun.Status.RUNNING)

        with patch("apps.llm_analysis.services.chat", return_value="A short summary."):
            strategy = self._strategy(current)

        used = sum(estimate_tokens(m["content"]) for m in strategy.pad.messages)
        assert used <= int(get_llm_config().num_ctx * (1 - RESPONSE_RESERVE))

    def test_the_history_budget_leaves_room_for_the_biggest_tool_observation(self):
        """The defect a LIVE run found that no unit test had.

        The first version of this was a flat 50% share of the pad budget, which at
        num_ctx=4096 left 915 tokens for the turn's own work - less than the ~1,180 a single
        `company_financials` observation costs. The model would fetch the financials and
        Scratchpad would immediately drop an observation to stay in budget, so the turn
        answered without the data it had just asked for. Nothing failed; the answer was just
        worse.

        Pinned against the real catalogue size rather than a number, so adding a tool (which
        grows the system prompt) cannot silently re-create it.
        """
        from apps.llm_analysis._context import RESPONSE_RESERVE, estimate_tokens
        from apps.llm_analysis.chat_agent import TURN_RESERVE, _history_budget, _system_prompt
        from apps.llm_analysis.config import get_llm_config

        pad = int(get_llm_config().num_ctx * (1 - RESPONSE_RESERVE))
        spent = estimate_tokens(_system_prompt()) + _history_budget()

        # Measured 2026-09-28 against the live tools; company_financials is the largest.
        biggest_observation = 1181
        assert pad - spent >= biggest_observation, (
            "the turn has less room than one company_financials observation"
        )
        assert TURN_RESERVE >= biggest_observation

    def test_the_history_budget_shrinks_as_the_system_prompt_grows(self):
        """Derived, not a fraction - otherwise a twelfth tool silently eats the turn's room."""
        from apps.llm_analysis import chat_agent

        baseline = chat_agent._history_budget()
        with patch.object(chat_agent, "_system_prompt", return_value="x" * 4000):
            assert chat_agent._history_budget() < baseline

    def test_compaction_runs_on_the_classifier_model(self, user):
        """A chat turn must not wait on a second MAIN-model call for housekeeping."""
        session = _session(user)
        self._fill(user, session, 12)
        current = _turn(user, session, "next", status=AgentRun.Status.RUNNING)

        with (
            patch("apps.llm_analysis.services.chat", return_value="s") as chat,
            patch("apps.llm_analysis.services._classifier_model", return_value="qwen3:1.7b"),
        ):
            self._strategy(current)

        assert chat.call_args.kwargs["model"] == "qwen3:1.7b"

    def test_the_most_recent_turns_are_never_summarised(self, user):
        """Summarising the exchange the user is replying to is how an assistant starts
        answering a question nobody asked."""
        from apps.llm_analysis.chat_agent import KEEP_VERBATIM

        session = _session(user)
        self._fill(user, session, 12)
        last_kept = session.turns.order_by("created_at").last()
        current = _turn(user, session, "next", status=AgentRun.Status.RUNNING)

        with patch("apps.llm_analysis.services.chat", return_value="s"):
            strategy = self._strategy(current)

        contents = [m["content"] for m in strategy.pad.messages]
        assert last_kept.query in contents
        assert strategy.replayed == KEEP_VERBATIM

    def test_folded_turns_are_not_also_sent_verbatim(self, user):
        """Otherwise the model is told the same thing twice - once compressed, once in full."""
        session = _session(user)
        self._fill(user, session, 12)
        first = session.turns.order_by("created_at").first()
        current = _turn(user, session, "next", status=AgentRun.Status.RUNNING)

        with patch("apps.llm_analysis.services.chat", return_value="s"):
            strategy = self._strategy(current)

        assert first.query not in [m["content"] for m in strategy.pad.messages]

    def test_the_summary_is_reused_not_recomputed(self, user):
        """Persisted on the session precisely so every later turn does not re-summarise."""
        session = _session(user)
        self._fill(user, session, 12)
        first = _turn(user, session, "a", output="b")

        with patch("apps.llm_analysis.services.chat", return_value="s") as chat:
            self._strategy(first)
            assert chat.call_count == 1

            second = _turn(user, session, "next", status=AgentRun.Status.RUNNING)
            self._strategy(second)
            # Still 1: the tail is short again, so nothing needs folding.
            assert chat.call_count == 1

    def test_summarised_upto_only_moves_forward(self, user):
        """Pinned as an INVARIANT rather than defended with a `max()`.

        `compact` folds only what `_verbatim` yields, and `_verbatim` yields only turns at
        or after the current `summarised_upto` - so the new value is always greater. The
        first version of this test set `summarised_upto` high and asserted it did not move,
        which made `_verbatim` return nothing, `compact` return early, and the assertion
        pass without ever reaching the line it was about. A mutation check caught that.
        """
        from apps.llm_analysis.chat_agent import compact

        session = _session(user)
        self._fill(user, session, 12)

        seen = []
        with patch("apps.llm_analysis.services.chat", return_value="s"):
            for _ in range(3):
                turns = list(session.turns.order_by("created_at"))
                compact(session, turns)
                session.refresh_from_db()
                seen.append(session.summarised_upto)
                self._fill(user, session, 8)

        assert seen == sorted(seen)
        assert seen[0] > 0
        assert len(set(seen)) == len(seen), "each compaction must advance the marker"

    def test_verbatim_never_yields_an_already_folded_turn(self, user):
        """The invariant the line above depends on, pinned directly."""
        from apps.llm_analysis.chat_agent import _verbatim

        session = _session(user)
        self._fill(user, session, 6, size=20)
        session.summarised_upto = 4
        turns = list(session.turns.order_by("created_at"))

        kept = _verbatim(session, turns)

        assert [t.meta["turn"] for t in kept] == [4, 5]

    def test_a_failed_compaction_still_produces_an_answer(self, user):
        """A housekeeping failure must never eat the user's question."""
        session = _session(user)
        self._fill(user, session, 12)
        current = _turn(user, session, "next", status=AgentRun.Status.RUNNING)

        # Compaction uses the blocking chat; the TURN uses the token stream.
        with (
            patch("apps.llm_analysis.services.chat", side_effect=OllamaServiceError("down")),
            _patch_tokens(_answer("answered anyway")),
        ):
            events = _events(run_chat(current, model=""))

        assert events[0]["compacted"] == 0
        current.refresh_from_db()
        assert current.status == AgentRun.Status.DONE
        assert current.output == "answered anyway"

    def test_an_unexpected_error_during_compaction_is_also_survivable(self, user):
        session = _session(user)
        self._fill(user, session, 12)
        current = _turn(user, session, "next", status=AgentRun.Status.RUNNING)

        with patch(
            "apps.llm_analysis.chat_agent.compact", side_effect=ZeroDivisionError("policy bug")
        ):
            strategy = self._strategy(current)

        assert strategy.compacted == 0

    def test_a_blank_summary_is_not_persisted(self, user):
        """A small model answering with whitespace must not erase the history it replaced."""
        from apps.llm_analysis.chat_agent import compact

        session = _session(user)
        self._fill(user, session, 12)
        turns = list(session.turns.order_by("created_at"))

        with patch("apps.llm_analysis.services.chat", return_value="   \n "):
            assert compact(session, turns) == 0

        session.refresh_from_db()
        assert session.summary == ""
        assert session.summarised_upto == 0

    def test_compaction_is_reported_on_the_run_and_the_stream(self, user):
        session = _session(user)
        self._fill(user, session, 12)
        current = _turn(user, session, "next", status=AgentRun.Status.RUNNING)

        with (
            patch("apps.llm_analysis.services.chat", return_value="a summary"),
            _patch_tokens(_answer("hi")),
        ):
            events = _events(run_chat(current, model=""))

        assert events[0]["compacted"] > 0
        current.refresh_from_db()
        assert current.meta["compacted"] > 0

    def test_nothing_to_fold_is_a_no_op(self, user):
        from apps.llm_analysis.chat_agent import compact

        session = _session(user)
        self._fill(user, session, 1, size=20)

        with patch("apps.llm_analysis.services.chat") as chat:
            assert compact(session, list(session.turns.all())) == 0

        chat.assert_not_called()

    def test_the_started_event_carries_the_run_and_session_ids(self, user):
        """Stop needs the row id, and a chat user stops a half-written reply constantly.
        `succeed` adds run_id to the terminal event, which is too late to be useful."""
        session = _session(user)
        run = _turn(user, session, "hi", status=AgentRun.Status.RUNNING)

        with _patch_tokens(_answer()):
            events = _events(run_chat(run, model=""))

        assert events[0]["run_id"] == str(run.id)
        assert events[0]["session_id"] == str(session.id)

    def test_a_sessionless_turn_reports_a_null_session_id(self, user):
        run = create_chat_run(user=user, query="hi", model="", max_steps=4)

        with _patch_tokens(_answer()):
            events = _events(run_chat(run, model=""))

        assert events[0]["session_id"] is None


# ---------------------------------------------------------------------------
# Token streaming (phase 5)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTokenStreaming:
    """Chat is the only INTERACTIVE workflow here, and the harness streams STEPS, not
    tokens - every driven workflow uses the blocking `services.chat`. Without this the new
    page would render a whole reply at once, which is visibly worse than the legacy chat it
    replaces. `perform_streaming` is the opt-in hook that makes it possible."""

    def _run(self, user, query="hello", max_steps=4):
        return create_chat_run(user=user, query=query, model="", max_steps=max_steps)

    def test_an_answer_is_streamed_as_deltas(self, user):
        run = self._run(user)
        with _patch_tokens("The trailing P/E is 39.07, a little above the sector median."):
            events = _events(run_chat(run, model=""))

        deltas = [e for e in events if e["event"] == "delta"]
        assert len(deltas) > 1, "a one-chunk 'stream' is not streaming"
        assert events[0]["event"] == "started"
        assert events[-1]["event"] == "result"

    def test_the_deltas_concatenate_to_exactly_what_is_persisted(self, user):
        """The invariant the whole feature rests on. If these two differ, a reload silently
        changes the reply the user already read."""
        answer = "AAPL trades at 39.07x trailing earnings."
        run = self._run(user)
        with _patch_tokens(answer):
            events = _events(run_chat(run, model=""))

        run.refresh_from_db()
        assert _deltas(events) == run.output == answer
        assert events[-1]["output"] == answer

    def test_a_tool_call_is_never_streamed_to_the_user(self, user):
        """Half a JSON tool call means nothing, and raw JSON in a chat bubble is worse than
        a pause. Only the final prose reply streams."""
        run = self._run(user)
        with (
            _patch_tokens(_action("company_snapshot", symbol="AAPL"), "It is 39.07."),
            patch("apps.llm_analysis.tools.run_tool", return_value='{"trailing_pe": 39.07}'),
        ):
            events = _events(run_chat(run, model=""))

        assert "company_snapshot" not in _deltas(events)
        assert _deltas(events) == "It is 39.07."

    def test_leading_whitespace_is_not_streamed(self, user):
        run = self._run(user)
        with _patch_tokens("\n\n  Hello there."):
            events = _events(run_chat(run, model=""))

        run.refresh_from_db()
        assert _deltas(events) == run.output == "Hello there."

    def test_a_leading_whitespace_chunk_defers_the_classification(self, user):
        """The classifier must not decide on a chunk that is all whitespace - it would read
        the empty string as prose and start streaming before it knows what this turn is."""
        run = self._run(user)
        # 10 spaces > the 8-char chunk size, so the first chunk carries nothing to judge.
        with _patch_tokens("          Hello there."):
            events = _events(run_chat(run, model=""))

        run.refresh_from_db()
        assert _deltas(events) == run.output == "Hello there."

    def test_a_json_wrapped_answer_still_works_and_is_not_streamed(self, user):
        """A small model will sometimes wrap an answer in the old JSON envelope anyway. The
        user wants the answer, not a lecture about the protocol - so it is accepted, whole."""
        run = self._run(user)
        with _patch_tokens(json.dumps({"thought": "t", "answer": "Wrapped reply."})):
            events = _events(run_chat(run, model=""))

        run.refresh_from_db()
        assert run.output == "Wrapped reply."
        assert _deltas(events) == ""
        assert run.status == AgentRun.Status.DONE

    def test_the_forced_answer_streams_too(self, user):
        """It is the slowest reply to arrive and the one a user is most likely to be
        watching, so it is the last place to leave unstreamed."""
        run = self._run(user, max_steps=1)
        with (
            _patch_tokens(_action("company_profile", symbol="AAPL"), "Best I can say is X."),
            patch("apps.llm_analysis.tools.run_tool", return_value="{}"),
        ):
            events = _events(run_chat(run, model=""))

        run.refresh_from_db()
        assert _deltas(events) == run.output == "Best I can say is X."

    def test_a_dropped_client_still_persists_the_whole_answer(self, user):
        """`stream_in_background` keeps driving after a disconnect. Abandoning the generator
        mid-delta must not truncate what lands on the row."""
        answer = "A fairly long reply that the client will stop reading part way through."
        run = self._run(user)

        with _patch_tokens(answer):
            gen = run_chat(run, model="")
            # Consume only the first few frames, then walk away.
            for _ in range(3):
                next(gen)
            # Draining the rest is what stream_in_background's worker does regardless of
            # whether the client is still attached.
            for _ in gen:
                pass

        run.refresh_from_db()
        assert run.output == answer
        assert run.status == AgentRun.Status.DONE

    def test_the_answer_step_is_still_persisted_and_streamed(self, user):
        """Streaming must not cost the step that keeps the live and restored transcripts the
        same length (issue #7)."""
        run = self._run(user)
        with _patch_tokens("Hi."):
            events = _events(run_chat(run, model=""))

        steps = [e for e in events if e["event"] == "step"]
        assert len(steps) == 1
        assert steps[0]["is_answer"] is True
        assert run.steps.count() == 1


class TestToolCallClassification:
    """One character decides whether a partial response is forwarded to the user or held
    back, so it is pinned directly rather than only through the loop."""

    @pytest.mark.parametrize(
        "text",
        ['{"tool": "x"}', '  {"tool": "x"}', "\n{", "```json\n{}", "  ```"],
    )
    def test_json_shaped_openings_are_held_back(self, text):
        from apps.llm_analysis.chat_agent import looks_like_tool_call

        assert looks_like_tool_call(text) is True

    @pytest.mark.parametrize(
        "text",
        ["Hello", "  AAPL trades at 39x", "The answer is {x}", "1. First", "#"],
    )
    def test_prose_is_streamed(self, text):
        from apps.llm_analysis.chat_agent import looks_like_tool_call

        assert looks_like_tool_call(text) is False


@pytest.mark.django_db(transaction=True)
class TestTheClientsRealPayload:
    """Posted exactly as `useChatAgent` builds it. The earlier view tests omitted `session`
    entirely, so a first message - the single most common request - 400'd in the browser
    while every test passed."""

    def test_a_first_message_with_an_explicit_null_session_succeeds(
        self, auth_client, llm_settings
    ):
        with _patch_tokens(_answer("hi")):
            response = auth_client.post(
                CHAT_URL, {"message": "whats the time?", "session": None}, format="json"
            )
            body = b"".join(response.streaming_content).decode()

        assert response.status_code == 200
        assert '"event": "result"' in body
        run = AgentRun.objects.get(kind="chat")
        assert run.output == "hi"
        assert run.session_id is not None

    def test_explicit_nulls_for_every_optional_field_succeed(self, auth_client, llm_settings):
        with _patch_tokens(_answer("hi")):
            response = auth_client.post(
                CHAT_URL,
                {"message": "hi", "session": None, "model": None, "max_steps": None},
                format="json",
            )
            b"".join(response.streaming_content)

        assert response.status_code == 200
        assert AgentRun.objects.get(kind="chat").meta["max_steps"] == llm_settings.chat_max_steps


# ---------------------------------------------------------------------------
# Issue #10: a named ticker is looked up by CODE before the model answers
# ---------------------------------------------------------------------------


@pytest.fixture
def listed(db):
    """Real symbols, including ones that are also everyday words."""
    from apps.companies.models import Company, CompanySnapshot

    for symbol in ("NVDA", "AAPL", "BRK-B", "IT", "SO", "NOW", "ALL", "A"):
        company = Company.objects.create(symbol=symbol, name=symbol)
        CompanySnapshot.objects.create(
            company=company, trailing_pe=28.49, forward_pe=14.35, profit_margins=0.6366, raw={}
        )


@pytest.mark.django_db
class TestNamedTickers:
    def test_a_capitalised_symbol_is_named(self, listed):
        from apps.llm_analysis.chat_agent import named_tickers

        assert named_tickers("is NVDA cheap compared to the sector?") == ["NVDA"]

    def test_order_of_mention_dedupe_and_limit(self, listed):
        from apps.llm_analysis.chat_agent import named_tickers

        assert named_tickers("AAPL vs NVDA, and AAPL again") == ["AAPL", "NVDA"]
        assert named_tickers("AAPL vs NVDA", limit=1) == ["AAPL"]

    def test_lowercase_words_are_never_tickers(self, listed):
        """'so', 'now' and 'all' are all real symbols - matching case-insensitively would
        prefetch three companies for 'so what should i buy now?'."""
        from apps.llm_analysis.chat_agent import named_tickers

        assert named_tickers("so what should i buy now, all things considered?") == []
        assert named_tickers("is nvda cheap?") == []

    def test_a_dollar_prefix_names_a_ticker_in_any_case(self, listed):
        from apps.llm_analysis.chat_agent import named_tickers

        assert named_tickers("is $nvda cheap?") == ["NVDA"]
        assert named_tickers("what about $IT?") == ["IT"]

    def test_ambiguous_domain_words_need_the_dollar(self, listed):
        from apps.llm_analysis.chat_agent import named_tickers

        assert named_tickers("how does the IT sector look?") == []

    def test_shouting_names_nothing_without_a_dollar(self, listed):
        from apps.llm_analysis.chat_agent import named_tickers

        assert named_tickers("SO IS IT CHEAP NOW?") == []
        assert named_tickers("IS $NVDA CHEAP NOW?") == ["NVDA"]

    def test_single_letters_and_unknown_caps_words_are_ignored(self, listed):
        from apps.llm_analysis.chat_agent import named_tickers

        assert named_tickers("A quick question about EPS in the USA") == []

    def test_dotted_share_classes_normalise(self, listed):
        from apps.llm_analysis.chat_agent import named_tickers

        assert named_tickers("and BRK.B?") == ["BRK-B"]


@pytest.mark.django_db
class TestPrefetch:
    def _run(self, user, query, max_steps=4):
        return create_chat_run(user=user, query=query, model="", max_steps=max_steps)

    def _capture(self, *replies):
        """Like _patch_tokens, but records the messages each model call was sent."""
        queue, seen = list(replies), []

        def side_effect(messages, **_kwargs):
            seen.append([dict(m) for m in messages])
            return iter(_chunks(queue.pop(0)))

        return patch("apps.llm_analysis.services.chat_tokens", side_effect=side_effect), seen

    def test_the_named_ticker_is_fetched_before_the_model_is_asked(self, user, listed):
        run = self._run(user, "is NVDA cheap compared to the sector?")
        patcher, seen = self._capture(_answer("NVDA trades at 28.49x."))
        with patcher:
            events = _events(run_chat(run, model=""))

        steps = [e for e in events if e["event"] == "step"]
        assert [s["tool"] for s in steps] == ["peer_comparison", ""]
        # "compared to the SECTOR" - the scope follows the user's own word (issue #13).
        assert steps[0]["tool_args"] == {"symbol": "NVDA", "scope": "sector"}
        assert '"trailing_pe": 28.49' in steps[0]["observation"]
        assert steps[1]["is_answer"] is True

        # ONE model call, and it already had NVDA's own figures in front of it.
        assert len(seen) == 1
        assert any("28.49" in m["content"] for m in seen[0])

        run.refresh_from_db()
        assert run.status == AgentRun.Status.DONE
        assert run.meta["tools_used"] == ["peer_comparison"]

    def test_the_prefetch_is_persisted_so_a_reload_shows_it(self, user, listed):
        run = self._run(user, "is NVDA cheap?")
        with _patch_tokens(_answer("ok")):
            list(run_chat(run, model=""))
        first = AgentStep.objects.filter(run=run).order_by("order").first()
        assert first.meta["tool"] == "peer_comparison"
        assert first.order == 0

    def test_the_prefetch_is_carried_into_the_next_turn(self, user, listed):
        """It is an ordinary tool step, so the existing carry-forward picks it up."""
        from apps.llm_analysis.chat_agent import _carried_observations

        run = self._run(user, "is NVDA cheap?")
        with _patch_tokens(_answer("ok")):
            list(run_chat(run, model=""))
        assert "peer_comparison returned:" in _carried_observations(run)

    def test_the_model_keeps_at_least_one_call(self, user, listed):
        run = self._run(user, "AAPL vs NVDA?", max_steps=2)
        with _patch_tokens(_answer("done")):
            events = _events(run_chat(run, model=""))
        tools_called = [e["tool"] for e in events if e["event"] == "step" and e["tool"]]
        assert tools_called == ["peer_comparison"]  # 1 prefetch, not 2: budget 2 - 1

    def test_a_budget_of_one_is_prefetched_then_forced_to_answer(self, user, listed):
        run = self._run(user, "is NVDA cheap?", max_steps=1)
        with _patch_tokens(_answer("forced")):
            events = _events(run_chat(run, model=""))
        run.refresh_from_db()
        assert run.status == AgentRun.Status.DONE
        assert run.output == "forced"
        assert next(e["tool"] for e in events if e["event"] == "step") == "peer_comparison"

    def test_no_named_ticker_means_no_prefetch(self, user, listed):
        run = self._run(user, "so what should i buy?")
        with (
            _patch_tokens(_answer("I can't recommend a buy.")),
            patch("apps.llm_analysis.tools.run_tool") as run_tool,
        ):
            list(run_chat(run, model=""))
        run_tool.assert_not_called()

    def test_the_model_can_still_call_a_tool_after_the_prefetch(self, user, listed):
        run = self._run(user, "is NVDA cheap vs its sector?")
        with _patch_tokens(_action("recent_price", symbol="NVDA"), _answer("done")):
            events = _events(run_chat(run, model=""))
        tools_called = [e["tool"] for e in events if e["event"] == "step" and e["tool"]]
        assert tools_called == ["peer_comparison", "recent_price"]
        run.refresh_from_db()
        assert run.meta["tools_used"] == ["peer_comparison", "recent_price"]

    def test_a_named_ticker_with_no_snapshot_is_an_observation_not_a_crash(self, user, db):
        from apps.companies.models import Company

        Company.objects.create(symbol="BARE", name="Bare Co")
        run = self._run(user, "is BARE cheap?")
        with _patch_tokens(_answer("I have no data for BARE.")):
            events = _events(run_chat(run, model=""))
        first = next(e for e in events if e["event"] == "step")
        assert "No snapshot data" in first["observation"]
        run.refresh_from_db()
        assert run.status == AgentRun.Status.DONE

    def test_two_named_tickers_are_both_fetched_in_order(self, user, listed):
        run = self._run(user, "AAPL vs NVDA - which is cheaper?")
        with _patch_tokens(_answer("compared")):
            events = _events(run_chat(run, model=""))
        args = [e["tool_args"] for e in events if e["event"] == "step" and e["tool"]]
        assert args == [{"symbol": "AAPL"}, {"symbol": "NVDA"}]

    def test_the_carried_prefetch_labels_its_units(self, user, listed):
        """Issue #11 meets #10: the carry-forward is truncated at 600 chars, and the `_pct`
        NAME is what tells the next turn's model 63.66 is already a percent."""
        from apps.llm_analysis.chat_agent import CARRY_OBSERVATION_CHARS, _carried_observations

        run = self._run(user, "is NVDA cheap?")
        with _patch_tokens(_answer("ok")):
            list(run_chat(run, model=""))
        carried = _carried_observations(run)
        assert '"profit_margins_pct": 63.66' in carried
        assert '"profit_margins":' not in carried
        # The whole snapshot fits: nothing of it is lost to truncation.
        observation = AgentStep.objects.get(run=run, order=0).meta["observation"]
        assert len(observation) < CARRY_OBSERVATION_CHARS

    def test_the_prefetch_thought_names_the_ticker(self, user, listed):
        """The thought is what the UI's tool disclosure shows - it must explain a tool call
        the user never saw the model decide on."""
        run = self._run(user, "is NVDA cheap?")
        with _patch_tokens(_answer("ok")):
            events = _events(run_chat(run, model=""))
        first = next(e for e in events if e["event"] == "step")
        assert "NVDA" in first["thought"]


class TestComparisonScope:
    """The prefetch compares against the group the user NAMED (issue #13): NVDA is 18% below
    its sector's median P/E and 42% below its industry's - both right, for different questions."""

    @pytest.mark.parametrize(
        "text, scope",
        [
            ("is NVDA cheap compared to the sector?", "sector"),
            ("how does NVDA rank in its industry?", "industry"),
            ("NVDA vs the Industry median", "industry"),
            ("is NVDA cheap?", None),
            ("sector first, then industry", "sector"),
        ],
    )
    def test_scope_follows_the_users_word(self, text, scope):
        from apps.llm_analysis.chat_agent import comparison_scope

        assert comparison_scope(text) == scope

    @pytest.mark.django_db
    def test_no_scope_word_leaves_the_tool_default(self, user, listed):
        run = create_chat_run(user=user, query="is NVDA cheap?", model="", max_steps=4)
        with _patch_tokens(_answer("ok")):
            events = _events(run_chat(run, model=""))
        first = next(e for e in events if e["event"] == "step")
        assert first["tool_args"] == {"symbol": "NVDA"}


@pytest.mark.django_db
class TestPrefetchWithAPeerGroup:
    """The `listed` fixture has no sectors, so every other prefetch test exercises the
    no-benchmark branch. This is the path the live issue-#13 runs took."""

    @pytest.fixture
    def tech(self, db):
        from apps.companies.models import Company, CompanySnapshot, Industry, Sector

        sector = Sector.objects.create(name="Technology")
        semis = Industry.objects.create(name="Semiconductors", sector=sector)
        software = Industry.objects.create(name="Software", sector=sector)
        rows = [
            ("NVDA", semis, 28.49, 14.35, 23.73),
            ("AMD", semis, 90.0, 30.0, 4.0),
            ("AVGO", semis, 45.06, 25.0, 16.9),
            ("MU", semis, 24.45, 10.0, 12.1),
            ("MSFT", software, 28.74, 26.0, 8.7),
            ("CRM", software, 40.0, 22.0, 4.5),
        ]
        for symbol, industry, pe, fpe, pb in rows:
            company = Company.objects.create(
                symbol=symbol, name=symbol, sector=sector, industry=industry
            )
            CompanySnapshot.objects.create(
                company=company,
                trailing_pe=pe,
                forward_pe=fpe,
                price_to_book=pb,
                return_on_equity=1.17,
                profit_margins=0.6366,
                dividend_yield=0.0044,
                debt_to_equity=0.17,
                market_cap=5_434_765_213_696,
                raw={},
            )

    def _prefetch(self, user, query):
        run = create_chat_run(user=user, query=query, model="", max_steps=4)
        with _patch_tokens(_answer("ok")):
            events = _events(run_chat(run, model=""))
        return run, next(e for e in events if e["event"] == "step")

    def test_the_model_is_handed_the_relation_not_two_numbers(self, user, tech):
        _, step = self._prefetch(user, "is NVDA cheap compared to the sector?")
        obs = json.loads(step["observation"])
        assert obs["peer_group"] == {"scope": "sector", "name": "Technology", "peers": 5}
        pe = obs["comparisons"]["trailing_pe"]
        # sector peers 90, 45.06, 24.45, 28.74, 40 -> median 40.0; 28.49 is 29% BELOW it.
        assert pe["median"] == 40.0
        assert pe["vs_median"] == "29% below"
        assert pe["reading"] == "cheaper than the typical peer"

    def test_the_users_scope_word_changes_the_group(self, user, tech):
        _, sector = self._prefetch(user, "NVDA vs its sector?")
        _, industry = self._prefetch(user, "NVDA vs its industry?")
        assert json.loads(sector["observation"])["peer_group"]["scope"] == "sector"
        assert json.loads(industry["observation"])["peer_group"]["name"] == "Semiconductors"

    def test_the_carried_slice_keeps_both_pe_relations(self, user, tech):
        """The docs claim valuation ratios come first so the 600-char carry keeps them.
        A follow-up ("and on forward earnings?") must still see the computed relation."""
        from apps.llm_analysis.chat_agent import _carried_observations

        run, _ = self._prefetch(user, "is NVDA cheap compared to the sector?")
        carried = _carried_observations(run)
        trailing = carried.index('"trailing_pe"')
        forward = carried.index('"forward_pe"')
        assert '"vs_median": "29% below"' in carried[trailing:forward]
        assert '"reading": "cheaper than the typical peer"' in carried[forward:]
