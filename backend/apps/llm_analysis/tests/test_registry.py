"""The per-workflow registry (issue #6 phase 6).

`views.py` carried a near-identical list/detail pair per workflow - 22 classes differing
only in `kind` and `serializer_class` - and `urls.py` a hand-written route per view. Both
are now built from `registry.WORKFLOWS`.

The risk of generating routes is that a mistake is invisible: a wrong slug or a dropped
name does not raise, it just 404s or breaks `reverse()` somewhere far away. So the route
table is pinned here EXACTLY, and every per-workflow suite still exercises the real
endpoints unmodified.
"""

from __future__ import annotations

import pytest
from django.urls import NoReverseMatch, get_resolver, reverse

from apps.llm_analysis.models import AgentRun, AgentStep
from apps.llm_analysis.registry import BY_KIND, WORKFLOWS, spec_for
from apps.llm_analysis.views import AgentRunDetailView, AgentRunListView, run_views

# The routes as they shipped before the registry existed. These paths and names are the
# frontend's contract; nothing here may change without a frontend change to match.
EXPECTED_ROUTES = {
    ("chain/", "llm-chain-list"),
    ("chain/<uuid:pk>/", "llm-chain-detail"),
    ("route/history/", "llm-route-list"),
    ("route/<uuid:pk>/", "llm-route-detail"),
    ("parallel/history/", "llm-parallel-list"),
    ("parallel/<uuid:pk>/", "llm-parallel-detail"),
    ("react/history/", "llm-react-list"),
    ("react/<uuid:pk>/", "llm-react-detail"),
    ("evaluate/history/", "llm-evaluate-list"),
    ("evaluate/<uuid:pk>/", "llm-evaluate-detail"),
    ("plan/history/", "llm-plan-list"),
    ("plan/<uuid:pk>/", "llm-plan-detail"),
    ("orchestrate/history/", "llm-orchestrate-list"),
    ("orchestrate/<uuid:pk>/", "llm-orchestrate-detail"),
    ("multiagent/history/", "llm-multiagent-list"),
    ("multiagent/<uuid:pk>/", "llm-multiagent-detail"),
    ("dag/history/", "llm-dag-list"),
    ("dag/<uuid:pk>/", "llm-dag-detail"),
    ("autonomous/history/", "llm-autonomous-list"),
    ("autonomous/<uuid:pk>/", "llm-autonomous-detail"),
    ("browser/history/", "llm-browser-list"),
    ("browser/<uuid:pk>/", "llm-browser-detail"),
    # chat-agent, not chat: /api/llm/chat/ is the legacy non-harness endpoint (issue #8).
    ("chat-agent/history/", "llm-chat-agent-list"),
    ("chat-agent/<uuid:pk>/", "llm-chat-agent-detail"),
    # NOT registry-generated: a ChatSession is a conversation, not a workflow, so it has no
    # WorkflowSpec. They are frozen here anyway - the collector picks up every
    # llm-*-list/-detail route, and pinning these costs nothing while catching a future
    # workflow slug that collides with them.
    ("chat/sessions/", "llm-chat-session-list"),
    ("chat/sessions/<uuid:pk>/", "llm-chat-session-detail"),
}


class TestCompleteness:
    def test_every_run_kind_has_an_entry(self):
        """A workflow with no entry has no endpoints at all. Failing here beats
        discovering it as a 404 after the frontend ships."""
        missing = {k for k, _ in AgentRun.Kind.choices} - set(BY_KIND)

        assert not missing, f"kinds with no registry entry: {sorted(missing)}"

    def test_kinds_and_slugs_are_both_unique(self):
        """A duplicate slug silently shadows a route; a duplicate kind silently drops one."""
        kinds = [w.kind for w in WORKFLOWS]
        slugs = [w.slug for w in WORKFLOWS]

        assert len(set(kinds)) == len(kinds)
        assert len(set(slugs)) == len(slugs)

    def test_unknown_kind_raises_rather_than_guessing(self):
        with pytest.raises(KeyError):
            spec_for("not_a_workflow")

    def test_the_slug_is_not_always_the_kind(self):
        """Pinned because it looks like a bug otherwise. These routes shipped before the
        kinds were consolidated and renaming them would break the frontend for nothing."""
        assert spec_for("eval_opt").slug == "evaluate"
        assert spec_for("plan_exec").slug == "plan"
        assert spec_for("orchestrator").slug == "orchestrate"


class TestGeneratedRoutes:
    def _llm_routes(self) -> set[tuple[str, str]]:
        found: set[tuple[str, str]] = set()

        def walk(patterns, prefix=""):
            for p in patterns:
                if hasattr(p, "url_patterns"):
                    walk(p.url_patterns, prefix + str(p.pattern))
                elif (p.name or "").endswith(("-list", "-detail")) and str(p.name).startswith(
                    "llm-"
                ):
                    found.add((str(p.pattern), p.name))

        walk(get_resolver().url_patterns)
        return found

    def test_the_route_table_is_exactly_what_shipped(self):
        """The whole risk of generating routes: a wrong slug does not raise, it 404s
        somewhere else. So the table is frozen rather than derived from the same registry
        the code uses - a test that recomputed it would agree with any mistake.

        It covers the two hand-written ``chat/sessions/`` routes as well. They are not
        generated, but they share the naming convention the collector matches on, and a
        workflow slug colliding with them would otherwise shadow a route silently.
        """
        assert self._llm_routes() == EXPECTED_ROUTES

    def test_chain_lists_at_its_root_unlike_every_other_workflow(self):
        """chain's routes predate the /history/ convention and the frontend still calls
        the old path. The irregularity is in the registry, not in a special case."""
        assert reverse("llm-chain-list").endswith("/chain/")
        assert reverse("llm-react-list").endswith("/react/history/")

    @pytest.mark.parametrize("spec", WORKFLOWS, ids=lambda s: s.kind)
    def test_both_names_reverse(self, spec):
        assert reverse(spec.list_name)
        assert reverse(spec.detail_name, args=["00000000-0000-0000-0000-000000000000"])

    def test_a_missing_name_would_fail_loudly(self):
        with pytest.raises(NoReverseMatch):
            reverse("llm-nonexistent-list")


@pytest.mark.django_db
class TestGenericViews:
    """The behaviour the 22 deleted classes each re-implemented."""

    @pytest.mark.parametrize("spec", WORKFLOWS, ids=lambda s: s.kind)
    def test_list_is_scoped_to_kind_and_user(self, spec, auth_client, user, django_user_model):
        from apps.llm_analysis import store

        mine = store.create_run(user, query="mine", model="m", kind=spec.kind)
        other = django_user_model.objects.create_user(email="o@t.test", password="x")
        store.create_run(other, query="theirs", model="m", kind=spec.kind)
        # A run of a DIFFERENT kind must not leak into this workflow's history.
        other_kind = next(w.kind for w in WORKFLOWS if w.kind != spec.kind)
        store.create_run(user, query="wrong kind", model="m", kind=other_kind)

        resp = auth_client.get(reverse(spec.list_name))

        assert resp.status_code == 200
        assert [r["id"] for r in resp.data["results"]] == [str(mine.id)]

    @pytest.mark.parametrize("spec", WORKFLOWS, ids=lambda s: s.kind)
    def test_detail_404s_another_users_run(self, spec, auth_client, django_user_model):
        from apps.llm_analysis import store

        other = django_user_model.objects.create_user(email="o2@t.test", password="x")
        theirs = store.create_run(other, query="theirs", model="m", kind=spec.kind)

        resp = auth_client.get(reverse(spec.detail_name, args=[theirs.id]))

        # 404 rather than 403: the endpoint must not confirm that the id exists.
        assert resp.status_code == 404

    def test_detail_404s_a_run_of_the_wrong_kind(self, auth_client, user):
        """Same id, wrong endpoint. Without the kind filter this would render a run
        through a serializer written for a different shape."""
        from apps.llm_analysis import store

        run = store.create_run(user, query="q", model="m", kind="react")

        assert auth_client.get(reverse("llm-dag-detail", args=[run.id])).status_code == 404
        assert auth_client.get(reverse("llm-react-detail", args=[run.id])).status_code == 200

    def test_steps_are_prefetched_not_n_plus_one(
        self, auth_client, user, django_assert_num_queries
    ):
        from apps.llm_analysis import store

        for i in range(4):
            run = store.create_run(user, query=f"q{i}", model="m", kind="react", max_steps=3)
            for order in range(3):
                store.create_step(run, order, key=f"s{order}", status=AgentStep.Status.DONE)

        # Three regardless of how many runs: the count, the page of runs, and ONE more
        # for all their steps together. Four runs x three steps would be 5 without the
        # prefetch, and it grows with the page size.
        with django_assert_num_queries(3):
            resp = auth_client.get(reverse("llm-react-list"))

        assert resp.status_code == 200
        assert resp.data["count"] == 4

    def test_unauthenticated_is_401(self, api_client):
        assert api_client.get(reverse("llm-react-list")).status_code == 401


class TestViewFactory:
    def test_generated_classes_carry_the_kind_and_serializer(self):
        spec = spec_for("dag")

        list_view, detail_view = run_views(spec)

        assert issubclass(list_view, AgentRunListView)
        assert issubclass(detail_view, AgentRunDetailView)
        assert list_view.kind == detail_view.kind == "dag"
        assert list_view.serializer_class is spec.run_serializer

    def test_class_names_are_readable_in_tracebacks(self):
        """Generated classes still need recognisable names - `type(...)` defaults to
        something opaque, and these appear in stack traces and DRF's error pages."""
        list_view, detail_view = run_views(spec_for("eval_opt"))

        assert list_view.__name__ == "EvalOptRunListView"
        assert detail_view.__name__ == "EvalOptRunDetailView"


class TestEveryWorkflowIsStoppable:
    """`STOPPABLE_RUN_MODELS` is the allow-list behind `POST /api/llm/runs/stop/`.

    It was a hand-written literal that no test touched, so a workflow omitted from it is
    silently UNSTOPPABLE - the Stop button posts, gets "Invalid run type or id", and the run
    carries on. `chat` shipped that way and this test is why it did not stay that way.
    """

    def test_the_map_is_exactly_the_registry_slugs(self):
        from apps.llm_analysis.views import STOPPABLE_RUN_MODELS

        assert set(STOPPABLE_RUN_MODELS) == {w.slug for w in WORKFLOWS}

    def test_every_entry_points_at_the_unified_run_model(self):
        from apps.llm_analysis.views import STOPPABLE_RUN_MODELS

        assert set(STOPPABLE_RUN_MODELS.values()) == {AgentRun}


class TestTheLegacyChatPathIsGone:
    """Issue #8 phase 6. Chat ran outside the harness for the whole life of the app - no run
    row, no history, no Stop, no tools - and the reason it could is that nothing pointed at
    it. These pin the removal so it cannot drift back in beside the harness one.
    """

    def test_the_streaming_endpoint_no_longer_resolves(self):
        with pytest.raises(NoReverseMatch):
            reverse("llm-chat-stream")

    def test_no_module_still_calls_the_removed_service(self):
        from pathlib import Path

        from apps.llm_analysis import services

        app = Path(services.__file__).parent
        offenders = [path.name for path in app.glob("*.py") if "chat_stream(" in path.read_text()]

        assert not offenders, (
            f"{offenders} call services.chat_stream, which was removed with the legacy "
            "endpoint - use services.chat_tokens (the raw primitive) instead"
        )

    def test_the_blocking_chat_endpoint_stays(self):
        """`/api/llm/chat/` is NOT the legacy streaming path: it still serves the Agents
        page's `single` comparable type via useSinglePrompt. Pinned so the next tidy-up
        does not take it as well."""
        assert reverse("llm-chat").endswith("/chat/")


class TestOptionalRequestFieldsAcceptNull:
    """An optional field whose default is None must also ACCEPT null.

    `required=False, default=None` lets the key be OMITTED; it does not let it be sent as
    null, and DRF rejects an explicit null with "This field may not be null." Every stream
    helper on the frontend builds its payload with `?? null` - `useChatAgent` sends
    `session: null` for the first message of a new conversation and `useBrowserAgent` sends
    `provider`/`max_steps` the same way - so the gap is a 400 on the most common request, not
    an edge case.

    It reached the browser on issue #8: every first chat message failed, and because the SSE
    reader finds no `data:` lines in a JSON error body it rendered as a blank reply with no
    error at all. Backend tests posted only the keys they cared about and frontend tests
    mocked `fetch`, so nothing exercised the real payload. Hence a derived invariant rather
    than one more example-based test.
    """

    def _request_serializers(self):
        import inspect

        from rest_framework import serializers as drf

        from apps.llm_analysis import serializers as ser

        return [
            (name, cls)
            for name, cls in vars(ser).items()
            if inspect.isclass(cls)
            and issubclass(cls, drf.Serializer)
            and name.endswith("RequestSerializer")
        ]

    def test_every_optional_none_defaulting_field_allows_null(self):
        from rest_framework import serializers as drf

        offenders = [
            f"{name}.{field_name}"
            for name, cls in self._request_serializers()
            for field_name, field in cls().fields.items()
            if field.required is False
            and getattr(field, "default", drf.empty) is None
            and not field.allow_null
        ]

        assert not offenders, (
            f"{offenders} default to None but reject an explicit null - a client sending "
            "`{field}: null` gets a 400. Add allow_null=True."
        )

    def test_the_audit_finds_something_to_check(self):
        """Guards against the test above passing because it examined nothing."""
        assert len(self._request_serializers()) >= 10

    def test_a_chat_turn_accepts_the_payload_the_client_actually_sends(self):
        """The exact body `useChatAgent` posts for the first message of a conversation."""
        from apps.llm_analysis.serializers import ChatAgentRequestSerializer

        ser = ChatAgentRequestSerializer(data={"message": "whats the time?", "session": None})

        assert ser.is_valid(), ser.errors
        assert ser.validated_data["session"] is None
