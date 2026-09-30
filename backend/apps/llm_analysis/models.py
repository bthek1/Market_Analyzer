import uuid

from django.contrib.auth import get_user_model
from django.db import models
from solo.models import SingletonModel

"""
Example queries:
- "Analyse Apple's revenue growth over the last 5 years"
- "Compare MSFT vs GOOG on profitability and valuation"
- "What is Tesla's current debt situation and can it service it?"
- "Which S&P 500 energy stocks have the highest FCF yield?"
- "Summarise NVIDIA's latest quarterly earnings and outlook"
"""


class ChatSession(models.Model):
    """One continuous conversation - the Claude-UI sense of a session (issue #8 phase 2).

    A session GROUPS turns; each turn is an ``AgentRun(kind="chat")`` whose ``query`` is the
    user message and ``output`` the assistant reply. So the transcript IS the ordered run
    list and there is no separate Message model to keep in sync with it.

    This is deliberately a model rather than an ``AgentRun.parent`` chain. ``parent`` could
    thread turns together, but a session is a product object: it needs a renameable title, a
    cheap "list my conversations by recency", one delete that takes the whole thread, and
    somewhere to hang the compaction summary. Walking ``parent`` backwards gives none of
    those without an N-query traversal per sidebar row. ``parent`` stays what it is (route ->
    the chain run it spawned); ``session`` is the conversation grouping.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        related_name="chat_sessions",
    )
    # Blank until the title task lands (or forever, if it fails - the UI falls back to the
    # first message). Never blocks a turn.
    title = models.CharField(max_length=200, blank=True)

    # --- compaction (written from phase 3; see docs/project_docs/chat-agent.md) ---
    #: A rolling summary of every turn up to ``summarised_upto``, so a long session stays
    #: inside the Scratchpad budget instead of silently shedding its own history.
    summary = models.TextField(blank=True)
    #: Turns with ``meta["turn"] <`` this are represented by ``summary``; the rest go in
    #: verbatim. Never regresses.
    summarised_upto = models.PositiveIntegerField(default=0)

    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    # Bumped on every new turn - this is the sidebar's ordering, not created_at.
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        indexes = (models.Index(fields=["user", "-updated_at"]),)

    def __str__(self):
        return f"ChatSession({self.id}, {self.title or 'untitled'})"


class AgentRun(models.Model):
    """Unified run row for every llm_analysis workflow.

    Replaces the per-workflow ``*Run`` models (ChainRun, RouteRun, ParallelRun,
    ReactRun, EvalOptRun, PlanExecRun, OrchestratorRun, MultiAgentRun, DagRun,
    AutonomousRun). The workflow is selected by ``kind``; each kind only sets the
    config/result columns relevant to it (the rest stay null). The shared spine
    (user/query/model/status/output/error/timestamps) is identical for every kind.

    ``status`` keeps the ``running | done | error`` choices; ``stopped`` is still
    written verbatim by ``services.request_run_stop`` / ``stream_in_background``
    (intentionally not a choice, so there is no DB-level constraint to migrate).
    """

    class Kind(models.TextChoices):
        CHAIN = "chain", "Prompt Chain"
        ROUTE = "route", "Routing"
        PARALLEL = "parallel", "Parallelization"
        REACT = "react", "ReAct"
        EVAL_OPT = "eval_opt", "Evaluator-Optimizer"
        PLAN_EXEC = "plan_exec", "Plan-and-Execute"
        ORCHESTRATOR = "orchestrator", "Orchestrator-Workers"
        MULTIAGENT = "multiagent", "Multi-Agent (Sequential)"
        DAG = "dag", "Multi-Agent (Parallel/DAG)"
        AUTONOMOUS = "autonomous", "Autonomous"
        BROWSER = "browser", "Browser (web)"
        CHAT = "chat", "Chat"

    class Status(models.TextChoices):
        RUNNING = "running"
        DONE = "done"
        ERROR = "error"

    class Strategy(models.TextChoices):
        SECTIONING = "sectioning", "Sectioning"
        VOTING = "voting", "Voting"

    # --- discriminator ---
    kind = models.CharField(max_length=20, choices=Kind.choices, db_index=True)

    # --- shared spine ---
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        related_name="agent_runs",
    )
    query = models.TextField()
    # Overrides the MAIN model only (synthesis/analysis/format). Classification always
    # runs on the configured classifier model regardless of this value. Blank = default.
    model = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    output = models.TextField(blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # --- workflow-specific fields, validated per kind by meta_spec.py and written
    #     only through store.py (see the meta_json refactor plan) ---
    meta = models.JSONField(default=dict, blank=True)

    # Replaces RouteRun.chain_run: a route run points at the chain run it spawned.
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )

    # The conversation this run is a TURN of. Null for every kind but "chat". CASCADE
    # because deleting a conversation must take its turns with it - a turn outliving its
    # session is an orphan nothing can render.
    session = models.ForeignKey(
        ChatSession,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="turns",
    )

    class Meta:
        ordering = ("-created_at",)
        indexes = (models.Index(fields=["session", "created_at"]),)

    def __str__(self):
        return f"AgentRun({self.kind}, {self.id}, {self.status})"


class AgentStep(models.Model):
    """Unified child row for every llm_analysis workflow.

    Replaces ChainStepResult, ParallelTaskResult, ReactStep, EvalOptIteration,
    PlanExecStep, OrchestratorWorker, MultiAgentStep, DagNode, AutonomousCycle. The
    per-workflow ``*_id`` columns collapse into ``key``; the remaining payload columns
    are nullable/blank and only filled by the kinds that use them.
    """

    class Status(models.TextChoices):
        PENDING = "pending"
        RUNNING = "running"
        DONE = "done"
        ERROR = "error"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name="steps")
    order = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # identity / labels (step_id | task_id | worker_id | node_id | agent_id)
    key = models.CharField(max_length=50, blank=True)
    label = models.CharField(max_length=100, blank=True)
    # Nearly every kind writes a step output; kept on the spine.
    output = models.TextField(blank=True)

    # --- workflow-specific fields, validated per kind by meta_spec.py and written
    #     only through store.py (see the meta_json refactor plan) ---
    meta = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("order",)
        unique_together = (("run", "order"),)

    def __str__(self):
        return f"AgentStep({self.run_id}, {self.order}, {self.status})"


# The OLLAMA_* settings (themselves env-backed) seed the singleton's defaults, so a
# fresh row mirrors whatever .env the environment was deployed with. Once the row
# exists it is the source of truth (editable via the UI / admin) and these are ignored.
def _default_base_url():
    from django.conf import settings

    return settings.OLLAMA_BASE_URL


def _default_main_model():
    from django.conf import settings

    return settings.OLLAMA_MAIN_MODEL


def _default_classifier_model():
    from django.conf import settings

    return settings.OLLAMA_CLASSIFIER_MODEL


def _default_embed_model():
    from django.conf import settings

    return settings.OLLAMA_EMBED_MODEL


def _default_timeout():
    from django.conf import settings

    return settings.OLLAMA_TIMEOUT


def _default_num_parallel():
    from django.conf import settings

    return settings.OLLAMA_NUM_PARALLEL


def _default_num_ctx():
    from django.conf import settings

    return settings.OLLAMA_NUM_CTX


def _default_route_mode():
    from django.conf import settings

    return settings.OLLAMA_ROUTE_MODE


def _default_route_threshold():
    from django.conf import settings

    return settings.OLLAMA_ROUTE_THRESHOLD


def _default_react_max_steps():
    from django.conf import settings

    return settings.OLLAMA_REACT_MAX_STEPS


def _default_chat_max_steps():
    from django.conf import settings

    return settings.OLLAMA_CHAT_MAX_STEPS


def _default_eval_max_iterations():
    from django.conf import settings

    return settings.OLLAMA_EVAL_MAX_ITERATIONS


def _default_eval_threshold():
    from django.conf import settings

    return settings.OLLAMA_EVAL_THRESHOLD


def _default_plan_max_steps():
    from django.conf import settings

    return settings.OLLAMA_PLAN_MAX_STEPS


def _default_plan_max_replans():
    from django.conf import settings

    return settings.OLLAMA_PLAN_MAX_REPLANS


def _default_orch_max_workers():
    from django.conf import settings

    return settings.OLLAMA_ORCH_MAX_WORKERS


def _default_multiagent_max_tools():
    from django.conf import settings

    return settings.OLLAMA_MULTIAGENT_MAX_TOOLS


def _default_dag_max_nodes():
    from django.conf import settings

    return settings.OLLAMA_DAG_MAX_NODES


def _default_auto_max_cycles():
    from django.conf import settings

    return settings.OLLAMA_AUTO_MAX_CYCLES


def _default_auto_max_subagents():
    from django.conf import settings

    return settings.OLLAMA_AUTO_MAX_SUBAGENTS


def _default_auto_subagent_steps():
    from django.conf import settings

    return settings.OLLAMA_AUTO_SUBAGENT_STEPS


def _default_auto_no_progress():
    from django.conf import settings

    return settings.OLLAMA_AUTO_NO_PROGRESS


def _default_summary_snapshot_max_age():
    from django.conf import settings

    return settings.SUMMARY_SNAPSHOT_MAX_AGE_DAYS


def _default_summary_price_max_age():
    from django.conf import settings

    return settings.SUMMARY_PRICE_MAX_AGE_DAYS


def _default_summary_financials_max_age():
    from django.conf import settings

    return settings.SUMMARY_FINANCIALS_MAX_AGE_DAYS


def _default_browser_enabled():
    from django.conf import settings

    return settings.BROWSER_ENABLED


def _default_browser_provider():
    from django.conf import settings

    return settings.BROWSER_PROVIDER


def _default_browser_model():
    from django.conf import settings

    return settings.BROWSER_MODEL


def _default_browser_max_steps():
    from django.conf import settings

    return settings.BROWSER_MAX_STEPS


def _default_browser_timeout():
    from django.conf import settings

    return settings.BROWSER_TIMEOUT_S


def _default_browser_headless():
    from django.conf import settings

    return settings.BROWSER_HEADLESS


def _default_browser_allowed_domains():
    from django.conf import settings

    return settings.BROWSER_ALLOWED_DOMAINS


class LLMSettings(SingletonModel):
    """Runtime-editable Ollama/LLM configuration (single row, via django-solo).

    The OLLAMA_* env vars only seed the field defaults (see the helpers above); once
    this row exists it is the source of truth and is editable from the UI / admin.
    """

    base_url = models.CharField(max_length=255, default=_default_base_url)
    main_model = models.CharField(max_length=100, default=_default_main_model)
    classifier_model = models.CharField(max_length=100, default=_default_classifier_model)
    embed_model = models.CharField(max_length=100, default=_default_embed_model)
    timeout = models.PositiveIntegerField(default=_default_timeout)
    num_parallel = models.PositiveIntegerField(default=_default_num_parallel)
    num_ctx = models.PositiveIntegerField(default=_default_num_ctx)

    class RouteMode(models.TextChoices):
        LLM = "llm"
        SEMANTIC = "semantic"

    route_mode = models.CharField(
        max_length=10, choices=RouteMode.choices, default=_default_route_mode
    )
    route_threshold = models.FloatField(default=_default_route_threshold)
    react_max_steps = models.PositiveIntegerField(default=_default_react_max_steps)
    chat_max_steps = models.PositiveIntegerField(default=_default_chat_max_steps)
    eval_max_iterations = models.PositiveIntegerField(default=_default_eval_max_iterations)
    eval_threshold = models.PositiveIntegerField(default=_default_eval_threshold)
    plan_max_steps = models.PositiveIntegerField(default=_default_plan_max_steps)
    plan_max_replans = models.PositiveIntegerField(default=_default_plan_max_replans)
    orch_max_workers = models.PositiveIntegerField(default=_default_orch_max_workers)
    multiagent_max_tools = models.PositiveIntegerField(default=_default_multiagent_max_tools)
    dag_max_nodes = models.PositiveIntegerField(default=_default_dag_max_nodes)
    auto_max_cycles = models.PositiveIntegerField(default=_default_auto_max_cycles)
    auto_max_subagents = models.PositiveIntegerField(default=_default_auto_max_subagents)
    auto_subagent_steps = models.PositiveIntegerField(default=_default_auto_subagent_steps)
    auto_no_progress = models.PositiveIntegerField(default=_default_auto_no_progress)

    # AI company summary freshness windows (days). Data older than these means the summary
    # returns insufficient_data without calling the LLM at all.
    summary_snapshot_max_age_days = models.PositiveIntegerField(
        default=_default_summary_snapshot_max_age
    )
    summary_price_max_age_days = models.PositiveIntegerField(default=_default_summary_price_max_age)
    summary_financials_max_age_days = models.PositiveIntegerField(
        default=_default_summary_financials_max_age
    )

    class BrowserProvider(models.TextChoices):
        ANTHROPIC = "anthropic"
        OLLAMA = "ollama"

    # Browser agent. Off by default: it is the only agent that leaves our network.
    browser_enabled = models.BooleanField(default=_default_browser_enabled)
    browser_provider = models.CharField(
        max_length=20, choices=BrowserProvider.choices, default=_default_browser_provider
    )
    browser_model = models.CharField(max_length=100, default=_default_browser_model)
    browser_max_steps = models.PositiveIntegerField(default=_default_browser_max_steps)
    browser_timeout_s = models.PositiveIntegerField(default=_default_browser_timeout)
    browser_headless = models.BooleanField(default=_default_browser_headless)
    # Newline/comma-separated hosts (glob patterns allowed). Blank = no restriction.
    browser_allowed_domains = models.TextField(blank=True, default=_default_browser_allowed_domains)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "LLM settings"

    def __str__(self):
        return "LLM settings"
