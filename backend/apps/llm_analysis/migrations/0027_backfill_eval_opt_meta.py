"""Backfill eval_opt AgentRun/AgentStep ``meta`` from the legacy typed columns."""

from django.db import migrations

RUN_KEYS = ["max_iterations", "threshold", "best_score"]
STEP_KEYS = ["draft", "score", "feedback", "passed"]


def _pick(obj, keys):
    out = {}
    for k in keys:
        v = getattr(obj, k)
        if v in ("", None, False):
            continue
        out[k] = v
    return out


def forwards(apps, schema_editor):
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentStep = apps.get_model("llm_analysis", "AgentStep")
    for run in AgentRun.objects.filter(kind="eval_opt").iterator():
        run.meta = _pick(run, RUN_KEYS)
        run.save(update_fields=["meta"])
    for step in AgentStep.objects.filter(run__kind="eval_opt").iterator():
        step.meta = _pick(step, STEP_KEYS)
        step.save(update_fields=["meta"])


def backwards(apps, schema_editor):
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentStep = apps.get_model("llm_analysis", "AgentStep")
    AgentRun.objects.filter(kind="eval_opt").update(meta=dict())
    AgentStep.objects.filter(run__kind="eval_opt").update(meta=dict())


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analysis", "0026_backfill_react_meta"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
