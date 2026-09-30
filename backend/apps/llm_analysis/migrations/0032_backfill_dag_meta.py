"""Backfill dag AgentRun/AgentStep ``meta`` from the legacy typed columns."""

from django.db import migrations

RUN_KEYS = ["max_nodes", "plan"]
STEP_KEYS = ["task", "wave", "depends_on", "tool", "tool_args", "observation"]


def _pick(obj, keys):
    out = {}
    for k in keys:
        v = getattr(obj, k)
        if v in ("", None, False) or v == []:
            continue
        out[k] = v
    return out


def forwards(apps, schema_editor):
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentStep = apps.get_model("llm_analysis", "AgentStep")
    for run in AgentRun.objects.filter(kind="dag").iterator():
        run.meta = _pick(run, RUN_KEYS)
        run.save(update_fields=["meta"])
    for step in AgentStep.objects.filter(run__kind="dag").iterator():
        meta = _pick(step, STEP_KEYS)
        # depends_on is meaningful even when empty for a root node; keep it explicitly.
        if step.depends_on:
            meta["depends_on"] = step.depends_on
        step.meta = meta
        step.save(update_fields=["meta"])


def backwards(apps, schema_editor):
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentStep = apps.get_model("llm_analysis", "AgentStep")
    AgentRun.objects.filter(kind="dag").update(meta=dict())
    AgentStep.objects.filter(run__kind="dag").update(meta=dict())


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analysis", "0031_backfill_multiagent_meta"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
