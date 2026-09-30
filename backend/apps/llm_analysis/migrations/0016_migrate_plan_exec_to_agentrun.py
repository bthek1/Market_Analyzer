"""Copy legacy PlanExecRun/PlanExecStep rows into AgentRun/AgentStep.

Part of the llm_analysis model consolidation (one workflow per phase). Ids and all
timestamps are preserved. Legacy tables are left in place (now empty) until the GOAL
phase drops them.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    PlanExecRun = apps.get_model("llm_analysis", "PlanExecRun")
    PlanExecStep = apps.get_model("llm_analysis", "PlanExecStep")
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentStep = apps.get_model("llm_analysis", "AgentStep")

    for run in PlanExecRun.objects.all().iterator():
        AgentRun.objects.create(
            id=run.id,
            kind="plan_exec",
            user_id=run.user_id,
            query=run.query,
            model=run.model,
            status=run.status,
            output=run.output,
            error=run.error,
            created_at=run.created_at,
            completed_at=run.completed_at,
            max_steps=run.max_steps,
            allow_replan=run.allow_replan,
            plan=run.plan,
            replans=run.replans,
        )
        AgentStep.objects.bulk_create(
            [
                AgentStep(
                    id=step.id,
                    run_id=run.id,
                    order=step.order,
                    status=step.status,
                    error=step.error,
                    created_at=step.created_at,
                    task=step.task,
                    tool=step.tool,
                    tool_args=step.tool_args,
                    observation=step.observation,
                    result=step.result,
                )
                for step in PlanExecStep.objects.filter(run_id=run.id).iterator()
            ]
        )


def backwards(apps, schema_editor):
    PlanExecRun = apps.get_model("llm_analysis", "PlanExecRun")
    PlanExecStep = apps.get_model("llm_analysis", "PlanExecStep")
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentStep = apps.get_model("llm_analysis", "AgentStep")

    for run in AgentRun.objects.filter(kind="plan_exec").iterator():
        PlanExecRun.objects.update_or_create(
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
                allow_replan=run.allow_replan if run.allow_replan is not None else True,
                plan=run.plan,
                replans=run.replans or 0,
            ),
        )
        for step in AgentStep.objects.filter(run_id=run.id).iterator():
            PlanExecStep.objects.update_or_create(
                id=step.id,
                defaults=dict(
                    run_id=run.id,
                    order=step.order,
                    status=step.status,
                    error=step.error,
                    created_at=step.created_at,
                    task=step.task,
                    tool=step.tool,
                    tool_args=step.tool_args,
                    observation=step.observation,
                    result=step.result,
                ),
            )
        AgentStep.objects.filter(run_id=run.id).delete()
        run.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analysis", "0015_migrate_eval_opt_to_agentrun"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
