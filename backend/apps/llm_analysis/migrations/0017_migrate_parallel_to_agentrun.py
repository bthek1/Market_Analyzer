"""Copy legacy ParallelRun/ParallelTaskResult rows into AgentRun/AgentStep.

Part of the llm_analysis model consolidation (one workflow per phase). The per-task
``task_id`` is stored in ``AgentStep.key``. Ids and all timestamps are preserved.
Legacy tables are left in place (now empty) until the GOAL phase drops them.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    ParallelRun = apps.get_model("llm_analysis", "ParallelRun")
    ParallelTaskResult = apps.get_model("llm_analysis", "ParallelTaskResult")
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentStep = apps.get_model("llm_analysis", "AgentStep")

    for run in ParallelRun.objects.all().iterator():
        AgentRun.objects.create(
            id=run.id,
            kind="parallel",
            user_id=run.user_id,
            query=run.query,
            model=run.model,
            status=run.status,
            output=run.output,
            error=run.error,
            created_at=run.created_at,
            completed_at=run.completed_at,
            strategy=run.strategy,
            n=run.n,
            tally=run.tally,
        )
        AgentStep.objects.bulk_create(
            [
                AgentStep(
                    id=task.id,
                    run_id=run.id,
                    order=task.order,
                    status=task.status,
                    error=task.error,
                    started_at=task.started_at,
                    completed_at=task.completed_at,
                    key=task.task_id,
                    label=task.label,
                    output=task.output,
                    vote=task.vote,
                )
                for task in ParallelTaskResult.objects.filter(run_id=run.id).iterator()
            ]
        )


def backwards(apps, schema_editor):
    ParallelRun = apps.get_model("llm_analysis", "ParallelRun")
    ParallelTaskResult = apps.get_model("llm_analysis", "ParallelTaskResult")
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentStep = apps.get_model("llm_analysis", "AgentStep")

    for run in AgentRun.objects.filter(kind="parallel").iterator():
        ParallelRun.objects.update_or_create(
            id=run.id,
            defaults=dict(
                user_id=run.user_id,
                query=run.query,
                model=run.model,
                status=run.status,
                output=run.output,
                error=run.error,
                created_at=run.created_at,
                completed_at=run.completed_at,
                strategy=run.strategy or "sectioning",
                n=run.n or 3,
                tally=run.tally,
            ),
        )
        for task in AgentStep.objects.filter(run_id=run.id).iterator():
            ParallelTaskResult.objects.update_or_create(
                id=task.id,
                defaults=dict(
                    run_id=run.id,
                    order=task.order,
                    status=task.status,
                    error=task.error,
                    started_at=task.started_at,
                    completed_at=task.completed_at,
                    task_id=task.key,
                    label=task.label,
                    output=task.output,
                    vote=task.vote,
                ),
            )
        AgentStep.objects.filter(run_id=run.id).delete()
        run.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analysis", "0016_migrate_plan_exec_to_agentrun"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
