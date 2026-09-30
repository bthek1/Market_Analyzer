"""Copy legacy ChainRun/ChainStepResult rows into AgentRun/AgentStep.

Part of the llm_analysis model consolidation (one workflow per phase). The per-step
``step_id`` is stored in ``AgentStep.key``. ChainRun has no output/error columns, so
those stay blank on AgentRun. Ids and timestamps are preserved. Legacy tables are left
in place (now empty) until the GOAL phase drops them.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    ChainRun = apps.get_model("llm_analysis", "ChainRun")
    ChainStepResult = apps.get_model("llm_analysis", "ChainStepResult")
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentStep = apps.get_model("llm_analysis", "AgentStep")

    for run in ChainRun.objects.all().iterator():
        AgentRun.objects.create(
            id=run.id,
            kind="chain",
            user_id=run.user_id,
            query=run.query,
            model=run.model,
            status=run.status,
            created_at=run.created_at,
            completed_at=run.completed_at,
        )
        AgentStep.objects.bulk_create(
            [
                AgentStep(
                    id=s.id,
                    run_id=run.id,
                    order=s.order,
                    status=s.status,
                    error=s.error,
                    started_at=s.started_at,
                    completed_at=s.completed_at,
                    key=s.step_id,
                    label=s.label,
                    output=s.output,
                )
                for s in ChainStepResult.objects.filter(run_id=run.id).iterator()
            ]
        )


def backwards(apps, schema_editor):
    ChainRun = apps.get_model("llm_analysis", "ChainRun")
    ChainStepResult = apps.get_model("llm_analysis", "ChainStepResult")
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentStep = apps.get_model("llm_analysis", "AgentStep")

    for run in AgentRun.objects.filter(kind="chain").iterator():
        ChainRun.objects.update_or_create(
            id=run.id,
            defaults=dict(
                user_id=run.user_id,
                query=run.query,
                model=run.model,
                status=run.status,
                created_at=run.created_at,
                completed_at=run.completed_at,
            ),
        )
        for s in AgentStep.objects.filter(run_id=run.id).iterator():
            ChainStepResult.objects.update_or_create(
                id=s.id,
                defaults=dict(
                    run_id=run.id,
                    order=s.order,
                    status=s.status,
                    error=s.error,
                    started_at=s.started_at,
                    completed_at=s.completed_at,
                    step_id=s.key,
                    label=s.label,
                    output=s.output,
                ),
            )
        AgentStep.objects.filter(run_id=run.id).delete()
        run.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analysis", "0021_migrate_autonomous_to_agentrun"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
