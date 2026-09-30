"""Issue #9 phase 3: every agent that is SHOWN tools is shown the grounding rule with them.

The rule lives once, in ``tools.tool_catalogue()``, so no workflow carries its own copy. That
only holds while every prompt builds its tool list through that function - so the set of
modules calling it is DERIVED from the source (AST, not grep), and a workflow that starts
embedding the catalogue without a prompt listed below fails here rather than shipping a prompt
nobody checked.
"""

import ast
from pathlib import Path

import pytest

from apps.llm_analysis import (
    autonomous,
    chat_agent,
    dag,
    multiagent,
    orchestrator,
    plan_execute,
    react,
    tools,
)
from apps.llm_analysis.tools import GROUNDING_RULE

_PKG = Path(tools.__file__).parent

_RESEARCHER = next(a for a in multiagent.ROSTER if a.tools)

#: Every rendered prompt that embeds the tool catalogue, keyed by its module.
PROMPTS = {
    "autonomous": [
        autonomous._bootstrap_system,
        autonomous._controller_system,
        lambda: autonomous.SUBAGENT_SYSTEM_TEMPLATE.format(catalogue=tools.tool_catalogue()),
    ],
    "chat_agent": [chat_agent._system_prompt],
    "dag": [lambda: dag._decompose_system(4)],
    "multiagent": [lambda: multiagent._tool_plan_system(_RESEARCHER, 3)],
    "orchestrator": [lambda: orchestrator._orchestrate_system(3)],
    "plan_execute": [lambda: plan_execute._plan_system(4)],
    "react": [react._system_prompt],
}


def _modules_calling_tool_catalogue() -> set[str]:
    found = set()
    for path in _PKG.glob("*.py"):
        if path.stem == "tools":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "tool_catalogue"
            ):
                found.add(path.stem)
    return found


def test_every_catalogue_caller_has_its_prompt_checked():
    assert _modules_calling_tool_catalogue() == set(PROMPTS)


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(b, id=f"{mod}[{i}]")
        for mod, builds in PROMPTS.items()
        for i, b in enumerate(builds)
    ],
)
def test_prompt_carries_the_grounding_rule(build):
    assert GROUNDING_RULE in build()


def test_rule_appears_once_per_prompt():
    # Once, from the catalogue - a hand-pasted second copy is the drift this design prevents.
    for builds in PROMPTS.values():
        for build in builds:
            assert build().count(GROUNDING_RULE) == 1


def test_agents_without_tools_get_no_catalogue_and_no_rule():
    # multiagent's Analyst and Writer are pure reasoning stages: an empty catalogue stays
    # empty rather than becoming a lone rule about tools they cannot call.
    for agent in multiagent.ROSTER:
        if not agent.tools:
            assert tools.tool_catalogue(only=agent.tools) == ""
