"""Copy legacy DagRun/DagNode rows into AgentRun/AgentStep.

Part of the llm_analysis model consolidation (one workflow per phase). The per-node
``node_id`` is stored in ``AgentStep.key`` and ``depends_on``/``wave`` carry over
unchanged. The legacy ``(run, node_id)`` uniqueness becomes ``(run, order)`` - every
DagNode already has a distinct ``order``, so this holds. Ids and timestamps are
preserved. Legacy tables are left in place (now empty) until the GOAL phase drops them.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    DagRun = apps.get_model("llm_analysis", "DagRun")
    DagNode = apps.get_model("llm_analysis", "DagNode")
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentStep = apps.get_model("llm_analysis", "AgentStep")

    for run in DagRun.objects.all().iterator():
        AgentRun.objects.create(
            id=run.id,
            kind="dag",
            user_id=run.user_id,
            query=run.query,
            model=run.model,
            status=run.status,
            output=run.output,
            error=run.error,
            created_at=run.created_at,
            completed_at=run.completed_at,
            max_nodes=run.max_nodes,
            plan=run.plan,
        )
        AgentStep.objects.bulk_create(
            [
                AgentStep(
                    id=n.id,
                    run_id=run.id,
                    order=n.order,
                    status=n.status,
                    error=n.error,
                    started_at=n.started_at,
                    completed_at=n.completed_at,
                    key=n.node_id,
                    label=n.label,
                    task=n.task,
                    wave=n.wave,
                    depends_on=n.depends_on,
                    tool=n.tool,
                    tool_args=n.tool_args,
                    observation=n.observation,
                    output=n.output,
                )
                for n in DagNode.objects.filter(run_id=run.id).iterator()
            ]
        )


def backwards(apps, schema_editor):
    DagRun = apps.get_model("llm_analysis", "DagRun")
    DagNode = apps.get_model("llm_analysis", "DagNode")
    AgentRun = apps.get_model("llm_analysis", "AgentRun")
    AgentStep = apps.get_model("llm_analysis", "AgentStep")

    for run in AgentRun.objects.filter(kind="dag").iterator():
        DagRun.objects.update_or_create(
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
                max_nodes=run.max_nodes or 6,
                plan=run.plan,
            ),
        )
        for n in AgentStep.objects.filter(run_id=run.id).iterator():
            DagNode.objects.update_or_create(
                id=n.id,
                defaults=dict(
                    run_id=run.id,
                    order=n.order,
                    status=n.status,
                    error=n.error,
                    started_at=n.started_at,
                    completed_at=n.completed_at,
                    node_id=n.key,
                    label=n.label,
                    task=n.task,
                    wave=n.wave or 0,
                    depends_on=n.depends_on,
                    tool=n.tool,
                    tool_args=n.tool_args,
                    observation=n.observation,
                    output=n.output,
                ),
            )
        AgentStep.objects.filter(run_id=run.id).delete()
        run.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analysis", "0019_migrate_multiagent_to_agentrun"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
