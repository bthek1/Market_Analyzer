"""Unit tests for the meta spec validator + store accessors (model consolidation,
meta_json refactor). Pure-logic tests; the validator has no DB dependency."""

import pytest

from apps.llm_analysis import meta_spec, store
from apps.llm_analysis.meta_spec import (
    MetaValidationError,
    validate_run_meta,
    validate_step_meta,
)


class TestValidateRunMeta:
    def test_accepts_known_keys_and_returns_clean_copy(self):
        out = validate_run_meta("react", {"max_steps": 6})
        assert out == {"max_steps": 6}

    def test_unknown_key_raises(self):
        with pytest.raises(MetaValidationError, match="Unknown run meta key 'bogus'"):
            validate_run_meta("react", {"bogus": 1})

    def test_unknown_kind_raises(self):
        with pytest.raises(MetaValidationError, match="Unknown kind"):
            validate_run_meta("nope", {})

    def test_wrong_type_raises(self):
        with pytest.raises(MetaValidationError, match="expects"):
            validate_run_meta("react", {"max_steps": "six"})

    def test_bool_rejected_for_int_field(self):
        # bool is an int subclass; the validator must not let it pass as an int.
        with pytest.raises(MetaValidationError, match="bool"):
            validate_run_meta("react", {"max_steps": True})

    def test_choice_enforced(self):
        assert validate_run_meta("parallel", {"strategy": "voting"}) == {"strategy": "voting"}
        with pytest.raises(MetaValidationError, match="must be one of"):
            validate_run_meta("parallel", {"strategy": "bogus"})

    def test_none_skips_type_check(self):
        # nullable fields (e.g. route_confidence) accept None regardless of declared type.
        assert validate_run_meta("route", {"route_confidence": None}) == {"route_confidence": None}

    def test_json_field_accepts_list_and_dict(self):
        assert validate_run_meta("plan_exec", {"plan": [{"task": "x"}]}) == {
            "plan": [{"task": "x"}]
        }
        assert validate_run_meta("parallel", {"tally": {"buy": 1}}) == {"tally": {"buy": 1}}

    def test_chain_has_no_run_meta(self):
        assert validate_run_meta("chain", {}) == {}
        with pytest.raises(MetaValidationError):
            validate_run_meta("chain", {"max_steps": 1})


class TestValidateStepMeta:
    def test_react_step_keys(self):
        out = validate_step_meta(
            "react",
            {
                "thought": "t",
                "tool": "company_snapshot",
                "tool_args": {"symbol": "AAPL"},
                "observation": "{}",
                "is_answer": False,
            },
        )
        assert out["tool"] == "company_snapshot" and out["is_answer"] is False

    def test_dag_depends_on_is_json(self):
        assert validate_step_meta("dag", {"depends_on": ["a", "b"]}) == {"depends_on": ["a", "b"]}

    def test_autonomous_action_choice(self):
        assert validate_step_meta("autonomous", {"action": "subagent"})["action"] == "subagent"
        with pytest.raises(MetaValidationError):
            validate_step_meta("autonomous", {"action": "bogus"})

    def test_cross_kind_key_rejected(self):
        # 'vote' belongs to parallel, not react.
        with pytest.raises(MetaValidationError):
            validate_step_meta("react", {"vote": "buy"})


class TestDefaults:
    def test_run_defaults_apply_declared_defaults(self):
        d = meta_spec.run_defaults("plan_exec")
        assert d["replans"] == 0 and d["allow_replan"] is None

    def test_step_defaults_booleans(self):
        d = meta_spec.step_defaults("react")
        assert d["is_answer"] is False and d["thought"] == ""

    def test_dag_default_depends_on_empty_list(self):
        assert meta_spec.step_defaults("dag")["depends_on"] == []


class TestMetaView:
    def test_returns_stored_over_default(self):
        view = store.MetaView({"max_steps": 6, "threshold": 8})
        assert view.max_steps == 6
        assert view.get("threshold") == 8

    def test_missing_key_is_none(self):
        view = store.MetaView({})
        assert view.max_steps is None
        assert view.get("nope", "fallback") == "fallback"
