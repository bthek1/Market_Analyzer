"""Copy legacy ReactRun/ReactStep rows into the unified AgentRun/AgentStep tables.

Part of the llm_analysis model consolidation (one workflow per phase). Ids and all
timestamps are preserved so frontend deep links / localStorage run ids still resolve.
The legacy ReactRun/ReactStep tables are left in place (now empty) until the final
GOAL phase drops them.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    ReactRun = apps.get_model("llm_analysis", "ReactRun")
    ReactStep = apps.get_model("llm_analysis", "ReactStep")
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentStep = apps.get_model("llm_analysis", "AgentStep")

    for run in ReactRun.objects.all().iterator():
        AgentRun.objects.create(
            id=run.id,
            kind="react",
            user_id=run.user_id,
            query=run.query,
            model=run.model,
            status=run.status,
            output=run.output,
            error=run.error,
            created_at=run.created_at,
            completed_at=run.completed_at,
            max_steps=run.max_steps,
        )
        steps = [
            AgentStep(
                id=step.id,
                run_id=run.id,
                order=step.order,
                status=step.status,
                error=step.error,
                created_at=step.created_at,
                thought=step.thought,
                tool=step.tool,
                tool_args=step.tool_args,
                observation=step.observation,
                is_answer=step.is_answer,
            )
            for step in ReactStep.objects.filter(run_id=run.id).iterator()
        ]
        AgentStep.objects.bulk_create(steps)


def backwards(apps, schema_editor):
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentStep = apps.get_model("llm_analysis", "AgentStep")
    ReactRun = apps.get_model("llm_analysis", "ReactRun")
    ReactStep = apps.get_model("llm_analysis", "ReactStep")

    for run in AgentRun.objects.filter(kind="react").iterator():
        ReactRun.objects.update_or_create(
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
                max_steps=run.max_steps or 6,
            ),
        )
        for step in AgentStep.objects.filter(run_id=run.id).iterator():
            ReactStep.objects.update_or_create(
                id=step.id,
                defaults=dict(
                    run_id=run.id,
                    order=step.order,
                    status=step.status,
                    error=step.error,
                    created_at=step.created_at,
                    thought=step.thought,
                    tool=step.tool,
                    tool_args=step.tool_args,
                    observation=step.observation,
                    is_answer=step.is_answer,
                ),
            )
        AgentStep.objects.filter(run_id=run.id).delete()
        run.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analysis", "0013_agentrun_agentstep"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
