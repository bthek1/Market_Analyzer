from datetime import timedelta
from pathlib import Path

import environ

from core.env import resolve_env_file

BASE_DIR = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = BASE_DIR.parent

env = environ.Env(SECRET_KEY=(str, "django-insecure-change-me-in-production"))
# One .env at the repo root, shared with the frontend, compose and systemd.
ENV_FILE = resolve_env_file(REPO_ROOT)
if ENV_FILE is not None:
    environ.Env.read_env(ENV_FILE)

SECRET_KEY = env("SECRET_KEY")

DEBUG = False

ALLOWED_HOSTS = []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.contrib.postgres",
    "rest_framework",
    "rest_framework.authtoken",
    "rest_framework_simplejwt",
    "corsheaders",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "dj_rest_auth",
    "dj_rest_auth.registration",
    "django_celery_results",
    "django_celery_beat",
    "django_filters",
    "django_prometheus",
    "solo",
    "apps.accounts",
    "apps.companies",
    "apps.tasks",
    "apps.redis_monitor",
    "apps.llm_analysis",
    "apps.knowledge_graph",
    "apps.codegraph",
]

MIDDLEWARE = [
    # django-prometheus measures the whole chain, so its two halves must be the OUTERMOST
    # entries - Before first, After last. Anything placed outside them is not counted in
    # the request latency they report.
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    # Then the correlation id, so every log line produced during the request carries it,
    # including lines from the middleware below.
    "core.middleware.RequestIDMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "core.wsgi.application"

DATABASES = {
    "default": env.db("DATABASE_URL", default="sqlite:///db.sqlite3"),
}

AUTH_USER_MODEL = "accounts.CustomUser"

SITE_ID = 1

AUTHENTICATION_BACKENDS = [
    "allauth.account.auth_backends.AuthenticationBackend",
]

ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_USER_MODEL_USERNAME_FIELD = None

REST_AUTH = {
    "USE_JWT": True,
    "JWT_AUTH_COOKIE": "access-token",
    "JWT_AUTH_REFRESH_COOKIE": "refresh-token",
    "JWT_AUTH_HTTPONLY": True,
    "USER_DETAILS_SERIALIZER": "apps.accounts.serializers.UserSerializer",
    "REGISTER_SERIALIZER": "apps.accounts.serializers.RegisterSerializer",
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    # Only the browser agent is throttled: it is slow, costs API tokens per run and
    # reaches the public internet, so a runaway client must not be able to loop on it.
    "DEFAULT_THROTTLE_RATES": {"browser": env("BROWSER_THROTTLE_RATE", default="10/hour")},
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": False,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = "django-db"
CELERY_CACHE_BACKEND = "django-cache"
CELERY_RESULT_EXTENDED = True
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
# Task events power apps/tasks' run_metrics_exporter. Both are off by default in Celery,
# and without them the event stream carries worker heartbeats but no task lifecycle at
# all - so every task metric would read zero. The worker also needs its -E flag.
CELERY_WORKER_SEND_TASK_EVENTS = True
CELERY_TASK_SEND_SENT_EVENT = True

ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY", default="")

OLLAMA_BASE_URL = env("OLLAMA_BASE_URL", default="http://localhost:11434")
# Per-role models. The main model handles chat/analysis/synthesis/agents.
OLLAMA_MAIN_MODEL = env("OLLAMA_MAIN_MODEL", default="qwen3:8b")
OLLAMA_CLASSIFIER_MODEL = env("OLLAMA_CLASSIFIER_MODEL", default="qwen3:1.7b")
OLLAMA_EMBED_MODEL = env("OLLAMA_EMBED_MODEL", default="nomic-embed-text")
OLLAMA_TIMEOUT = env.int("OLLAMA_TIMEOUT", default=60)
# App-side fan-out cap; mirror the server's OLLAMA_NUM_PARALLEL so we never queue.
OLLAMA_NUM_PARALLEL = env.int("OLLAMA_NUM_PARALLEL", default=4)
# Context window for every main/classifier-model call, sent EXPLICITLY rather than left to
# Ollama's default - a declared window is what the Scratchpad budget in
# apps/llm_analysis/_context.py measures against, and it makes silent truncation a
# configuration choice rather than an accident.
#
# The VALUE is 4096 because that is what fits. Measured on the live host (RTX 3060, 12 GB):
#
#   num_ctx   qwen3:8b VRAM   models resident
#   4096          6.25 GB     3 of 3   <- classifier + main + embedder all stay loaded
#   8192          7.54 GB     2 of 3
#   16384        10.11 GB     2 of 3
#
# Above 4096 the main model crowds the classifier out, so every routed query pays a
# model swap. And it buys nothing today: the largest real prompts in this app measure
# ~1,100 tokens (a full ReAct scratchpad, and the AI company summary). Raise it only
# alongside a residency re-measurement - CLAUDE.md's "all three stay resident" is the
# invariant this trades against.
OLLAMA_NUM_CTX = env.int("OLLAMA_NUM_CTX", default=4096)
# Routing mode: "llm" (classifier model) or "semantic" (embedder, 0 LLM calls for the path).
OLLAMA_ROUTE_MODE = env("OLLAMA_ROUTE_MODE", default="llm")
# Minimum cosine similarity to a route exemplar before trusting the semantic decision.
OLLAMA_ROUTE_THRESHOLD = env.float("OLLAMA_ROUTE_THRESHOLD", default=0.75)
# Hard cap on ReAct agent iterations (Thought -> Tool -> Observation) before forcing an answer.
OLLAMA_REACT_MAX_STEPS = env.int("OLLAMA_REACT_MAX_STEPS", default=6)
# Chat agent: tool calls allowed WITHIN ONE TURN before a final answer is forced. Lower
# than ReAct's on purpose - most conversational turns need no tool at all, and a turn is
# interactive, so latency matters more than exhaustiveness.
OLLAMA_CHAT_MAX_STEPS = env.int("OLLAMA_CHAT_MAX_STEPS", default=4)
# Evaluator-Optimizer: max generate/evaluate/revise iterations and the 0-10 quality bar to stop at.
OLLAMA_EVAL_MAX_ITERATIONS = env.int("OLLAMA_EVAL_MAX_ITERATIONS", default=3)
OLLAMA_EVAL_THRESHOLD = env.int("OLLAMA_EVAL_THRESHOLD", default=8)
# Plan-and-Execute: max plan steps and the hard cap on replans when a step's tool lookup diverges.
OLLAMA_PLAN_MAX_STEPS = env.int("OLLAMA_PLAN_MAX_STEPS", default=20)
OLLAMA_PLAN_MAX_REPLANS = env.int("OLLAMA_PLAN_MAX_REPLANS", default=5)
# Orchestrator-Workers: max number of dynamically-decomposed worker subtasks.
OLLAMA_ORCH_MAX_WORKERS = env.int("OLLAMA_ORCH_MAX_WORKERS", default=4)
# Multi-Agent (Sequential): max read-only tool calls the Researcher sub-agent may make.
OLLAMA_MULTIAGENT_MAX_TOOLS = env.int("OLLAMA_MULTIAGENT_MAX_TOOLS", default=4)
# Multi-Agent (Parallel/DAG): max number of dynamically-decomposed graph nodes.
OLLAMA_DAG_MAX_NODES = env.int("OLLAMA_DAG_MAX_NODES", default=6)
# Autonomous / Long-Horizon: hard caps that keep the open-ended loop reliable. Max controller
# cycles before forced synthesis; max spawned sub-agents and their own per-sub-agent step budget;
# how many consecutive no-progress cycles terminate a stalled run.
OLLAMA_AUTO_MAX_CYCLES = env.int("OLLAMA_AUTO_MAX_CYCLES", default=8)
OLLAMA_AUTO_MAX_SUBAGENTS = env.int("OLLAMA_AUTO_MAX_SUBAGENTS", default=3)
OLLAMA_AUTO_SUBAGENT_STEPS = env.int("OLLAMA_AUTO_SUBAGENT_STEPS", default=3)
OLLAMA_AUTO_NO_PROGRESS = env.int("OLLAMA_AUTO_NO_PROGRESS", default=2)

# AI company summary freshness gate: how old the relevant CompanySyncRecord may be before
# the summary refuses to opine (and skips the LLM call entirely). These seed the
# LLMSettings singleton.
SUMMARY_SNAPSHOT_MAX_AGE_DAYS = env.int("SUMMARY_SNAPSHOT_MAX_AGE_DAYS", default=7)
SUMMARY_PRICE_MAX_AGE_DAYS = env.int("SUMMARY_PRICE_MAX_AGE_DAYS", default=3)
SUMMARY_FINANCIALS_MAX_AGE_DAYS = env.int("SUMMARY_FINANCIALS_MAX_AGE_DAYS", default=120)

# Browser agent (browser-use): the only agent that reaches the public internet, so it is
# OFF by default and every knob below is a hard bound. These seed the LLMSettings singleton.
BROWSER_ENABLED = env.bool("BROWSER_ENABLED", default=False)
# Which LLM drives the browser: "ollama" (default - free, local, no API key, but small
# models are best-effort at browser-use's strict action JSON) or "anthropic" (far more
# reliable, needs ANTHROPIC_API_KEY and costs per run).
BROWSER_PROVIDER = env("BROWSER_PROVIDER", default="ollama")
# Pinned to a VISION model rather than left blank (which would fall back to
# OLLAMA_MAIN_MODEL). browser-use attaches a screenshot to every step, and a text-only
# model - qwen3:8b, the main model, among them - answers that with a 400 on every step
# rather than degrading, burning the whole step budget. qwen3-vl:8b is the same family and
# quantization as the main model, ~0.9 GB larger. See browser.provider_supports_vision.
# An explicit blank still means "the provider's own default"; anthropic ignores this and
# uses claude-sonnet-5. See browser.build_llm.
BROWSER_MODEL = env("BROWSER_MODEL", default="qwen3-vl:8b")
# Context window for the Ollama browser model. Ollama defaults to 4096, and browser-use's
# per-step prompt (system prompt + serialised DOM + a 1920x1080 screenshot) measures ~15k
# tokens - so the default silently leaves no room to generate and the model returns an
# EMPTY string, which browser-use reports as "Invalid JSON: EOF while parsing". browser-use
# never sets num_ctx itself (ChatOllama.ollama_options is None), so we must.
# Costs KV-cache memory on the Ollama host: lower it if that box is tight.
BROWSER_NUM_CTX = env.int("BROWSER_NUM_CTX", default=32768)
# Max browser actions per run, and the wall-clock ceiling for the whole run.
BROWSER_MAX_STEPS = env.int("BROWSER_MAX_STEPS", default=15)
BROWSER_TIMEOUT_S = env.int("BROWSER_TIMEOUT_S", default=300)
BROWSER_HEADLESS = env.bool("BROWSER_HEADLESS", default=True)
# Newline/comma-separated host allow-list handed to the browser session. Blank = any host,
# which is deliberately NOT the default.
BROWSER_ALLOWED_DOMAINS = env(
    "BROWSER_ALLOWED_DOMAINS",
    default=(
        "*.google.com\n*.duckduckgo.com\n*.bing.com\n*.wikipedia.org\n"
        "*.yahoo.com\n*.reuters.com\n*.bloomberg.com\n*.ft.com\n*.cnbc.com\n"
        "*.marketwatch.com\n*.sec.gov\n*.investopedia.com"
    ),
)
# Where per-run step screenshots are written. Served only through an authenticated,
# owner-checked view (there is no MEDIA_URL) - never listed by the static server.
BROWSER_SCREENSHOT_ROOT = env(
    "BROWSER_SCREENSHOT_ROOT", default=str(BASE_DIR / "media" / "browser")
)
# Screenshots are deleted with their run after this many days by a Celery Beat sweep.
BROWSER_SCREENSHOT_RETENTION_DAYS = env.int("BROWSER_SCREENSHOT_RETENTION_DAYS", default=7)

# Knowledge graph: trigram dedup threshold, default expansion depth, neighbors per
# expansion, and a global node ceiling guarding against runaway fan-out.
KG_SIM_THRESHOLD = env.float("KG_SIM_THRESHOLD", default=0.7)
KG_MAX_DEPTH = env.int("KG_MAX_DEPTH", default=2)
KG_MAX_NEIGHBORS = env.int("KG_MAX_NEIGHBORS", default=8)
KG_MAX_NODES = env.int("KG_MAX_NODES", default=5000)
# Manual structural prune (prune_edges): a weight floor below which edges are dropped
# (a node always keeps its single strongest link so nothing is orphaned).
KG_MIN_EDGE_WEIGHT = env.float("KG_MIN_EDGE_WEIGHT", default=0.6)
# LLM rerank-and-prune: a node with MORE than KG_RERANK_TRIGGER edges is queued for an
# offline LLM rerank that keeps its KG_RERANK_TARGET most important/correct edges.
KG_RERANK_TRIGGER = env.int("KG_RERANK_TRIGGER", default=30)
KG_RERANK_TARGET = env.int("KG_RERANK_TARGET", default=15)
# Word-sense disambiguation: when on, a name colliding with an existing, already-described
# concept is judged by the LLM (same sense -> reuse; different -> mint a disambiguated node), so
# homonyms ("pop" the genre vs "pop" the stack op) no longer merge. Off -> legacy slug reuse.
KG_WSD_ENABLED = env.bool("KG_WSD_ENABLED", default=False)


# ---------------------------------------------------------------------------
# Logging / observability
# ---------------------------------------------------------------------------
# One JSON object per line on stdout -> systemd journal -> Grafana Alloy -> Loki.
# See core/logging.py for why request ids belong in the body and never in a label.
# LOG_FORMAT=console swaps in a human-readable line for local development.
LOG_LEVEL = env("LOG_LEVEL", default="INFO").upper()
LOG_FORMAT = env("LOG_FORMAT", default="json")
# Inbound header honoured for cross-service correlation, and echoed on every response.
REQUEST_ID_HEADER = env("REQUEST_ID_HEADER", default="X-Request-ID")

# Tracing (issue #5). OFF by default, the same opt-in posture as BROWSER_ENABLED and
# PROMETHEUS_EXPORT_WORKER_PORTS. Unlike the Prometheus port range these are SAFE to
# define in base.py: they are inert data, and nothing is bound or exported until
# core.tracing.configure_tracing() is called from an explicit entry point (wsgi.py /
# celery.py) - never from AppConfig.ready(), which every management command and every
# pytest worker would run.
OTEL_TRACES_ENABLED = env.bool("OTEL_TRACES_ENABLED", default=False)
# Alloy's OTLP receiver on the loopback. The app never learns where Tempo lives.
OTEL_EXPORTER_OTLP_ENDPOINT = env("OTEL_EXPORTER_OTLP_ENDPOINT", default="http://127.0.0.1:4317")
# Head sampling ratio, applied to ROOT spans only (children follow their parent).
# 1.0 is affordable at this traffic level and far more useful for debugging agent runs;
# lower it here rather than in code if Tempo's disk growth becomes a problem.
OTEL_TRACES_SAMPLER_RATIO = env.float("OTEL_TRACES_SAMPLER_RATIO", default=1.0)

LOGGING = {
    "version": 1,
    # Django configures DEFAULT_LOGGING before this dict, so leaving existing loggers
    # enabled keeps third-party loggers working; the explicit "django" entry below is
    # what stops Django's own console handler from double-printing every line.
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {"()": "core.logging.RequestIDFilter"},
    },
    "formatters": {
        "json": {"()": "core.logging.JSONFormatter"},
        "console": {
            "format": "%(asctime)s %(levelname)-8s %(name)s [%(request_id)s] %(message)s",
        },
    },
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": LOG_FORMAT,
            "filters": ["request_id"],
        },
    },
    "root": {"handlers": ["stdout"], "level": LOG_LEVEL},
    "loggers": {
        # propagate=False on each: these all have a handler of their own now, and
        # propagating to root as well would emit every line twice.
        "django": {"handlers": ["stdout"], "level": LOG_LEVEL, "propagate": False},
        # The runserver access log. WARNING would hide it entirely, which is not what a
        # developer wants, so it is pinned to INFO regardless of LOG_LEVEL.
        "django.server": {"handlers": ["stdout"], "level": "INFO", "propagate": False},
        "celery": {"handlers": ["stdout"], "level": LOG_LEVEL, "propagate": False},
        "apps": {"handlers": ["stdout"], "level": LOG_LEVEL, "propagate": False},
        "core": {"handlers": ["stdout"], "level": LOG_LEVEL, "propagate": False},
    },
}
