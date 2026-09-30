import logging
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import FileResponse, StreamingHttpResponse
from rest_framework.exceptions import NotFound
from rest_framework.generics import (
    ListAPIView,
    ListCreateAPIView,
    RetrieveAPIView,
    RetrieveUpdateDestroyAPIView,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import (
    autonomous,
    browser,
    chain,
    chat_agent,
    config,
    dag,
    eval_opt,
    multiagent,
    orchestrator,
    parallel,
    plan_execute,
    react,
    router,
    services,
    store,
)
from .models import (
    AgentRun,
    ChatSession,
)
from .serializers import (
    AnalyseRequestSerializer,
    AutonomousRequestSerializer,
    BrowserRequestSerializer,
    ChainRequestSerializer,
    ChatAgentRequestSerializer,
    ChatRequestSerializer,
    ChatSessionDetailSerializer,
    ChatSessionSerializer,
    DagRequestSerializer,
    EvalOptRequestSerializer,
    LLMSettingsSerializer,
    MultiAgentRequestSerializer,
    OrchestratorRequestSerializer,
    ParallelRequestSerializer,
    PlanRequestSerializer,
    ReactRequestSerializer,
    RouteRequestSerializer,
    SummariseRequestSerializer,
)

logger = logging.getLogger(__name__)


def _sse_response(content) -> StreamingHttpResponse:
    """Build an SSE streaming response with reverse-proxy buffering disabled.

    nginx buffers upstream responses by default, which would batch/withhold SSE
    frames until its buffer fills (or the response ends) instead of forwarding
    each event as it is produced. ``X-Accel-Buffering: no`` tells nginx to stream
    this response through unbuffered; it is ignored by proxies that do not honour
    it, so it is safe in dev too.
    """
    response = StreamingHttpResponse(content, content_type="text/event-stream")
    response["X-Accel-Buffering"] = "no"
    return response


class LLMSettingsView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        cfg = config.get_llm_config()
        return Response(LLMSettingsSerializer(cfg).data)

    def put(self, request: Request) -> Response:
        return self._update(request, partial=False)

    def patch(self, request: Request) -> Response:
        return self._update(request, partial=True)

    def _update(self, request: Request, *, partial: bool) -> Response:
        cfg = config.get_llm_config()
        ser = LLMSettingsSerializer(cfg, data=request.data, partial=partial)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)


# Maps the frontend workflow-type string to its run model. Single prompt is
# ephemeral (not persisted) and therefore not cancellable.
STOPPABLE_RUN_MODELS = {
    "chain": AgentRun,
    "route": AgentRun,
    "parallel": AgentRun,
    "react": AgentRun,
    "evaluate": AgentRun,
    "plan": AgentRun,
    "orchestrate": AgentRun,
    "multiagent": AgentRun,
    "dag": AgentRun,
    "autonomous": AgentRun,
    "browser": AgentRun,
    # The KEY is the registry SLUG, not the kind - hence "chat-agent". A structural test
    # derives this whole map from `registry.WORKFLOWS`, because it used to be a
    # hand-written literal that nothing checked: a workflow left out of it is simply
    # unstoppable, and the Stop button 400s with "Invalid run type" long after the fact.
    "chat-agent": AgentRun,
}


class StopRunView(APIView):
    """Cancel a running workflow. The background worker polls the run status and
    unwinds the generator once this flips it to ``stopped``."""

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        run_type = request.data.get("type")
        run_id = request.data.get("id")
        model = STOPPABLE_RUN_MODELS.get(run_type)
        if model is None or not run_id:
            return Response({"detail": "Invalid run type or id."}, status=400)
        try:
            stopped = services.request_run_stop(model, run_id, request.user)
        except (ValueError, ValidationError):
            return Response({"detail": "Invalid run id."}, status=400)
        return Response({"stopped": stopped})


class ChatView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        ser = ChatRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        try:
            content = services.chat(d["messages"], model=d.get("model"))
        except services.OllamaServiceError as exc:
            return Response({"detail": str(exc)}, status=503)
        return Response({"content": content})


class SummariseView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        ser = SummariseRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        try:
            content = services.summarise(d["text"], model=d.get("model"))
        except services.OllamaServiceError as exc:
            return Response({"detail": str(exc)}, status=503)
        return Response({"content": content})


class AnalyseView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        ser = AnalyseRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        try:
            content = services.analyse(
                d["text"],
                context=d.get("context"),
                model=d.get("model"),
            )
        except services.OllamaServiceError as exc:
            return Response({"detail": str(exc)}, status=503)
        return Response({"content": content})


class ModelsView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        try:
            models = services.list_models()
        except services.OllamaServiceError as exc:
            return Response({"detail": str(exc)}, status=503)
        return Response(models)


class PromptChainView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> StreamingHttpResponse:
        ser = ChainRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        run = services.create_chain_run(
            user=request.user,
            query=d["query"],
            model=d.get("model") or "",
        )
        gen = chain.run_chain(run, model=d.get("model"))
        return _sse_response(services.stream_in_background(gen, run))


class RouteView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> StreamingHttpResponse:
        ser = RouteRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        run = services.create_route_run(
            user=request.user,
            query=d["query"],
            model=d.get("model") or "",
        )
        gen = router.run_route(run, model=run.model)
        return _sse_response(services.stream_in_background(gen, run))


class ReactView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> StreamingHttpResponse:
        ser = ReactRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        cfg = config.get_llm_config()
        run = services.create_react_run(
            user=request.user,
            query=d["query"],
            model=d.get("model") or "",
            max_steps=d["max_steps"] or cfg.react_max_steps,
        )
        gen = react.run_react(run, model=run.model)
        return _sse_response(services.stream_in_background(gen, run))


def _chat_session(request, session_id) -> ChatSession:
    """The session this turn belongs to, creating one when none was given.

    404s a session the requester does not own rather than 403ing, so the endpoint does not
    confirm that an id exists - the same rule as ``AgentRunDetailView``.
    """
    if session_id is None:
        return ChatSession.objects.create(user=request.user)
    try:
        return ChatSession.objects.get(pk=session_id, user=request.user)
    except ChatSession.DoesNotExist:
        raise NotFound() from None


def _dispatch_title(session: ChatSession) -> None:
    """Queue the title task, tolerating a broker that is not there.

    A title is cosmetic and a dev box often has no Celery worker; failing the turn because
    the sidebar would show "Untitled" would be the wrong trade.
    """
    from . import tasks

    try:
        tasks.generate_chat_title.delay(str(session.id))
    except Exception:  # broker down, misconfigured, anything - a title is not worth a 500
        logger.warning("Could not queue a title for chat session %s", session.id)


class ChatSessionListView(ListCreateAPIView):
    """The conversation sidebar: this user's sessions, most recently active first."""

    permission_classes = (IsAuthenticated,)
    serializer_class = ChatSessionSerializer

    def get_queryset(self):
        return _session_queryset(self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class ChatSessionDetailView(RetrieveUpdateDestroyAPIView):
    """One conversation with its transcript. PATCH renames or archives; DELETE cascades to
    every turn and step, which is the whole point of the session owning them."""

    permission_classes = (IsAuthenticated,)
    serializer_class = ChatSessionDetailSerializer

    def get_queryset(self):
        return _session_queryset(self.request.user).prefetch_related("turns__steps")


def _session_queryset(user):
    from django.db.models import Count, Max

    return (
        ChatSession.objects.filter(user=user)
        .annotate(
            turn_count=Count("turns", distinct=True),
            last_message_at=Max("turns__created_at"),
        )
        .order_by("-updated_at")
    )


class ChatAgentView(APIView):
    """One conversational turn through the agent harness.

    Distinct from ``ChatStreamView`` above, which is the legacy non-harness path and stays
    until the frontend moves over (issue #8 phase 6).
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> StreamingHttpResponse:
        ser = ChatAgentRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        session = _chat_session(request, d.get("session"))

        # Two turns at once FORK the transcript: the second rehydrates without the first's
        # reply, then both write. 409 rather than queueing - the client should not have a
        # second composer open, and silently serialising would hide that it does.
        if services.chat_session_has_running_turn(session):
            return Response(
                {"detail": "This conversation already has a turn in progress."}, status=409
            )

        cfg = config.get_llm_config()
        run = services.create_chat_run(
            user=request.user,
            query=d["message"],
            model=d.get("model") or "",
            max_steps=d["max_steps"] or cfg.chat_max_steps,
            session=session,
        )
        if store.run_meta(run).turn == 0:
            # Named from the first message alone, so it does not wait on the reply. Blank
            # title is a supported state, hence fire-and-forget.
            _dispatch_title(session)

        gen = chat_agent.run_chat(run, model=run.model)
        return _sse_response(services.stream_in_background(gen, run))


class EvaluatorOptimizerView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> StreamingHttpResponse:
        ser = EvalOptRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        cfg = config.get_llm_config()
        run = services.create_eo_run(
            user=request.user,
            query=d["query"],
            model=d.get("model") or "",
            max_iterations=d["max_iterations"] or cfg.eval_max_iterations,
            threshold=d["threshold"] or cfg.eval_threshold,
        )
        gen = eval_opt.run_eval_opt(run, model=run.model)
        return _sse_response(services.stream_in_background(gen, run))


class PlanExecuteView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> StreamingHttpResponse:
        ser = PlanRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        cfg = config.get_llm_config()
        run = services.create_plan_run(
            user=request.user,
            query=d["query"],
            model=d.get("model") or "",
            max_steps=d["max_steps"] or cfg.plan_max_steps,
            allow_replan=d["allow_replan"],
        )
        gen = plan_execute.run_plan(run, model=run.model)
        return _sse_response(services.stream_in_background(gen, run))


class OrchestratorView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> StreamingHttpResponse:
        ser = OrchestratorRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        cfg = config.get_llm_config()
        run = services.create_orchestrator_run(
            user=request.user,
            query=d["query"],
            model=d.get("model") or "",
            max_workers=d["max_workers"] or cfg.orch_max_workers,
        )
        gen = orchestrator.run_orchestrator(run, model=run.model)
        return _sse_response(services.stream_in_background(gen, run))


class MultiAgentView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> StreamingHttpResponse:
        ser = MultiAgentRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        cfg = config.get_llm_config()
        run = services.create_multiagent_run(
            user=request.user,
            query=d["query"],
            model=d.get("model") or "",
            max_tools=d["max_tools"] or cfg.multiagent_max_tools,
        )
        gen = multiagent.run_multiagent(run, model=run.model)
        return _sse_response(services.stream_in_background(gen, run))


class DagView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> StreamingHttpResponse:
        ser = DagRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        cfg = config.get_llm_config()
        run = services.create_dag_run(
            user=request.user,
            query=d["query"],
            model=d.get("model") or "",
            max_nodes=d["max_nodes"] or cfg.dag_max_nodes,
        )
        gen = dag.run_dag(run, model=run.model)
        return _sse_response(services.stream_in_background(gen, run))


class AutonomousView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> StreamingHttpResponse:
        ser = AutonomousRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        cfg = config.get_llm_config()
        max_subagents = d["max_subagents"]
        if max_subagents is None:
            max_subagents = cfg.auto_max_subagents
        run = services.create_autonomous_run(
            user=request.user,
            query=d["query"],
            model=d.get("model") or "",
            max_cycles=d["max_cycles"] or cfg.auto_max_cycles,
            max_subagents=max_subagents,
        )
        gen = autonomous.run_autonomous(run, model=run.model)
        return _sse_response(services.stream_in_background(gen, run))


class BrowserView(APIView):
    """Start one browser-agent run. Guarded three ways before anything launches: the
    feature flag, a per-user throttle, and the process-wide single-browser slot."""

    permission_classes = (IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "browser"

    def post(self, request: Request) -> StreamingHttpResponse | Response:
        ser = BrowserRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        cfg = config.get_llm_config()
        if not cfg.browser_enabled:
            return Response(
                {
                    "detail": "The browser agent is disabled.",
                    "hint": "Enable it under LLM Settings (browser_enabled) once a Chrome/Chromium "
                    "binary is installed on the server.",
                },
                status=503,
            )
        if not browser.acquire_slot():
            browser.SLOT_REJECTIONS.inc()
            return Response(
                {"detail": "A browser run is already in progress. Try again when it finishes."},
                status=429,
            )

        try:
            run = services.create_browser_run(
                user=request.user,
                query=d["query"],
                model=d.get("model") or "",
                provider=d.get("provider") or cfg.browser_provider,
                max_steps=d["max_steps"] or cfg.browser_max_steps,
                allowed_domains=browser.parse_domains(cfg.browser_allowed_domains),
            )
        except Exception:
            browser.release_slot()
            raise
        gen = browser.run_browser(run, model=run.model)
        return _sse_response(services.stream_in_background(gen, run))


class BrowserScreenshotView(APIView):
    """Serve one step's screenshot. Deliberately not static/media-served: a screenshot can
    show anything the agent browsed, so it is owner-checked on every request."""

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk, order: int):
        if not AgentRun.objects.filter(pk=pk, kind="browser", user=request.user).exists():
            raise NotFound()
        path = browser.screenshot_dir(pk) / f"{int(order)}.png"
        # resolve() both sides: `order` is int-cast above, but never serve outside the root.
        root = Path(settings.BROWSER_SCREENSHOT_ROOT).resolve()
        try:
            resolved = path.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            raise NotFound()
        if not resolved.is_file():
            raise NotFound()
        return FileResponse(resolved.open("rb"), content_type="image/png")


class ParallelView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> StreamingHttpResponse:
        ser = ParallelRequestSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data

        run = services.create_parallel_run(
            user=request.user,
            query=d["query"],
            model=d.get("model") or "",
            strategy=d["strategy"],
            n=d["n"],
        )
        gen = parallel.run_parallel(run, model=run.model)
        return _sse_response(services.stream_in_background(gen, run))


# --- Generic run history views ---------------------------------------------------------
#
# Every workflow's list and detail endpoints differed only by `kind` and `serializer_class`,
# so they are built from `registry.WORKFLOWS` instead of written out. `urls.py` wires them.


class AgentRunListView(ListAPIView):
    """A workflow's run history, newest first, scoped to the requesting user."""

    permission_classes = (IsAuthenticated,)
    kind: str = ""

    def get_queryset(self):
        return AgentRun.objects.filter(kind=self.kind, user=self.request.user).prefetch_related(
            "steps"
        )


class AgentRunDetailView(RetrieveAPIView):
    """One run with its steps. 404s another user's run rather than 403ing, so the
    endpoint does not confirm that an id exists."""

    permission_classes = (IsAuthenticated,)
    kind: str = ""

    def get_object(self):
        try:
            return AgentRun.objects.prefetch_related("steps").get(
                pk=self.kwargs["pk"], kind=self.kind, user=self.request.user
            )
        except AgentRun.DoesNotExist:
            raise NotFound() from None


def run_views(spec) -> tuple[type, type]:
    """The (list, detail) view pair for one workflow spec."""
    name = spec.kind.title().replace("_", "")
    list_view = type(
        f"{name}RunListView",
        (AgentRunListView,),
        {"kind": spec.kind, "serializer_class": spec.run_serializer},
    )
    detail_view = type(
        f"{name}RunDetailView",
        (AgentRunDetailView,),
        {"kind": spec.kind, "serializer_class": spec.run_serializer},
    )
    return list_view, detail_view
