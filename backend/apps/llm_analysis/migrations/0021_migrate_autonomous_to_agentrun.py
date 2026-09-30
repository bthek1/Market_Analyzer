"""Copy legacy AutonomousRun/AutonomousCycle rows into AgentRun/AgentStep.

Part of the llm_analysis model consolidation (one workflow per phase). The per-cycle
``index`` becomes ``AgentStep.order``; reflection/action/spawned/subagent_steps/backlog/
goal_complete carry over unchanged. Ids and timestamps are preserved. Legacy tables are
left in place (now empty) until the GOAL phase drops them.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    AutonomousRun = apps.get_model("llm_analysis", "AutonomousRun")
    AutonomousCycle = apps.get_model("llm_analysis", "AutonomousCycle")
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentStep = apps.get_model("llm_analysis", "AgentStep")

    for run in AutonomousRun.objects.all().iterator():
        AgentRun.objects.create(
            id=run.id,
            kind="autonomous",
            user_id=run.user_id,
            query=run.query,
            model=run.model,
            status=run.status,
            output=run.output,
            error=run.error,
            created_at=run.created_at,
            completed_at=run.completed_at,
            max_cycles=run.max_cycles,
            max_subagents=run.max_subagents,
            goal=run.goal,
            backlog=run.backlog,
            stop_reason=run.stop_reason,
        )
        AgentStep.objects.bulk_create(
            [
                AgentStep(
                    id=c.id,
                    run_id=run.id,
                    order=c.index,
                    status=c.status,
                    error=c.error,
                    started_at=c.started_at,
                    completed_at=c.completed_at,
                    reflection=c.reflection,
                    task=c.task,
                    action=c.action,
                    tool=c.tool,
                    tool_args=c.tool_args,
                    observation=c.observation,
                    spawned=c.spawned,
                    subagent_steps=c.subagent_steps,
                    output=c.output,
                    backlog=c.backlog,
                    goal_complete=c.goal_complete,
                )
                for c in AutonomousCycle.objects.filter(run_id=run.id).iterator()
            ]
        )


def backwards(apps, schema_editor):
    AutonomousRun = apps.get_model("llm_analysis", "AutonomousRun")
    AutonomousCycle = apps.get_model("llm_analysis", "AutonomousCycle")
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentStep = apps.get_model("llm_analysis", "AgentStep")

    for run in AgentRun.objects.filter(kind="autonomous").iterator():
        AutonomousRun.objects.update_or_create(
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
                max_cycles=run.max_cycles or 8,
                max_subagents=run.max_subagents if run.max_subagents is not None else 3,
                goal=run.goal,
                backlog=run.backlog,
                stop_reason=run.stop_reason,
            ),
        )
        for c in AgentStep.objects.filter(run_id=run.id).iterator():
            AutonomousCycle.objects.update_or_create(
                id=c.id,
                defaults=dict(
                    run_id=run.id,
                    index=c.order,
                    status=c.status,
                    error=c.error,
                    started_at=c.started_at,
                    completed_at=c.completed_at,
                    reflection=c.reflection,
                    task=c.task,
                    action=c.action or "reason",
                    tool=c.tool,
                    tool_args=c.tool_args,
                    observation=c.observation,
                    spawned=c.spawned,
                    subagent_steps=c.subagent_steps,
                    output=c.output,
                    backlog=c.backlog,
                    goal_complete=c.goal_complete,
                ),
            )
        AgentStep.objects.filter(run_id=run.id).delete()
        run.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analysis", "0020_migrate_dag_to_agentrun"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
