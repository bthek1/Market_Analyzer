"""Copy legacy RouteRun rows into AgentRun (kind="route").

Part of the llm_analysis model consolidation (one workflow per phase). Route has no
child rows; its ``chain_run`` OneToOne becomes ``AgentRun.parent``. Because Chain was
migrated first (preserving ids), the old ``chain_run_id`` maps directly to the migrated
chain AgentRun's id. Ids and timestamps are preserved. Legacy tables are left in place
(now empty) until the GOAL phase drops them.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    RouteRun = apps.get_model("llm_analysis", "RouteRun")
    AgentRun = apps.get_model("llm_analysis", "AgentRun")

    for run in RouteRun.objects.all().iterator():
        AgentRun.objects.create(
            id=run.id,
            kind="route",
            user_id=run.user_id,
            query=run.query,
            model=run.model,
            status=run.status,
            output=run.output,
            error=run.error,
            created_at=run.created_at,
            completed_at=run.completed_at,
            route=run.route or "",
            route_reason=run.route_reason,
            route_method=run.route_method or "",
            route_confidence=run.route_confidence,
            # chain_run_id points at a chain run whose id is preserved as an AgentRun id.
            parent_id=run.chain_run_id,
        )


def backwards(apps, schema_editor):
    RouteRun = apps.get_model("llm_analysis", "RouteRun")
    AgentRun = apps.get_model("llm_analysis", "AgentRun")

    for run in AgentRun.objects.filter(kind="route").iterator():
        RouteRun.objects.update_or_create(
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
                route=run.route or None,
                route_reason=run.route_reason,
                route_method=run.route_method or None,
                route_confidence=run.route_confidence,
                chain_run_id=run.parent_id,
            ),
        )
        run.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("llm_analysis", "0022_migrate_chain_to_agentrun"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
