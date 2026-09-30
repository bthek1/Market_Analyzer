"""Context management for the accumulating loops (issue #6 phase 5).

`num_ctx` is now declared rather than defaulted (see `test_services.py`), but a declared
window is still a window: Ollama truncates silently past it. These tests pin the budget
that keeps the two accumulating scratchpads - `react` and `autonomous.run_subagent` -
inside it, and pin the policy that decides what goes when something has to.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.llm_analysis import _context
from apps.llm_analysis._context import RESPONSE_RESERVE, Scratchpad, estimate_tokens


def _roles(pad: Scratchpad) -> list[str]:
    return [m["role"] for m in pad.messages]


def _contents(pad: Scratchpad) -> list[str]:
    return [m["content"] for m in pad.messages]


class TestBuilding:
    def test_system_comes_first_and_stays_first(self):
        pad = Scratchpad("SYS", budget_tokens=10_000)
        pad.user("q")
        pad.assistant("a")
        pad.observation("o")

        assert _roles(pad) == ["system", "user", "assistant", "user"]
        assert pad.messages[0]["content"] == "SYS"

    def test_observation_is_a_user_turn_on_the_wire(self):
        """The kind is ours, for the trim policy. Ollama only ever sees role/content."""
        pad = Scratchpad("SYS", budget_tokens=10_000)
        pad.observation("Observation: {}")

        assert pad.messages[-1] == {"role": "user", "content": "Observation: {}"}
        assert set(pad.messages[-1]) == {"role", "content"}

    def test_nothing_is_trimmed_under_budget(self):
        pad = Scratchpad("SYS", budget_tokens=10_000)
        for i in range(20):
            pad.observation(f"obs {i}")

        assert pad.trimmed == 0
        assert len(pad) == 21


class TestTrimPolicy:
    def test_the_oldest_observation_goes_first(self):
        pad = Scratchpad("SYS", budget_tokens=estimate_tokens("x" * 400))
        pad.user("the question")
        for i in range(6):
            pad.assistant(f"thought {i}")
            pad.observation("o" * 200)

        assert pad.trimmed > 0
        kept = _contents(pad)
        # Reasoning survives; the bulky tool output is what goes.
        assert any("thought 0" in c for c in kept)

    def test_the_system_prompt_is_never_dropped(self):
        pad = Scratchpad("SYSTEM-PROMPT", budget_tokens=4)
        for _ in range(10):
            pad.observation("o" * 500)

        assert pad.messages[0]["content"] == "SYSTEM-PROMPT"

    def test_the_most_recent_exchange_is_never_dropped(self):
        """Losing the latest turn changes what the model is being asked to do, which is
        worse than losing an observation it has already reasoned about."""
        pad = Scratchpad("SYS", budget_tokens=estimate_tokens("x" * 300))
        for i in range(8):
            pad.observation(f"{i}:" + "o" * 150)
        pad.user("THE LATEST QUESTION")

        assert _contents(pad)[-1] == "THE LATEST QUESTION"

    def test_it_gives_up_loudly_rather_than_mangling(self):
        """With nothing droppable left, an oversized prompt an operator can see in the log
        beats a silently mangled conversation."""
        pad = Scratchpad("SYS", budget_tokens=1)

        with patch.object(_context, "logger") as log:
            pad.user("a very long question " * 50)

        assert pad.trimmed == 0
        assert len(pad) == 2
        assert any("nothing droppable" in c.args[0] for c in log.warning.call_args_list)

    def test_trimming_is_logged_with_the_numbers(self):
        pad = Scratchpad("SYS", budget_tokens=estimate_tokens("x" * 200))
        pad.user("q")

        with patch.object(_context, "logger") as log:
            for _ in range(4):
                pad.observation("o" * 200)
                pad.assistant("a")

        # The LAST warning may be the "nothing droppable left" one, which carries no
        # trimmed_total - assert on the trim warning specifically.
        trims = [c for c in log.warning.call_args_list if "trimmed an observation" in c.args[0]]
        assert trims, "a trim happened but was not logged"
        extra = trims[-1].kwargs["extra"]
        assert extra["budget"] == pad._budget
        assert extra["trimmed_total"] == pad.trimmed


@pytest.mark.django_db
class TestBudgetComesFromTheDeclaredWindow:
    def test_default_budget_reserves_room_to_answer(self, llm_settings):
        """A prompt filling the whole window leaves nowhere to put the reply - which is
        exactly how the browser agent came to return empty strings."""
        llm_settings.num_ctx = 16384
        pad = Scratchpad("SYS")

        assert pad._budget == int(16384 * (1 - RESPONSE_RESERVE))
        assert pad._budget < 16384

    def test_budget_follows_the_configured_window(self, llm_settings):
        llm_settings.num_ctx = 4096

        assert Scratchpad("SYS")._budget == int(4096 * (1 - RESPONSE_RESERVE))


@pytest.mark.django_db
class TestTheAccumulatingLoopsUseIt:
    """The two loops this module exists for. Everything else sends a one-shot
    system+user per call and has nothing to accumulate."""

    def test_react_builds_its_scratchpad_through_the_pad(self, user):
        from apps.llm_analysis import store
        from apps.llm_analysis.react import ReActStrategy

        run = store.create_run(user, query="is AAPL cheap", model="m", kind="react", max_steps=3)
        strategy = ReActStrategy(run, "")

        assert isinstance(strategy.pad, Scratchpad)
        assert _roles(strategy.pad) == ["system", "user"]
        assert strategy.pad.messages[-1]["content"] == "is AAPL cheap"

    def test_a_long_react_run_stays_inside_the_budget(self, user, llm_settings):
        """The regression this phase exists to prevent: an agent whose scratchpad grows
        past the window and gets silently truncated by Ollama mid-run."""
        import json

        from apps.llm_analysis import store
        from apps.llm_analysis.react import run_react

        llm_settings.num_ctx = 2048  # small, so a realistic run would overflow it
        run = store.create_run(user, query="q", model="m", kind="react", max_steps=5)

        sizes: list[int] = []
        action = json.dumps({"thought": "look", "tool": "company_profile", "args": {"s": "A"}})
        answer = json.dumps({"thought": "done", "answer": "final"})

        def fake_chat(messages, model=None, **kw):
            sizes.append(sum(estimate_tokens(m["content"]) for m in messages))
            return action if len(sizes) < 5 else answer

        with (
            patch("apps.llm_analysis.services.chat", side_effect=fake_chat),
            patch("apps.llm_analysis.tools.run_tool", return_value="X" * 3000),
        ):
            list(run_react(run, model=""))

        budget = int(2048 * (1 - RESPONSE_RESERVE))
        assert sizes, "the loop never called the model"
        assert max(sizes) <= budget, f"scratchpad reached {max(sizes)} tokens, budget {budget}"
        # And it still finished rather than stalling on a trimmed conversation.
        run.refresh_from_db()
        assert run.output == "final"

    def test_run_subagent_uses_a_pad_too(self, llm_settings):
        import json

        from apps.llm_analysis.autonomous import run_subagent

        llm_settings.num_ctx = 2048
        sizes: list[int] = []
        action = json.dumps({"tool": "company_profile", "args": {"s": "A"}})
        answer = json.dumps({"answer": "found it"})

        def fake_chat(messages, model=None, **kw):
            sizes.append(sum(estimate_tokens(m["content"]) for m in messages))
            return action if len(sizes) < 3 else answer

        with (
            patch("apps.llm_analysis.services.chat", side_effect=fake_chat),
            patch("apps.llm_analysis.tools.run_tool", return_value="Y" * 3000),
        ):
            findings, _steps = run_subagent("g", max_steps=4, model=None)

        assert findings == "found it"
        assert max(sizes) <= int(2048 * (1 - RESPONSE_RESERVE))


class TestBrowserIsDeliberatelyOutOfScope:
    def test_browser_does_not_use_the_scratchpad(self):
        """browser-use owns its own message construction (a serialised DOM plus a
        screenshot per step) and BROWSER_NUM_CTX already sizes the window for it. Pinned
        so the absence reads as a decision rather than an oversight."""
        from pathlib import Path

        source = (Path(_context.__file__).parent / "browser.py").read_text()

        assert "Scratchpad" not in source
        assert "BROWSER_NUM_CTX" in source or "browser_num_ctx" in source
