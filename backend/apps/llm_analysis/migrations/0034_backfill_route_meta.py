"""Backfill route AgentRun ``meta`` from the legacy typed columns. Route has no child rows."""

from django.db import migrations

RUN_KEYS = ["route", "route_reason", "route_method", "route_confidence"]


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
    for run in AgentRun.objects.filter(kind="route").iterator():
        run.meta = _pick(run, RUN_KEYS)
        run.save(update_fields=["meta"])


def backwards(apps, schema_editor):
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentRun.objects.filter(kind="route").update(meta=dict())


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analysis", "0033_backfill_autonomous_meta"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
