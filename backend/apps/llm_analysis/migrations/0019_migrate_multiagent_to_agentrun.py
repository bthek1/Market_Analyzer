"""Copy legacy MultiAgentRun/MultiAgentStep rows into AgentRun/AgentStep.

Part of the llm_analysis model consolidation (one workflow per phase). The per-step
``agent_id`` is stored in ``AgentStep.key``. Ids and all timestamps are preserved.
Legacy tables are left in place (now empty) until the GOAL phase drops them.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    MultiAgentRun = apps.get_model("llm_analysis", "MultiAgentRun")
    MultiAgentStep = apps.get_model("llm_analysis", "MultiAgentStep")
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentStep = apps.get_model("llm_analysis", "AgentStep")

    for run in MultiAgentRun.objects.all().iterator():
        AgentRun.objects.create(
            id=run.id,
            kind="multiagent",
            user_id=run.user_id,
            query=run.query,
            model=run.model,
            status=run.status,
            output=run.output,
            error=run.error,
            created_at=run.created_at,
            completed_at=run.completed_at,
            max_tools=run.max_tools,
            agents=run.agents,
            route_reason=run.route_reason,
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
                    key=s.agent_id,
                    label=s.label,
                    input=s.input,
                    tool_calls=s.tool_calls,
                    output=s.output,
                )
                for s in MultiAgentStep.objects.filter(run_id=run.id).iterator()
            ]
        )


def backwards(apps, schema_editor):
    MultiAgentRun = apps.get_model("llm_analysis", "MultiAgentRun")
    MultiAgentStep = apps.get_model("llm_analysis", "MultiAgentStep")
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentStep = apps.get_model("llm_analysis", "AgentStep")

    for run in AgentRun.objects.filter(kind="multiagent").iterator():
        MultiAgentRun.objects.update_or_create(
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
                max_tools=run.max_tools or 4,
                agents=run.agents,
                route_reason=run.route_reason,
            ),
        )
        for s in AgentStep.objects.filter(run_id=run.id).iterator():
            MultiAgentStep.objects.update_or_create(
                id=s.id,
                defaults=dict(
                    run_id=run.id,
                    order=s.order,
                    status=s.status,
                    error=s.error,
                    started_at=s.started_at,
                    completed_at=s.completed_at,
                    agent_id=s.key,
                    label=s.label,
                    input=s.input,
                    tool_calls=s.tool_calls,
                    output=s.output,
                ),
            )
        AgentStep.objects.filter(run_id=run.id).delete()
        run.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analysis", "0018_migrate_orchestrator_to_agentrun"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
