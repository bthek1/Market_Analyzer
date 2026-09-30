"""Reduce ConceptEdge relation types from five to three.

Collapses the ``uses`` and ``applies_to`` relations into ``related_to``. Because
(source, target, relation) is unique, an old edge that would collide with an existing
``related_to`` edge between the same pair is merged into it (accumulating ``times_seen``
and keeping the stronger ``weight``) rather than remapped.
"""

from django.db import migrations, models

_MERGED = ("uses", "applies_to")


def collapse_relations(apps, schema_editor):
    ConceptEdge = apps.get_model("knowledge_graph", "ConceptEdge")

    for edge in ConceptEdge.objects.filter(relation__in=_MERGED):
        existing = (
            ConceptEdge.objects.filter(
                source_id=edge.source_id,
                target_id=edge.target_id,
                relation="related_to",
            )
            .exclude(pk=edge.pk)
            .first()
        )
        if existing is None:
            edge.relation = "related_to"
            edge.save(update_fields=["relation"])
        else:
            existing.times_seen += edge.times_seen
            existing.weight = max(existing.weight, edge.weight)
            existing.save(update_fields=["times_seen", "weight"])
            edge.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("knowledge_graph", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(collapse_relations, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="conceptedge",
            name="relation",
            field=models.CharField(
                choices=[
                    ("subfield_of", "subfield of"),
                    ("prerequisite_of", "prerequisite of"),
                    ("related_to", "related to"),
                ],
                max_length=50,
            ),
        ),
    ]
