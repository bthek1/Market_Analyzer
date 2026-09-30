"""Context management for the accumulating agent loops (issue #6 phase 5).

Most workflows send a one-shot ``system + user`` per call - there is nothing to manage.
Exactly two loops ACCUMULATE: ``react`` (thought -> tool -> observation, appended every
turn) and ``autonomous.run_subagent`` (the same shape, one level down). Those are what
this module is for.

``num_ctx`` is now declared rather than defaulted (see ``services.chat``), but a declared
window is still a window: Ollama TRUNCATES silently past it rather than erroring, so an
oversized scratchpad degrades the answer with nothing anywhere reporting a problem. A
budget that is enforced here, loudly, is the difference between a trimmed conversation we
chose and a trimmed conversation we discovered months later.

The policy is deliberately simple and stated rather than clever: **drop the oldest tool
observation first**. Observations are the bulkiest part of a scratchpad and the most
replaceable - the model has already reasoned about them, and its own assistant turn
summarising that reasoning is kept. The system prompt and the most recent exchange are
never dropped, because losing either changes what the model is being asked to do.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Fraction of the window left for the model to generate into. A prompt that fills the
#: whole window leaves no room for a reply, which is how the browser agent came to return
#: empty strings (see CLAUDE.md) - the model had context but nowhere to put the answer.
RESPONSE_RESERVE = 0.25

#: Characters per token. A heuristic, not a tokenizer: pulling one in for this would add a
#: model-specific dependency to a budget that only has to be roughly right and
#: conservative. Real English averages nearer 4.
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Approximate token count. Deliberately crude - see ``CHARS_PER_TOKEN``."""
    return len(text) // CHARS_PER_TOKEN + 1


class Scratchpad:
    """An accumulating message list that stays inside a declared token budget.

    Messages are tagged by kind so the trim policy can tell an observation (droppable)
    from reasoning (not). The tags never reach Ollama - ``messages`` emits plain
    ``{"role", "content"}`` dicts.
    """

    __slots__ = ("_budget", "_entries", "_system", "_trimmed")

    def __init__(self, system: str, *, budget_tokens: int | None = None):
        self._system = system
        self._entries: list[tuple[str, str, str]] = []  # (kind, role, content)
        self._budget = budget_tokens if budget_tokens is not None else _default_budget()
        self._trimmed = 0

    # --- building -------------------------------------------------------------------

    def user(self, content: str) -> None:
        self._add("user", "user", content)

    def assistant(self, content: str) -> None:
        self._add("assistant", "assistant", content)

    def observation(self, content: str) -> None:
        """A tool result. Droppable first - see the module docstring."""
        self._add("observation", "user", content)

    def _add(self, kind: str, role: str, content: str) -> None:
        self._entries.append((kind, role, content))
        self._enforce()

    # --- reading --------------------------------------------------------------------

    @property
    def messages(self) -> list[dict[str, str]]:
        """The conversation as Ollama wants it."""
        return [{"role": "system", "content": self._system}] + [
            {"role": role, "content": content} for _, role, content in self._entries
        ]

    @property
    def tokens(self) -> int:
        return estimate_tokens(self._system) + sum(estimate_tokens(c) for _, _, c in self._entries)

    @property
    def trimmed(self) -> int:
        """How many entries this pad has dropped. Surfaced so a caller can report it."""
        return self._trimmed

    def __len__(self) -> int:
        return len(self._entries) + 1

    # --- trimming -------------------------------------------------------------------

    def _enforce(self) -> None:
        if self.tokens <= self._budget:
            return

        # Never the system prompt, never the most recent exchange: losing either changes
        # what the model is being asked to do, which is worse than losing an observation
        # it has already reasoned about.
        protected = 2
        while self.tokens > self._budget:
            index = next(
                (
                    i
                    for i, (kind, _, _) in enumerate(self._entries[:-protected])
                    if kind == "observation"
                ),
                None,
            )
            if index is None:
                # Nothing droppable left. Better an oversized prompt the operator can see
                # in the log than a silently mangled conversation.
                logger.warning(
                    "scratchpad over budget with nothing droppable left",
                    extra={"tokens": self.tokens, "budget": self._budget},
                )
                return
            self._entries.pop(index)
            self._trimmed += 1
            logger.warning(
                "scratchpad trimmed an observation to stay inside the context budget",
                extra={
                    "tokens": self.tokens,
                    "budget": self._budget,
                    "trimmed_total": self._trimmed,
                },
            )


def _default_budget() -> int:
    """The declared context window, less room for the model to answer in."""
    from .config import get_llm_config

    return int(get_llm_config().num_ctx * (1 - RESPONSE_RESERVE))
