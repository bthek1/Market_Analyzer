"""Copy legacy OrchestratorRun/OrchestratorWorker rows into AgentRun/AgentStep.

Part of the llm_analysis model consolidation (one workflow per phase). The per-worker
``worker_id`` is stored in ``AgentStep.key``. Ids and all timestamps are preserved.
Legacy tables are left in place (now empty) until the GOAL phase drops them.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    OrchestratorRun = apps.get_model("llm_analysis", "OrchestratorRun")
    OrchestratorWorker = apps.get_model("llm_analysis", "OrchestratorWorker")
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentStep = apps.get_model("llm_analysis", "AgentStep")

    for run in OrchestratorRun.objects.all().iterator():
        AgentRun.objects.create(
            id=run.id,
            kind="orchestrator",
            user_id=run.user_id,
            query=run.query,
            model=run.model,
            status=run.status,
            output=run.output,
            error=run.error,
            created_at=run.created_at,
            completed_at=run.completed_at,
            max_workers=run.max_workers,
            plan=run.plan,
        )
        AgentStep.objects.bulk_create(
            [
                AgentStep(
                    id=w.id,
                    run_id=run.id,
                    order=w.order,
                    status=w.status,
                    error=w.error,
                    started_at=w.started_at,
                    completed_at=w.completed_at,
                    key=w.worker_id,
                    label=w.label,
                    task=w.task,
                    tool=w.tool,
                    tool_args=w.tool_args,
                    observation=w.observation,
                    output=w.output,
                )
                for w in OrchestratorWorker.objects.filter(run_id=run.id).iterator()
            ]
        )


def backwards(apps, schema_editor):
    OrchestratorRun = apps.get_model("llm_analysis", "OrchestratorRun")
    OrchestratorWorker = apps.get_model("llm_analysis", "OrchestratorWorker")
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentStep = apps.get_model("llm_analysis", "AgentStep")

    for run in AgentRun.objects.filter(kind="orchestrator").iterator():
        OrchestratorRun.objects.update_or_create(
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
                max_workers=run.max_workers or 4,
                plan=run.plan,
            ),
        )
        for w in AgentStep.objects.filter(run_id=run.id).iterator():
            OrchestratorWorker.objects.update_or_create(
                id=w.id,
                defaults=dict(
                    run_id=run.id,
                    order=w.order,
                    status=w.status,
                    error=w.error,
                    started_at=w.started_at,
                    completed_at=w.completed_at,
                    worker_id=w.key,
                    label=w.label,
                    task=w.task,
                    tool=w.tool,
                    tool_args=w.tool_args,
                    observation=w.observation,
                    output=w.output,
                ),
            )
        AgentStep.objects.filter(run_id=run.id).delete()
        run.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analysis", "0017_migrate_parallel_to_agentrun"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
