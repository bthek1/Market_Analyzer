import json
from unittest.mock import patch

from apps.knowledge_graph import llm
from apps.llm_analysis.services import OllamaServiceError


def _reply(description="A field.", neighbors=None):
    return json.dumps(
        {"description": description, "neighbors": neighbors if neighbors is not None else []}
    )


def test_expand_passes_schema_and_temperature():
    captured = {}

    def fake_chat(messages, **kwargs):
        captured.update(kwargs)
        captured["messages"] = messages
        return _reply()

    with patch.object(llm.services, "chat", side_effect=fake_chat):
        llm.expand("Physics")

    assert captured["format"] is llm.EXPANSION_SCHEMA
    assert captured["temperature"] == 0.3


def test_expand_injects_existing_names():
    captured = {}

    def fake_chat(messages, **kwargs):
        captured["messages"] = messages
        return _reply()

    with patch.object(llm.services, "chat", side_effect=fake_chat):
        llm.expand("Physics", existing=["Quantum Mechanics", "Thermodynamics"])

    user_msg = captured["messages"][-1]["content"]
    assert "Quantum Mechanics" in user_msg
    assert "Thermodynamics" in user_msg


def test_expand_malformed_json_returns_empty():
    with patch.object(llm.services, "chat", return_value="not json at all"):
        out = llm.expand("Physics")
    assert out == {"description": "", "negative_description": "", "neighbors": []}


def test_expand_connection_error_returns_empty():
    with patch.object(llm.services, "chat", side_effect=OllamaServiceError("down")):
        out = llm.expand("Physics")
    assert out == {"description": "", "negative_description": "", "neighbors": []}


def test_expand_parses_negative_description():
    reply = json.dumps(
        {
            "description": "music genre",
            "negative_description": "Not the stack pop().",
            "neighbors": [],
        }
    )
    with patch.object(llm.services, "chat", return_value=reply):
        out = llm.expand("pop")
    assert out["negative_description"] == "Not the stack pop()."


def test_expand_missing_negative_description_defaults_empty():
    with patch.object(llm.services, "chat", return_value=_reply()):
        out = llm.expand("Physics")
    assert out["negative_description"] == ""


def test_disambiguate_includes_negative_meaning_in_prompt():
    captured = {}

    def fake_chat(messages, **kwargs):
        captured["messages"] = messages
        return json.dumps({"match": "1"})

    cands = [_cand("id-1", "pop", "music genre")]
    evidence = {"id-1": {"negative": "Not the stack pop() operation."}}
    with patch.object(llm.services, "chat", side_effect=fake_chat):
        llm.disambiguate_sense("pop", cands, _ctx(), evidence=evidence)
    assert "Not the stack pop() operation." in captured["messages"][-1]["content"]


def test_expand_clamps_weight_and_drops_bad_relations():
    neighbors = [
        {"name": "QM", "relation": "subfield_of", "weight": 5.0},  # clamp to 1.0
        {"name": "Bad", "relation": "no_such_relation", "weight": 0.5},  # dropped
        {"name": "", "relation": "subfield_of", "weight": 0.5},  # dropped (blank name)
        {"name": "Energy", "relation": "has_subfield", "weight": -2},  # clamp to 0.0
    ]
    with patch.object(llm.services, "chat", return_value=_reply(neighbors=neighbors)):
        out = llm.expand("Physics")

    names = {n["name"]: n["weight"] for n in out["neighbors"]}
    assert names == {"QM": 1.0, "Energy": 0.0}


def test_expand_caps_neighbor_count():
    neighbors = [{"name": f"N{i}", "relation": "has_subfield", "weight": 0.5} for i in range(20)]
    with patch.object(llm.services, "chat", return_value=_reply(neighbors=neighbors)):
        out = llm.expand("Physics")
    assert len(out["neighbors"]) == llm.max_neighbors()


def test_system_prompt_defines_relation_directions():
    """The hierarchy is offered in both directions; prerequisites are offered ONLY in the
    dependable direction (has_prerequisite), with no reverse ``prerequisite_for`` bucket the
    model tends to invert."""
    prompt = llm._SYSTEM.lower()
    assert "subfield_of" in prompt and "has_subfield" in prompt
    assert "has_prerequisite" in prompt
    assert "prerequisite_for" not in prompt  # the inverted-prone bucket is gone
    # The parent (broader) and child (narrower) framings are both present.
    assert "broader parent" in prompt
    assert "child" in prompt


def test_directed_relation_maps_to_canonical_relation_and_direction():
    """Each directed edge type collapses to a stored Relation plus a source_is_self flag the
    caller uses to orient the edge."""
    neighbors = [
        {"name": "Quantum Mechanics", "relation": "has_subfield", "weight": 0.9},  # child
        {"name": "Science", "relation": "subfield_of", "weight": 0.8},  # parent
        {"name": "Calculus", "relation": "has_prerequisite", "weight": 0.7},  # foundation
        {"name": "Engineering", "relation": "prerequisite_for", "weight": 0.6},  # dropped
    ]
    with patch.object(llm.services, "chat", return_value=_reply(neighbors=neighbors)):
        out = llm.expand("Physics")

    by_name = {n["name"]: n for n in out["neighbors"]}
    # Hierarchy is stored canonically as has_subfield (parent -> child).
    # has_subfield: the neighbor is the child -> THIS concept (parent) is the edge source.
    assert by_name["Quantum Mechanics"]["relation"] == "has_subfield"
    assert by_name["Quantum Mechanics"]["source_is_self"] is True
    # subfield_of: THIS concept is the child -> the neighbor (parent) is the source.
    assert by_name["Science"]["relation"] == "has_subfield"
    assert by_name["Science"]["source_is_self"] is False
    # has_prerequisite: the neighbor is the foundation -> THIS concept is the target.
    assert by_name["Calculus"]["relation"] == "prerequisite_for"
    assert by_name["Calculus"]["source_is_self"] is False
    # prerequisite_for is no longer a valid bucket -> the model-inverted reverse edge is dropped.
    assert "Engineering" not in by_name


def test_system_prompt_passed_as_system_message():
    captured = {}

    def fake_chat(messages, **kwargs):
        captured["messages"] = messages
        return _reply()

    with patch.object(llm.services, "chat", side_effect=fake_chat):
        llm.expand("Physics")

    system_msg = captured["messages"][0]
    assert system_msg["role"] == "system"
    assert system_msg["content"] == llm._SYSTEM


def _neigh(*names):
    return [{"name": n, "relation": "has_subfield", "direction": "has neighbor"} for n in names]


def test_rerank_returns_kept_names_capped_at_keep():
    captured = {}

    def fake_chat(messages, **kwargs):
        captured.update(kwargs)
        captured["messages"] = messages
        return json.dumps({"keep": ["Optics", "Mechanics", "Mass"]})

    with patch.object(llm.services, "chat", side_effect=fake_chat):
        kept = llm.rerank_neighbors("Physics", _neigh("Optics", "Mechanics", "Mass"), keep=2)

    assert kept == ["Optics", "Mechanics"]  # capped at keep
    assert captured["format"] is llm.RERANK_SCHEMA
    # The neighbor names and the concept are both in the user prompt.
    user_msg = captured["messages"][-1]["content"]
    assert "Physics" in user_msg and "Optics" in user_msg


def test_rerank_empty_neighbors_skips_llm():
    with patch.object(llm.services, "chat") as chat:
        assert llm.rerank_neighbors("Physics", [], keep=15) == []
    chat.assert_not_called()


def test_rerank_malformed_or_failed_returns_empty():
    with patch.object(llm.services, "chat", return_value="not json"):
        assert llm.rerank_neighbors("Physics", _neigh("Optics"), keep=5) == []
    with patch.object(llm.services, "chat", side_effect=OllamaServiceError("down")):
        assert llm.rerank_neighbors("Physics", _neigh("Optics"), keep=5) == []


def _cand(pk, name, description):
    from types import SimpleNamespace

    return SimpleNamespace(pk=pk, name=name, description=description)


def _ctx(domain="stacks", relation="prerequisite_for"):
    return {"domain": domain, "relation": relation}


def test_disambiguate_returns_matched_candidate_id():
    cands = [_cand("id-1", "pop", "pop music genre"), _cand("id-2", "pop", "stack op")]
    with patch.object(llm.services, "chat", return_value=json.dumps({"match": "2"})):
        assert llm.disambiguate_sense("pop", cands, _ctx()) == "id-2"


def test_disambiguate_returns_none_for_new_sense():
    cands = [_cand("id-1", "pop", "pop music genre")]
    with patch.object(llm.services, "chat", return_value=json.dumps({"match": "new"})):
        assert llm.disambiguate_sense("pop", cands, _ctx()) is None


def test_disambiguate_passes_schema_and_context():
    captured = {}

    def fake_chat(messages, **kwargs):
        captured.update(kwargs)
        captured["messages"] = messages
        return json.dumps({"match": "1"})

    cands = [_cand("id-1", "pop", "pop music genre")]
    with patch.object(llm.services, "chat", side_effect=fake_chat):
        llm.disambiguate_sense("pop", cands, _ctx(domain="stacks", relation="prerequisite_for"))

    assert captured["format"] is llm.DISAMBIGUATE_SCHEMA
    user_msg = captured["messages"][-1]["content"]
    assert "pop" in user_msg and "stacks" in user_msg and "prerequisite for" in user_msg


def test_disambiguate_includes_evidence_in_prompt():
    captured = {}

    def fake_chat(messages, **kwargs):
        captured["messages"] = messages
        return json.dumps({"match": "1"})

    cands = [_cand("id-1", "pop", "music genre")]
    evidence = {"id-1": {"aliases": ["pop-genre"], "neighbors": ["melody", "rhythm"]}}
    with patch.object(llm.services, "chat", side_effect=fake_chat):
        llm.disambiguate_sense("pop", cands, _ctx(), evidence=evidence)
    user_msg = captured["messages"][-1]["content"]
    assert "pop-genre" in user_msg  # alias evidence reaches the LLM
    assert "melody" in user_msg  # neighbor evidence reaches the LLM


def test_disambiguate_degrades_to_first_candidate_on_failure():
    cands = [_cand("id-1", "pop", "music"), _cand("id-2", "pop", "stack op")]
    # Bad reply / out-of-range / connection error all fall back to the FIRST candidate (reuse).
    with patch.object(llm.services, "chat", return_value="not json"):
        assert llm.disambiguate_sense("pop", cands, _ctx()) == "id-1"
    with patch.object(llm.services, "chat", return_value=json.dumps({"match": "9"})):
        assert llm.disambiguate_sense("pop", cands, _ctx()) == "id-1"
    with patch.object(llm.services, "chat", side_effect=OllamaServiceError("down")):
        assert llm.disambiguate_sense("pop", cands, _ctx()) == "id-1"
