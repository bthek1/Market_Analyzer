from django.urls import path

from .registry import WORKFLOWS
from .views import (
    AnalyseView,
    AutonomousView,
    BrowserScreenshotView,
    BrowserView,
    ChatAgentView,
    ChatSessionDetailView,
    ChatSessionListView,
    ChatView,
    DagView,
    EvaluatorOptimizerView,
    LLMSettingsView,
    ModelsView,
    MultiAgentView,
    OrchestratorView,
    ParallelView,
    PlanExecuteView,
    PromptChainView,
    ReactView,
    RouteView,
    StopRunView,
    SummariseView,
    run_views,
)

urlpatterns = [
    path("chat/", ChatView.as_view(), name="llm-chat"),
    path("summarise/", SummariseView.as_view(), name="llm-summarise"),
    path("analyse/", AnalyseView.as_view(), name="llm-analyse"),
    path("models/", ModelsView.as_view(), name="llm-models"),
    path("settings/", LLMSettingsView.as_view(), name="llm-settings"),
    path("runs/stop/", StopRunView.as_view(), name="llm-run-stop"),
    path("chain/run/", PromptChainView.as_view(), name="llm-chain-run"),
    path("route/", RouteView.as_view(), name="llm-route"),
    path("parallel/", ParallelView.as_view(), name="llm-parallel"),
    path("react/", ReactView.as_view(), name="llm-react"),
    path("chat-agent/", ChatAgentView.as_view(), name="llm-chat-agent"),
    path("chat/sessions/", ChatSessionListView.as_view(), name="llm-chat-session-list"),
    path(
        "chat/sessions/<uuid:pk>/",
        ChatSessionDetailView.as_view(),
        name="llm-chat-session-detail",
    ),
    path("evaluate/", EvaluatorOptimizerView.as_view(), name="llm-evaluate"),
    path("plan/", PlanExecuteView.as_view(), name="llm-plan"),
    path("orchestrate/", OrchestratorView.as_view(), name="llm-orchestrate"),
    path("multiagent/", MultiAgentView.as_view(), name="llm-multiagent"),
    path("dag/", DagView.as_view(), name="llm-dag"),
    path("autonomous/", AutonomousView.as_view(), name="llm-autonomous"),
    path("browser/", BrowserView.as_view(), name="llm-browser"),
    path(
        "browser/<uuid:pk>/screenshot/<int:order>/",
        BrowserScreenshotView.as_view(),
        name="llm-browser-screenshot",
    ),
]

# History + detail for every workflow, built from the registry rather than written out.
# A twelfth workflow gets its routes by adding ONE registry entry.
for _spec in WORKFLOWS:
    _list_view, _detail_view = run_views(_spec)
    urlpatterns += [
        path(_spec.list_path, _list_view.as_view(), name=_spec.list_name),
        path(_spec.detail_path, _detail_view.as_view(), name=_spec.detail_name),
    ]
