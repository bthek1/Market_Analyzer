"""Copy legacy EvalOptRun/EvalOptIteration rows into AgentRun/AgentStep.

Part of the llm_analysis model consolidation (one workflow per phase). Ids and all
timestamps are preserved. Legacy tables are left in place (now empty) until the GOAL
phase drops them.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    EvalOptRun = apps.get_model("llm_analysis", "EvalOptRun")
    EvalOptIteration = apps.get_model("llm_analysis", "EvalOptIteration")
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentStep = apps.get_model("llm_analysis", "AgentStep")

    for run in EvalOptRun.objects.all().iterator():
        AgentRun.objects.create(
            id=run.id,
            kind="eval_opt",
            user_id=run.user_id,
            query=run.query,
            model=run.model,
            status=run.status,
            output=run.output,
            error=run.error,
            created_at=run.created_at,
            completed_at=run.completed_at,
            max_iterations=run.max_iterations,
            threshold=run.threshold,
            best_score=run.best_score,
        )
        AgentStep.objects.bulk_create(
            [
                AgentStep(
                    id=it.id,
                    run_id=run.id,
                    order=it.order,
                    status=it.status,
                    error=it.error,
                    created_at=it.created_at,
                    draft=it.draft,
                    score=it.score,
                    feedback=it.feedback,
                    passed=it.passed,
                )
                for it in EvalOptIteration.objects.filter(run_id=run.id).iterator()
            ]
        )


def backwards(apps, schema_editor):
    EvalOptRun = apps.get_model("llm_analysis", "EvalOptRun")
    EvalOptIteration = apps.get_model("llm_analysis", "EvalOptIteration")
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentStep = apps.get_model("llm_analysis", "AgentStep")

    for run in AgentRun.objects.filter(kind="eval_opt").iterator():
        EvalOptRun.objects.update_or_create(
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
                max_iterations=run.max_iterations or 3,
                threshold=run.threshold or 8,
                best_score=run.best_score,
            ),
        )
        for it in AgentStep.objects.filter(run_id=run.id).iterator():
            EvalOptIteration.objects.update_or_create(
                id=it.id,
                defaults=dict(
                    run_id=run.id,
                    order=it.order,
                    status=it.status,
                    error=it.error,
                    created_at=it.created_at,
                    draft=it.draft,
                    score=it.score,
                    feedback=it.feedback,
                    passed=it.passed,
                ),
            )
        AgentStep.objects.filter(run_id=run.id).delete()
        run.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analysis", "0014_migrate_react_to_agentrun"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
