"""Backfill react AgentRun/AgentStep ``meta`` from the legacy typed columns.

Part of the meta_json refactor (one kind per phase). After this, react reads/writes
``meta``; the typed columns are dropped in the final phase. Reverse clears react meta.
"""

from django.db import migrations

RUN_KEYS = ["max_steps"]
STEP_KEYS = ["thought", "tool", "tool_args", "observation", "is_answer"]


def _pick(obj, keys):
    out = {}
    for k in keys:
        v = getattr(obj, k)
        # Skip empty/None/default-False so meta stays minimal; read-time defaults restore them.
        if v in ("", None, False):
            continue
        out[k] = v
    return out


def forwards(apps, schema_editor):
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentStep = apps.get_model("llm_analysis", "AgentStep")
    for run in AgentRun.objects.filter(kind="react").iterator():
        run.meta = _pick(run, RUN_KEYS)
        run.save(update_fields=["meta"])
    for step in AgentStep.objects.filter(run__kind="react").iterator():
        step.meta = _pick(step, STEP_KEYS)
        step.save(update_fields=["meta"])


def backwards(apps, schema_editor):
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentStep = apps.get_model("llm_analysis", "AgentStep")
    AgentRun.objects.filter(kind="react").update(meta=dict())
    AgentStep.objects.filter(run__kind="react").update(meta=dict())


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analysis", "0025_agentrun_meta_agentstep_meta"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
