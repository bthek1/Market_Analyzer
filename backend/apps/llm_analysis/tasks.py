"""Celery tasks for llm_analysis.

Only housekeeping lives here - the workflows themselves run in-process (see
``services.stream_in_background``), not on the worker.
"""

from __future__ import annotations

import logging
import shutil
from datetime import UTC, timedelta
from datetime import datetime as dt
from pathlib import Path

from celery import shared_task
from django.conf import settings

from .models import AgentRun, ChatSession

logger = logging.getLogger(__name__)


@shared_task
def sweep_browser_screenshots() -> dict:
    """Delete screenshot directories for browser runs older than the retention window.

    Screenshots are page captures of the live web, so they are not kept indefinitely.
    Directories whose run no longer exists are swept too (a deleted run leaves its
    files behind - nothing cascades to the filesystem). Idempotent; a no-op when the
    root directory is absent.
    """
    root = Path(settings.BROWSER_SCREENSHOT_ROOT)
    if not root.is_dir():
        return {"removed": 0, "kept": 0}

    cutoff = dt.now(UTC) - timedelta(days=settings.BROWSER_SCREENSHOT_RETENTION_DAYS)
    fresh = {
        str(pk)
        for pk in AgentRun.objects.filter(kind="browser", created_at__gte=cutoff).values_list(
            "id", flat=True
        )
    }

    removed = kept = 0
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if child.name in fresh:
            kept += 1
            continue
        try:
            shutil.rmtree(child)
            removed += 1
        except OSError:
            logger.warning("Could not remove browser screenshot dir %s", child)
    return {"removed": removed, "kept": kept}


TITLE_PROMPT = (
    "Write a short title for a conversation that begins with the message below. "
    "Four words or fewer, no quotes, no trailing period, plain text only. "
    "Reply with the title and nothing else.\n\nMessage: "
)


@shared_task
def generate_chat_title(session_id: str) -> str:
    """Name a chat session from its first message. Fire-and-forget; never raises.

    Runs on the CLASSIFIER model, not the main one: this is a four-word summarisation, the
    classifier is already resident on the GPU, and a title is not worth a model swap.

    A blank title is a supported state - the UI falls back to the truncated first message -
    so every failure path here simply leaves it blank rather than retrying. That is also why
    it is a task and not part of the turn: a title must never delay or fail a reply.
    """
    from . import services

    session = ChatSession.objects.filter(pk=session_id).first()
    if session is None or session.title:
        return ""

    first = session.turns.filter(kind="chat").order_by("created_at").first()
    if first is None:
        return ""

    try:
        raw = services.chat(
            [{"role": "user", "content": TITLE_PROMPT + first.query}],
            model=services._classifier_model(),
        )
    except services.OllamaServiceError:
        logger.warning("Could not title chat session %s", session_id)
        return ""

    # A small model will sometimes answer in a sentence anyway. Take the first line, drop
    # surrounding quotes, and cap it - the column is 200 and the sidebar shows far less.
    title = raw.strip().splitlines()[0].strip().strip("\"'").strip()[:200]
    if not title:
        return ""

    session.title = title
    session.save(update_fields=["title", "updated_at"])
    return title
