"""Browser agent: an LLM that drives a real (headless) browser to search the live web.

Every other agent in this app is read-only over our own Postgres. This one leaves the
network, so it is bounded on every axis: a feature flag, a host allow-list, a step cap, a
wall-clock deadline, one run at a time per process, and a fresh incognito browser profile
per run (no cookies, no stored credentials).

Runtime shape mirrors the other workflows - ``run_browser`` is a plain sync SSE generator
driven by ``services.stream_in_background``. Because browser-use is async, an inner thread
owns the event loop and hands step payloads back over a queue; the generator thread does
all the DB writes (each thread gets its own connection) and yields the SSE events.

The seam for tests is ``build_agent``: nothing below it is exercised in the suite, and no
test may launch a browser (mark any that does ``@pytest.mark.browser_live``).
"""

from __future__ import annotations

import base64
import logging
import os
import queue
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from django.conf import settings
from prometheus_client import Counter

from ._events import event, fail, step_event, succeed

# browser-use ships with anonymized telemetry and cloud sync ON. Both phone home about
# what we browse, so they are off before the library is ever imported. setdefault, so an
# operator who really wants them can still opt in from the environment.
os.environ.setdefault("ANONYMIZED_TELEMETRY", "false")
os.environ.setdefault("BROWSER_USE_CLOUD_SYNC", "false")

if TYPE_CHECKING:
    from collections.abc import Generator

    from .models import AgentRun

logger = logging.getLogger(__name__)

_SENTINEL = object()
# How long we keep draining after the deadline before abandoning the browser thread.
_SHUTDOWN_GRACE_S = 30.0
# How often the drain loop wakes to re-check the deadline / stop flag.
_POLL_S = 0.5


class BrowserAgentError(RuntimeError):
    """Configuration or launch failure that should end the run with a clear message."""


# One browser per process. Chromium costs ~400 MB and the app container has 4 GB, so N
# concurrent users must not mean N browsers. The view acquires before creating the run and
# ``run_browser`` always releases in its finally.
_SLOT = threading.BoundedSemaphore(1)

# A rejected run creates no AgentRun row, so this is the ONLY trace it leaves - it cannot
# be recovered from the database after the fact. Lives in the web process, which is where
# browser runs are started from, so django-prometheus' per-worker ports export it.
SLOT_REJECTIONS = Counter(
    "stockmarket_browser_rejected_total",
    "Browser runs refused because the single concurrency slot was busy.",
)


def acquire_slot() -> bool:
    """Try to claim this process's single browser slot without blocking."""
    return _SLOT.acquire(blocking=False)


def release_slot() -> None:
    try:
        _SLOT.release()
    except ValueError:
        # Released without a matching acquire (e.g. a test driving run_browser directly).
        pass


# --- configuration helpers ----------------------------------------------------------------


def parse_domains(raw: str) -> list[str]:
    """Split the settings blob into a host allow-list. Blank -> [] (meaning no restriction)."""
    if not raw:
        return []
    parts = [p.strip() for chunk in raw.splitlines() for p in chunk.split(",")]
    return [p for p in parts if p]


DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"

# Fallback only - `model_has_vision` asks Ollama first. Substrings identifying a tag that
# can accept images, matched against the model name so "llava:13b" and "qwen2.5vl:7b" both
# hit. Necessarily incomplete (mistral-small3.2 is multimodal and matches nothing here),
# which is exactly why the live capability check is preferred. Conservative by design: a
# false negative costs the agent its screenshots, a false positive costs it every step.
OLLAMA_VISION_MODELS = (
    "llava",
    "vl",
    "vision",
    "gemma3",
    "minicpm-v",
    "moondream",
)


def provider_supports_vision(provider: str, model: str) -> bool:
    """Whether the driving model can accept the screenshot browser-use attaches to a step.

    browser-use defaults ``use_vision`` to True. Sending an image to a text-only model is
    not a degraded run, it is a hard 400 on EVERY step ("Multimodal data provided, but
    model does not support multimodal requests"), so the agent burns its whole step budget
    without ever seeing a page. Anthropic models are all multimodal; Ollama serves mostly
    text-only ones (the default qwen3 among them), so vision is opt-in by model there.
    """
    if provider == "anthropic":
        return True
    if provider == "ollama":
        name = model or _config().main_model or ""
        return model_has_vision(name)
    return False


def model_has_vision(name: str) -> bool:
    """Whether an Ollama tag accepts images, from the server's own capability list.

    Ollama's /api/show reports capabilities ("completion", "tools", "vision", ...), which
    beats guessing from the tag - the name tells you nothing for e.g. mistral-small3.2.
    Falls back to OLLAMA_VISION_MODELS when the server cannot be reached, so an Ollama
    outage degrades to the old heuristic rather than failing the run.
    """
    if not name:
        return False
    try:
        resp = httpx.post(
            f"{_config().base_url}/api/show",
            json={"model": name},
            timeout=10,
        )
        resp.raise_for_status()
        return "vision" in (resp.json().get("capabilities") or [])
    except (httpx.HTTPError, ValueError):
        lowered = name.lower()
        return any(tag in lowered for tag in OLLAMA_VISION_MODELS)


def build_llm(provider: str, model: str) -> Any:
    """Return a browser-use chat model. Raises ``BrowserAgentError`` on bad configuration.

    A blank ``model`` means "the provider's own default": the configured Ollama main
    model, or ``DEFAULT_ANTHROPIC_MODEL``. Provider and model are separate knobs, so a
    model name left over from the other provider never leaks across.
    """
    if provider == "ollama":
        from browser_use import ChatOllama

        cfg = _config()
        return ChatOllama(
            model=model or cfg.main_model,
            host=cfg.base_url,
            # Without this every call runs at Ollama's 4096 default, which a browser-use
            # step prompt (~15k tokens with a screenshot) does not fit in. See BROWSER_NUM_CTX.
            ollama_options={"num_ctx": settings.BROWSER_NUM_CTX},
        )
    if provider == "anthropic":
        api_key = settings.ANTHROPIC_API_KEY
        if not api_key:
            raise BrowserAgentError(
                "The browser agent is configured to use Anthropic but ANTHROPIC_API_KEY is unset. "
                "Set a real key in the backend .env, or switch the provider to Ollama in "
                "LLM Settings."
            )
        from browser_use import ChatAnthropic

        return ChatAnthropic(model=model or DEFAULT_ANTHROPIC_MODEL, api_key=api_key)
    raise BrowserAgentError(f"Unknown browser LLM provider {provider!r}.")


def _config():
    from . import config

    return config.get_llm_config()


# --- launch preflight ---------------------------------------------------------------------
#
# Without this, a Chromium that cannot start fails as
#   "Event handler ... on_BrowserStartEvent ... timed out after 30.0s"
# 30 seconds later - which says nothing about the actual cause. The usual cause on a fresh
# server is the browser binary being present but its shared libraries not (playwright
# downloads the binary; the .so packages come from apt separately).

# Point at the just recipe rather than inlining a shell pipeline: a bare
# `sudo uvx playwright install-deps` dies with "sudo: uvx: command not found" (uv puts uvx
# in ~/.local/bin, which is not on sudo's secure_path), installing nothing and leaving
# exactly the state this message is diagnosing. The recipe elevates only apt-get.
INSTALL_DEPS_CMD = "just be-browser-setup"
INSTALL_BROWSER_CMD = "uvx playwright install chromium"

_PLAYWRIGHT_GLOBS = (
    "chromium-*/chrome-linux*/chrome",
    "chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
    "chromium_headless_shell-*/chrome-linux*/chrome-headless-shell",
    "chromium_headless_shell-*/chrome-linux*/chrome",
)


def resolve_browser_binary() -> str | None:
    """Path to the Chromium browser-use would launch, or None if there is none.

    Mirrors browser-use's own lookup order (system Chrome first, then the Playwright
    download) without depending on its private watchdog helper.
    """
    import glob

    try:
        from browser_use.browser.chrome import find_chrome_executable

        found = find_chrome_executable()
        if found:
            return found
    except Exception:
        pass

    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "~/.cache/ms-playwright"
    for pattern in _PLAYWRIGHT_GLOBS:
        matches = sorted(glob.glob(str(Path(root).expanduser() / pattern)))
        if matches:
            return matches[-1]
    return None


def missing_shared_libraries(binary: str) -> list[str]:
    """Shared objects the binary needs but cannot resolve. Empty list = good to launch.

    ``ldd`` is Linux-only; anywhere else (or if it is unavailable) this reports nothing
    rather than guessing, so the preflight can never block a working setup.
    """
    import subprocess

    try:
        proc = subprocess.run(
            ["ldd", binary], capture_output=True, text=True, timeout=20, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return []
    missing = []
    for line in proc.stdout.splitlines():
        if "not found" in line:
            name = line.strip().split(" ")[0]
            if name and name not in missing:
                missing.append(name)
    return missing


def preflight() -> None:
    """Raise ``BrowserAgentError`` with a fix when the browser cannot possibly start."""
    binary = resolve_browser_binary()
    if binary is None:
        raise BrowserAgentError(
            "No Chrome/Chromium binary found for the browser agent. "
            f"Install one with: {INSTALL_BROWSER_CMD}"
        )
    missing = missing_shared_libraries(binary)
    if missing:
        shown = ", ".join(missing[:4]) + (" and others" if len(missing) > 4 else "")
        raise BrowserAgentError(
            f"Chromium is installed at {binary} but cannot start: missing system libraries "
            f"({shown}). Install them with: {INSTALL_DEPS_CMD}"
        )


def _launch_hint(error: str) -> str:
    """Append the likely fix to a raw browser-use launch failure.

    Preflight catches the common case up front; this covers a launch that gets past it and
    then dies or hangs inside browser-use's start event.
    """
    lowered = error.lower()
    if "browserstartevent" in lowered or ("timed out" in lowered and "start" in lowered):
        return (
            f"{error}\n\nThe browser failed to start within its launch timeout. Check that "
            f"Chromium and its system libraries are installed ({INSTALL_DEPS_CMD}), and that "
            "the server has enough memory for one Chromium process."
        )
    return error


def build_agent(
    task: str,
    *,
    llm: Any,
    allowed_domains: list[str],
    headless: bool,
    on_step: Any,
    should_stop: Any,
    use_vision: bool = True,
) -> Any:
    """Construct the browser-use Agent. The single place that touches browser-use's API,
    and therefore the one thing tests patch."""
    from browser_use import Agent, BrowserProfile, BrowserSession

    profile = BrowserProfile(
        headless=headless,
        allowed_domains=allowed_domains or None,
        # No user_data_dir / storage_state: a throwaway profile every run means the agent
        # can never act with the operator's logged-in sessions.
        user_data_dir=None,
        keep_alive=False,
    )
    return Agent(
        task=task,
        llm=llm,
        browser_session=BrowserSession(browser_profile=profile),
        register_new_step_callback=on_step,
        register_should_stop_callback=should_stop,
        # Off for text-only models: browser-use would otherwise attach a screenshot the
        # model cannot accept and every step would 400. See provider_supports_vision.
        use_vision=use_vision,
        # Never hand the model secrets, and never let it read local files.
        sensitive_data=None,
        available_file_paths=[],
    )


# --- step payload extraction --------------------------------------------------------------


def _action_summary(output: Any) -> tuple[str, dict]:
    """First action of the step as (name, args). browser-use emits one dict per action with
    a single key naming it."""
    actions = getattr(output, "action", None) or []
    for action in actions:
        try:
            dumped = action.model_dump(exclude_unset=True)
        except AttributeError:
            continue
        for name, args in dumped.items():
            if args is None:
                continue
            return name, args if isinstance(args, dict) else {"value": args}
    return "", {}


def step_payload(state: Any, output: Any, n_steps: int) -> dict:
    """Flatten a browser-use step callback into the dict the generator persists."""
    name, args = _action_summary(output)
    return {
        "order": max(int(n_steps) - 1, 0),
        "action": name,
        "action_args": args,
        "url": getattr(state, "url", "") or "",
        "title": getattr(state, "title", "") or "",
        "evaluation": str(getattr(output, "evaluation_previous_goal", "") or ""),
        "memory": str(getattr(output, "memory", "") or ""),
        "goal": str(getattr(output, "next_goal", "") or ""),
        "screenshot_b64": getattr(state, "screenshot", None),
    }


def screenshot_dir(run_id: Any) -> Path:
    return Path(settings.BROWSER_SCREENSHOT_ROOT) / str(run_id)


def save_screenshot(run_id: Any, order: int, b64: str | None) -> str:
    """Write one step's screenshot to disk, returning its ``<run_id>/<order>.png`` key.

    Screenshots are files, not meta: base64 in the JSONB column would be ~200 KB a step.
    Never raises - a missing screenshot must not fail a run.
    """
    if not b64:
        return ""
    try:
        directory = screenshot_dir(run_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{order}.png"
        path.write_bytes(base64.b64decode(b64))
    except Exception:
        logger.warning("Could not save browser screenshot for run %s step %s", run_id, order)
        return ""
    return f"{run_id}/{order}.png"


def _sources(history: Any) -> list[str]:
    """De-duplicated, order-preserving list of URLs the agent actually visited."""
    try:
        urls = history.urls()
    except Exception:
        return []
    seen: list[str] = []
    for url in urls:
        text = str(url or "")
        if text and text != "about:blank" and text not in seen:
            seen.append(text)
    return seen


# --- the workflow -------------------------------------------------------------------------


def run_browser(run: AgentRun, model: str = "") -> Generator[str]:
    """SSE generator. Drives one bounded browser session and streams its steps.

    Owns the release of the process-wide browser slot, however the run ends - normally,
    by error, or by the generator being closed on a stop request.
    """
    try:
        yield from _run_browser(run, model)
    finally:
        release_slot()


def _run_browser(run: AgentRun, model: str = "") -> Generator[str]:
    from . import store
    from .models import AgentStep

    cfg = _config()
    meta = store.run_meta(run)
    max_steps = meta.max_steps or cfg.browser_max_steps
    provider = meta.provider or cfg.browser_provider
    allowed = list(meta.allowed_domains or [])
    timeout_s = cfg.browser_timeout_s

    resolved_model = model or cfg.browser_model
    use_vision = provider_supports_vision(provider, resolved_model)

    try:
        llm = build_llm(provider, resolved_model)
        # Fail fast and legibly rather than 30s into an opaque BrowserStartEvent timeout.
        preflight()
    except BrowserAgentError as exc:
        yield from fail(run, str(exc), meta={"stop_reason": "error"})
        return

    yield event(
        "started",
        max_steps=max_steps,
        provider=provider,
        allowed_domains=allowed,
        timeout_s=timeout_s,
    )

    events: queue.Queue = queue.Queue()
    stop_flag = threading.Event()
    deadline = time.monotonic() + timeout_s
    result: dict[str, Any] = {}

    async def _should_stop() -> bool:
        return stop_flag.is_set() or time.monotonic() >= deadline

    def _on_step(state, output, n_steps) -> None:
        events.put(step_payload(state, output, n_steps))

    def _drive() -> None:
        import asyncio

        async def _main():
            agent = build_agent(
                run.query,
                llm=llm,
                allowed_domains=allowed,
                headless=cfg.browser_headless,
                on_step=_on_step,
                should_stop=_should_stop,
                use_vision=use_vision,
            )
            try:
                return await agent.run(max_steps=max_steps)
            finally:
                # Always tear the browser down; an orphaned Chromium outlives the request.
                try:
                    await agent.close()
                except Exception:
                    logger.warning("Browser session close failed for run %s", run.id)

        try:
            result["history"] = asyncio.run(_main())
        except InterruptedError:
            result["interrupted"] = True
        except BaseException as exc:  # the thread must never die silently
            result["error"] = str(exc) or exc.__class__.__name__
        finally:
            events.put(_SENTINEL)

    worker = threading.Thread(target=_drive, name="browser-agent", daemon=True)
    worker.start()

    timed_out = False
    saved = 0
    try:
        while True:
            try:
                item = events.get(timeout=_POLL_S)
            except queue.Empty:
                if not stop_flag.is_set() and time.monotonic() >= deadline:
                    timed_out = True
                    stop_flag.set()
                elif stop_flag.is_set() and time.monotonic() >= deadline + _SHUTDOWN_GRACE_S:
                    # The browser ignored the stop request; abandon the daemon thread.
                    break
                continue
            if item is _SENTINEL:
                break

            order = item["order"]
            shot = save_screenshot(run.id, order, item.get("screenshot_b64"))
            step = store.create_step(
                run,
                order,
                status=AgentStep.Status.DONE,
                label=item["action"],
                output=item["goal"],
                action=item["action"],
                action_args=item["action_args"],
                url=item["url"],
                title=item["title"],
                evaluation=item["evaluation"],
                memory=item["memory"],
                screenshot=shot,
            )
            saved += 1
            yield step_event(step, "step", kind="browser")
    finally:
        # Covers GeneratorExit too (a stop request closes this generator): tell the
        # browser thread to wind down rather than leaving Chromium running.
        stop_flag.set()

    timed_out = timed_out or time.monotonic() >= deadline
    duration = round(timeout_s - max(deadline - time.monotonic(), 0.0), 2)
    history = result.get("history")
    error = _launch_hint(result["error"]) if result.get("error") else ""

    if error:
        yield from fail(
            run,
            error,
            meta={"stop_reason": "error", "duration_s": duration},
        )
        return

    answer = ""
    sources: list[str] = []
    if history is not None:
        try:
            answer = str(history.final_result() or "")
        except Exception:
            answer = ""
        sources = _sources(history)

    if timed_out:
        stop_reason = "timeout"
    elif history is not None and getattr(history, "is_done", None) and history.is_done():
        stop_reason = "complete"
    else:
        stop_reason = "budget"

    if not answer:
        msg = {
            "timeout": f"The browser agent hit its {timeout_s}s time limit before answering.",
            "budget": f"The browser agent used all {max_steps} steps without producing an answer.",
        }.get(stop_reason, "The browser agent stopped without producing an answer.")
        yield from fail(
            run,
            msg,
            meta={
                "stop_reason": stop_reason,
                "urls_visited": sources,
                "duration_s": duration,
            },
        )
        return

    yield from succeed(
        run,
        answer,
        meta={
            "stop_reason": stop_reason,
            "urls_visited": sources,
            "duration_s": duration,
        },
        sources=sources,
        stop_reason=stop_reason,
        steps=saved,
    )
