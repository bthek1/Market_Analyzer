from rest_framework import serializers

from .models import (
    AgentRun,
    AgentStep,
    ChatSession,
    LLMSettings,
)


class MetaField(serializers.Field):
    """Read-only field that pulls one key out of an ``AgentRun``/``AgentStep`` ``meta``
    dict, falling back to a default when absent. Lets the per-kind serializers keep their
    legacy JSON field names while the data lives in ``meta`` (model consolidation)."""

    def __init__(self, key=None, default=None, **kwargs):
        self._key = key
        self._default = default
        kwargs["read_only"] = True
        kwargs.setdefault("source", "*")
        super().__init__(**kwargs)

    def bind(self, field_name, parent):
        super().bind(field_name, parent)
        if self._key is None:
            self._key = field_name

    def to_representation(self, obj):
        meta = getattr(obj, "meta", None) or {}
        return meta.get(self._key, self._default)


class LLMSettingsSerializer(serializers.ModelSerializer):
    route_threshold = serializers.FloatField(min_value=0.0, max_value=1.0)
    timeout = serializers.IntegerField(min_value=1, max_value=600)
    num_parallel = serializers.IntegerField(min_value=1, max_value=32)
    # required=False so a full PUT written before this field existed still validates.
    # Lower bound is Ollama's own default, which is the value that truncates silently;
    # upper bound is qwen3:8b's declared 40960, and raising it costs KV-cache VRAM.
    num_ctx = serializers.IntegerField(min_value=4096, max_value=40960, required=False)
    react_max_steps = serializers.IntegerField(min_value=1, max_value=20)
    chat_max_steps = serializers.IntegerField(min_value=1, max_value=10, required=False)
    eval_max_iterations = serializers.IntegerField(min_value=1, max_value=10)
    eval_threshold = serializers.IntegerField(min_value=1, max_value=10)
    plan_max_steps = serializers.IntegerField(min_value=1, max_value=20)
    plan_max_replans = serializers.IntegerField(min_value=0, max_value=10)
    orch_max_workers = serializers.IntegerField(min_value=2, max_value=8)
    multiagent_max_tools = serializers.IntegerField(min_value=1, max_value=10)
    dag_max_nodes = serializers.IntegerField(min_value=2, max_value=12)
    auto_max_cycles = serializers.IntegerField(min_value=1, max_value=20)
    auto_max_subagents = serializers.IntegerField(min_value=0, max_value=6)
    auto_subagent_steps = serializers.IntegerField(min_value=1, max_value=6)
    auto_no_progress = serializers.IntegerField(min_value=1, max_value=10)
    # required=False so a full PUT written before these existed still validates.
    summary_snapshot_max_age_days = serializers.IntegerField(
        min_value=1, max_value=365, required=False
    )
    summary_price_max_age_days = serializers.IntegerField(
        min_value=1, max_value=365, required=False
    )
    summary_financials_max_age_days = serializers.IntegerField(
        min_value=1, max_value=730, required=False
    )
    browser_max_steps = serializers.IntegerField(min_value=1, max_value=40)
    browser_timeout_s = serializers.IntegerField(min_value=30, max_value=1800)

    class Meta:
        model = LLMSettings
        fields = (
            "base_url",
            "main_model",
            "classifier_model",
            "embed_model",
            "timeout",
            "num_parallel",
            "num_ctx",
            "route_mode",
            "route_threshold",
            "react_max_steps",
            "chat_max_steps",
            "eval_max_iterations",
            "eval_threshold",
            "plan_max_steps",
            "plan_max_replans",
            "orch_max_workers",
            "multiagent_max_tools",
            "dag_max_nodes",
            "auto_max_cycles",
            "auto_max_subagents",
            "auto_subagent_steps",
            "auto_no_progress",
            "summary_snapshot_max_age_days",
            "summary_price_max_age_days",
            "summary_financials_max_age_days",
            "browser_enabled",
            "browser_provider",
            "browser_model",
            "browser_max_steps",
            "browser_timeout_s",
            "browser_headless",
            "browser_allowed_domains",
            "updated_at",
        )
        read_only_fields = ("updated_at",)


class MessageSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["user", "assistant", "system"])
    content = serializers.CharField()


class ChatRequestSerializer(serializers.Serializer):
    messages = MessageSerializer(many=True, min_length=1)
    model = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)


class SummariseRequestSerializer(serializers.Serializer):
    text = serializers.CharField()
    model = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)


class AnalyseRequestSerializer(serializers.Serializer):
    text = serializers.CharField()
    context = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    model = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)


class ChainRequestSerializer(serializers.Serializer):
    query = serializers.CharField()
    model = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)


class ChainStepResultSerializer(serializers.ModelSerializer):
    # JSON key stays "step_id" (frontend contract); AgentStep stores it in "key".
    step_id = serializers.CharField(source="key")

    class Meta:
        model = AgentStep
        fields = (
            "id",
            "step_id",
            "label",
            "order",
            "status",
            "output",
            "error",
            "started_at",
            "completed_at",
        )


class ChainRunSerializer(serializers.ModelSerializer):
    steps = ChainStepResultSerializer(many=True, read_only=True)

    class Meta:
        model = AgentRun
        fields = (
            "id",
            "query",
            "model",
            "status",
            "created_at",
            "completed_at",
            "steps",
        )


class RouteRequestSerializer(serializers.Serializer):
    query = serializers.CharField()
    model = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)


class RouteRunSerializer(serializers.ModelSerializer):
    # JSON key stays "chain_run" (frontend contract); AgentRun stores it as "parent".
    chain_run = serializers.PrimaryKeyRelatedField(read_only=True, source="parent")
    route = MetaField(default="")
    route_reason = MetaField(default="")
    route_method = MetaField(default="")
    route_confidence = MetaField(default=None)

    class Meta:
        model = AgentRun
        fields = (
            "id",
            "query",
            "model",
            "route",
            "route_reason",
            "route_method",
            "route_confidence",
            "status",
            "output",
            "error",
            "chain_run",
            "created_at",
            "completed_at",
        )


class ReactRequestSerializer(serializers.Serializer):
    query = serializers.CharField()
    model = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    # Omitted -> the LLMSettings singleton supplies the default (resolved in the view).
    max_steps = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=1, max_value=20
    )


class ReactStepSerializer(serializers.ModelSerializer):
    thought = MetaField(default="")
    tool = MetaField(default="")
    tool_args = MetaField(default=None)
    observation = MetaField(default="")
    is_answer = MetaField(default=False)

    class Meta:
        model = AgentStep
        fields = (
            "id",
            "order",
            "thought",
            "tool",
            "tool_args",
            "observation",
            "is_answer",
            "status",
            "error",
            "created_at",
        )


class ReactRunSerializer(serializers.ModelSerializer):
    max_steps = MetaField(default=None)
    steps = ReactStepSerializer(many=True, read_only=True)

    class Meta:
        model = AgentRun
        fields = (
            "id",
            "query",
            "model",
            "max_steps",
            "status",
            "output",
            "error",
            "created_at",
            "completed_at",
            "steps",
        )


class ChatAgentRequestSerializer(serializers.Serializer):
    """One conversational turn. ``ChatRequestSerializer`` above belongs to the OLD
    ``/api/llm/chat/`` path, which takes a client-held message list; this one takes a single
    message, because the harness path owns the transcript itself."""

    message = serializers.CharField()
    # `allow_null` on all three, not just `required=False, default=None`. Those two let the
    # key be OMITTED; they do not let it be sent as null, and DRF rejects an explicit null
    # with "This field may not be null." The client sends `session: null` for the first
    # message of a new conversation - which is exactly what `ChatTurnRequest` declares - so
    # without this EVERY first message 400s. Backend tests posted `{"message": ...}` and
    # frontend tests mocked `fetch`, so nothing exercised the real payload.
    #: Null or omitted -> a new session is created for this turn.
    session = serializers.UUIDField(required=False, allow_null=True, default=None)
    model = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    #: Null or omitted -> the LLMSettings singleton supplies the default (view resolves it).
    max_steps = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=1, max_value=10
    )


class ChatSessionSerializer(serializers.ModelSerializer):
    """A conversation in the sidebar. ``turn_count`` and ``last_message_at`` save the client
    from fetching every turn just to render a list row."""

    # Method fields, not plain IntegerField/DateTimeField: the values are ANNOTATIONS on the
    # list queryset, and a freshly created instance carries neither - so a POST response
    # would omit the very fields every list row has, and the client would render a row with
    # holes in it. Annotated instances stay free; only the bare ones pay a query.
    turn_count = serializers.SerializerMethodField()
    last_message_at = serializers.SerializerMethodField()

    def get_turn_count(self, obj) -> int:
        annotated = getattr(obj, "turn_count", None)
        return annotated if annotated is not None else obj.turns.count()

    def get_last_message_at(self, obj):
        if hasattr(obj, "last_message_at"):
            return obj.last_message_at
        last = obj.turns.order_by("-created_at").first()
        return last.created_at if last else None

    class Meta:
        model = ChatSession
        fields = (
            "id",
            "title",
            "archived",
            "turn_count",
            "last_message_at",
            "created_at",
            "updated_at",
        )
        # Renaming and archiving are the only writes; the rest is server state.
        read_only_fields = ("id", "created_at", "updated_at")


class ChatSessionDetailSerializer(ChatSessionSerializer):
    """One conversation with its full transcript, oldest turn first."""

    turns = serializers.SerializerMethodField()

    class Meta(ChatSessionSerializer.Meta):
        fields = (*ChatSessionSerializer.Meta.fields, "summary", "summarised_upto", "turns")

    def get_turns(self, obj):
        # Ordered here rather than relying on the model's Meta ordering: AgentRun orders
        # NEWEST first, which is right for a history list and backwards for a transcript.
        turns = sorted(obj.turns.all(), key=lambda r: r.created_at)
        return ChatRunSerializer(turns, many=True).data


class ChatStepSerializer(serializers.ModelSerializer):
    """One tool call within a turn. Same shape as a ReAct step - a chat step IS a ReAct
    step - but declared separately so the two kinds can diverge without a shared edit."""

    thought = MetaField(default="")
    tool = MetaField(default="")
    tool_args = MetaField(default=None)
    observation = MetaField(default="")
    is_answer = MetaField(default=False)

    class Meta:
        model = AgentStep
        fields = (
            "id",
            "order",
            "thought",
            "tool",
            "tool_args",
            "observation",
            "is_answer",
            "status",
            "error",
            "created_at",
        )


class ChatRunSerializer(serializers.ModelSerializer):
    """One turn. ``query`` is the user message and ``output`` the assistant reply, so a
    conversation is just an ordered list of these."""

    max_steps = MetaField(default=None)
    turn = MetaField(default=0)
    tools_used = MetaField(default=None)
    compacted = MetaField(default=0)
    steps = ChatStepSerializer(many=True, read_only=True)

    class Meta:
        model = AgentRun
        fields = (
            "id",
            "query",
            "model",
            "max_steps",
            "turn",
            "tools_used",
            "compacted",
            "status",
            "output",
            "error",
            "created_at",
            "completed_at",
            "steps",
        )


class EvalOptRequestSerializer(serializers.Serializer):
    query = serializers.CharField()
    model = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    # Omitted -> the LLMSettings singleton supplies the defaults (resolved in the view).
    max_iterations = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=1, max_value=10
    )
    threshold = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=1, max_value=10
    )


class EvalOptIterationSerializer(serializers.ModelSerializer):
    draft = MetaField(default="")
    score = MetaField(default=None)
    feedback = MetaField(default="")
    passed = MetaField(default=False)

    class Meta:
        model = AgentStep
        fields = (
            "id",
            "order",
            "draft",
            "score",
            "feedback",
            "passed",
            "status",
            "error",
            "created_at",
        )


class EvalOptRunSerializer(serializers.ModelSerializer):
    # JSON key stays "iterations" (frontend contract); AgentRun stores them as "steps".
    iterations = EvalOptIterationSerializer(many=True, read_only=True, source="steps")
    max_iterations = MetaField(default=None)
    threshold = MetaField(default=None)
    best_score = MetaField(default=None)

    class Meta:
        model = AgentRun
        fields = (
            "id",
            "query",
            "model",
            "max_iterations",
            "threshold",
            "status",
            "output",
            "best_score",
            "error",
            "created_at",
            "completed_at",
            "iterations",
        )


class PlanRequestSerializer(serializers.Serializer):
    query = serializers.CharField()
    model = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    # Omitted -> the LLMSettings singleton supplies the default (resolved in the view).
    max_steps = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=1, max_value=20
    )
    allow_replan = serializers.BooleanField(default=True)


class PlanExecStepSerializer(serializers.ModelSerializer):
    task = MetaField(default="")
    tool = MetaField(default="")
    tool_args = MetaField(default=None)
    observation = MetaField(default="")
    result = MetaField(default="")

    class Meta:
        model = AgentStep
        fields = (
            "id",
            "order",
            "task",
            "tool",
            "tool_args",
            "observation",
            "result",
            "status",
            "error",
            "created_at",
        )


class PlanExecRunSerializer(serializers.ModelSerializer):
    steps = PlanExecStepSerializer(many=True, read_only=True)
    max_steps = MetaField(default=None)
    allow_replan = MetaField(default=None)
    plan = MetaField(default=None)
    replans = MetaField(default=0)

    class Meta:
        model = AgentRun
        fields = (
            "id",
            "query",
            "model",
            "max_steps",
            "allow_replan",
            "plan",
            "replans",
            "status",
            "output",
            "error",
            "created_at",
            "completed_at",
            "steps",
        )


class ParallelRequestSerializer(serializers.Serializer):
    query = serializers.CharField()
    model = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    strategy = serializers.ChoiceField(
        choices=AgentRun.Strategy.values, default=AgentRun.Strategy.SECTIONING
    )
    n = serializers.IntegerField(default=3, min_value=2, max_value=5)


class ParallelTaskResultSerializer(serializers.ModelSerializer):
    # JSON key stays "task_id" (frontend contract); AgentStep stores it in "key".
    task_id = serializers.CharField(source="key")
    vote = MetaField(default="")

    class Meta:
        model = AgentStep
        fields = (
            "id",
            "task_id",
            "label",
            "order",
            "status",
            "output",
            "vote",
            "error",
            "started_at",
            "completed_at",
        )


class ParallelRunSerializer(serializers.ModelSerializer):
    # JSON key stays "tasks" (frontend contract); AgentRun stores them as "steps".
    tasks = ParallelTaskResultSerializer(many=True, read_only=True, source="steps")
    strategy = MetaField(default="sectioning")
    n = MetaField(default=None)
    tally = MetaField(default=None)

    class Meta:
        model = AgentRun
        fields = (
            "id",
            "query",
            "model",
            "strategy",
            "n",
            "status",
            "output",
            "tally",
            "error",
            "created_at",
            "completed_at",
            "tasks",
        )


class OrchestratorRequestSerializer(serializers.Serializer):
    query = serializers.CharField()
    model = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    # Omitted -> the LLMSettings singleton supplies the default (resolved in the view).
    max_workers = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=2, max_value=8
    )


class OrchestratorWorkerSerializer(serializers.ModelSerializer):
    # JSON key stays "worker_id" (frontend contract); AgentStep stores it in "key".
    worker_id = serializers.CharField(source="key")
    task = MetaField(default="")
    tool = MetaField(default="")
    tool_args = MetaField(default=None)
    observation = MetaField(default="")

    class Meta:
        model = AgentStep
        fields = (
            "id",
            "worker_id",
            "label",
            "task",
            "order",
            "tool",
            "tool_args",
            "observation",
            "output",
            "status",
            "error",
            "started_at",
            "completed_at",
        )


class OrchestratorRunSerializer(serializers.ModelSerializer):
    # JSON key stays "workers" (frontend contract); AgentRun stores them as "steps".
    workers = OrchestratorWorkerSerializer(many=True, read_only=True, source="steps")
    max_workers = MetaField(default=None)
    plan = MetaField(default=None)

    class Meta:
        model = AgentRun
        fields = (
            "id",
            "query",
            "model",
            "max_workers",
            "plan",
            "status",
            "output",
            "error",
            "created_at",
            "completed_at",
            "workers",
        )


class MultiAgentRequestSerializer(serializers.Serializer):
    query = serializers.CharField()
    model = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    # Omitted -> the LLMSettings singleton supplies the default (resolved in the view).
    max_tools = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=1, max_value=10
    )


class MultiAgentStepSerializer(serializers.ModelSerializer):
    # JSON key stays "agent_id" (frontend contract); AgentStep stores it in "key".
    agent_id = serializers.CharField(source="key")
    input = MetaField(default="")
    tool_calls = MetaField(default=None)

    class Meta:
        model = AgentStep
        fields = (
            "id",
            "agent_id",
            "label",
            "order",
            "input",
            "tool_calls",
            "output",
            "status",
            "error",
            "started_at",
            "completed_at",
        )


class MultiAgentRunSerializer(serializers.ModelSerializer):
    steps = MultiAgentStepSerializer(many=True, read_only=True)
    max_tools = MetaField(default=None)
    agents = MetaField(default=None)
    route_reason = MetaField(default="")

    class Meta:
        model = AgentRun
        fields = (
            "id",
            "query",
            "model",
            "max_tools",
            "agents",
            "route_reason",
            "status",
            "output",
            "error",
            "created_at",
            "completed_at",
            "steps",
        )


class DagRequestSerializer(serializers.Serializer):
    query = serializers.CharField()
    model = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    # Omitted -> the LLMSettings singleton supplies the default (resolved in the view).
    max_nodes = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=2, max_value=12
    )


class DagNodeSerializer(serializers.ModelSerializer):
    # JSON key stays "node_id" (frontend contract); AgentStep stores it in "key".
    node_id = serializers.CharField(source="key")
    task = MetaField(default="")
    wave = MetaField(default=None)
    depends_on = MetaField(default=[])
    tool = MetaField(default="")
    tool_args = MetaField(default=None)
    observation = MetaField(default="")

    class Meta:
        model = AgentStep
        fields = (
            "id",
            "node_id",
            "label",
            "task",
            "wave",
            "order",
            "depends_on",
            "tool",
            "tool_args",
            "observation",
            "output",
            "status",
            "error",
            "started_at",
            "completed_at",
        )


class DagRunSerializer(serializers.ModelSerializer):
    # JSON key stays "nodes" (frontend contract); AgentRun stores them as "steps".
    nodes = DagNodeSerializer(many=True, read_only=True, source="steps")
    max_nodes = MetaField(default=None)
    plan = MetaField(default=None)

    class Meta:
        model = AgentRun
        fields = (
            "id",
            "query",
            "model",
            "max_nodes",
            "plan",
            "status",
            "output",
            "error",
            "created_at",
            "completed_at",
            "nodes",
        )


class AutonomousRequestSerializer(serializers.Serializer):
    query = serializers.CharField()
    model = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    # Omitted -> the LLMSettings singleton supplies the default (resolved in the view).
    max_cycles = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=1, max_value=20
    )
    max_subagents = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=0, max_value=6
    )


class AutonomousCycleSerializer(serializers.ModelSerializer):
    # JSON key stays "index" (frontend contract); AgentStep stores it in "order".
    index = serializers.IntegerField(source="order")
    reflection = MetaField(default="")
    task = MetaField(default="")
    action = MetaField(default="reason")
    tool = MetaField(default="")
    tool_args = MetaField(default=None)
    observation = MetaField(default="")
    spawned = MetaField(default=False)
    subagent_steps = MetaField(default=None)
    backlog = MetaField(default=None)
    goal_complete = MetaField(default=False)

    class Meta:
        model = AgentStep
        fields = (
            "id",
            "index",
            "reflection",
            "task",
            "action",
            "tool",
            "tool_args",
            "observation",
            "spawned",
            "subagent_steps",
            "output",
            "backlog",
            "goal_complete",
            "status",
            "error",
            "started_at",
            "completed_at",
        )


class AutonomousRunSerializer(serializers.ModelSerializer):
    # JSON key stays "cycles" (frontend contract); AgentRun stores them as "steps".
    cycles = AutonomousCycleSerializer(many=True, read_only=True, source="steps")
    max_cycles = MetaField(default=None)
    max_subagents = MetaField(default=None)
    goal = MetaField(default="")
    backlog = MetaField(default=None)
    stop_reason = MetaField(default="")

    class Meta:
        model = AgentRun
        fields = (
            "id",
            "query",
            "model",
            "max_cycles",
            "max_subagents",
            "goal",
            "backlog",
            "stop_reason",
            "status",
            "output",
            "error",
            "created_at",
            "completed_at",
            "cycles",
        )


class BrowserRequestSerializer(serializers.Serializer):
    query = serializers.CharField()
    # Selects the browser LLM provider, not an Ollama model name (unlike every other
    # workflow's `model`, which overrides the MAIN Ollama model).
    provider = serializers.ChoiceField(
        choices=LLMSettings.BrowserProvider.choices,
        required=False,
        allow_null=True,
        default=None,
    )
    model = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    max_steps = serializers.IntegerField(
        required=False, allow_null=True, default=None, min_value=1, max_value=40
    )


class BrowserStepSerializer(serializers.ModelSerializer):
    action = MetaField(default="")
    action_args = MetaField(default=None)
    url = MetaField(default="")
    title = MetaField(default="")
    evaluation = MetaField(default="")
    memory = MetaField(default="")
    screenshot = MetaField(default="")

    class Meta:
        model = AgentStep
        fields = (
            "id",
            "order",
            "action",
            "action_args",
            "url",
            "title",
            "evaluation",
            "memory",
            "screenshot",
            "output",
            "status",
            "error",
            "created_at",
        )


class BrowserRunSerializer(serializers.ModelSerializer):
    provider = MetaField(default="")
    max_steps = MetaField(default=None)
    allowed_domains = MetaField(default=[])
    urls_visited = MetaField(default=[])
    stop_reason = MetaField(default="")
    duration_s = MetaField(default=None)
    steps = BrowserStepSerializer(many=True, read_only=True)

    class Meta:
        model = AgentRun
        fields = (
            "id",
            "query",
            "model",
            "provider",
            "max_steps",
            "allowed_domains",
            "urls_visited",
            "stop_reason",
            "duration_s",
            "status",
            "output",
            "error",
            "created_at",
            "completed_at",
            "steps",
        )


# ---------------------------------------------------------------------------
# Unified AgentRun / AgentStep serializers (model consolidation).
#
# Each workflow is migrated to AgentRun/AgentStep one phase at a time. Per-kind
# serializers subclass these and project Meta.fields (with source= aliases) so the
# emitted JSON is byte-for-byte identical to the legacy per-workflow serializers.
# These base classes expose the full column union and are not wired to any view
# directly; the per-kind subclasses (added per phase) are.
# ---------------------------------------------------------------------------


class AgentStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentStep
        fields = (
            "id",
            "order",
            "status",
            "error",
            "created_at",
            "started_at",
            "completed_at",
            "key",
            "label",
            "thought",
            "tool",
            "tool_args",
            "observation",
            "output",
            "result",
            "is_answer",
            "draft",
            "score",
            "feedback",
            "passed",
            "vote",
            "task",
            "input",
            "tool_calls",
            "depends_on",
            "wave",
            "action",
            "spawned",
            "subagent_steps",
            "reflection",
            "backlog",
            "goal_complete",
        )


class AgentRunSerializer(serializers.ModelSerializer):
    steps = AgentStepSerializer(many=True, read_only=True)

    class Meta:
        model = AgentRun
        fields = (
            "id",
            "kind",
            "query",
            "model",
            "status",
            "output",
            "error",
            "created_at",
            "completed_at",
            "max_steps",
            "max_iterations",
            "threshold",
            "max_workers",
            "max_tools",
            "max_nodes",
            "max_cycles",
            "max_subagents",
            "allow_replan",
            "strategy",
            "n",
            "plan",
            "tally",
            "best_score",
            "replans",
            "agents",
            "route",
            "route_reason",
            "route_method",
            "route_confidence",
            "goal",
            "backlog",
            "stop_reason",
            "parent",
            "steps",
        )


# --- Per-kind step serialisation ------------------------------------------------------------

# The ONE mapping from a run kind to how its child steps are represented in JSON. Both
# consumers go through it: the detail endpoints (via the per-kind run serializers above)
# and the live SSE step events (via ``_events.step_event``). They used to be written
# independently, which is how ``dag`` came to stream ``id``/``args`` while its detail
# endpoint returned ``node_id``/``tool_args`` - the same row, two shapes, and the field
# silently vanished from the UI on a refresh-restore.
STEP_SERIALIZERS = {
    "chain": ChainStepResultSerializer,
    "parallel": ParallelTaskResultSerializer,
    "react": ReactStepSerializer,
    "eval_opt": EvalOptIterationSerializer,
    "plan_exec": PlanExecStepSerializer,
    "orchestrator": OrchestratorWorkerSerializer,
    "multiagent": MultiAgentStepSerializer,
    "dag": DagNodeSerializer,
    "autonomous": AutonomousCycleSerializer,
    "browser": BrowserStepSerializer,
    "chat": ChatStepSerializer,
}


def step_serializer_for(kind: str) -> type[serializers.ModelSerializer]:
    """The step serializer for a run ``kind``. Raises KeyError on an unregistered kind -
    a new workflow must declare how its steps are represented, not fall back to a guess."""
    return STEP_SERIALIZERS[kind]
