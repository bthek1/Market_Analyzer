"""Flip the hierarchy relation from ``subfield_of`` (child -> parent) to ``has_subfield``
(parent -> child).

The hierarchy is unchanged - every existing edge has its source/target swapped and its
relation renamed, so ``child --subfield_of--> parent`` becomes ``parent --has_subfield-->
child``. Because ``(source, target, relation)`` is unique, a flipped edge that collides with
one already converted this run is merged (running-mean ``weight``, summed ``times_seen``)
rather than duplicated - the same collapse rule used in ``0002``.
"""

from django.db import migrations, models


def _flip(concept_edge, from_rel, to_rel):
    for edge in concept_edge.objects.filter(relation=from_rel):
        new_source, new_target = edge.target_id, edge.source_id
        existing = (
            concept_edge.objects.filter(source_id=new_source, target_id=new_target, relation=to_rel)
            .exclude(pk=edge.pk)
            .first()
        )
        if existing is None:
            edge.source_id = new_source
            edge.target_id = new_target
            edge.relation = to_rel
            edge.save(update_fields=["source", "target", "relation"])
        else:
            total = existing.times_seen + edge.times_seen
            existing.weight = (
                existing.weight * existing.times_seen + edge.weight * edge.times_seen
            ) / total
            existing.times_seen = total
            existing.save(update_fields=["weight", "times_seen"])
            edge.delete()


def to_has_subfield(apps, schema_editor):
    _flip(apps.get_model("knowledge_graph", "ConceptEdge"), "subfield_of", "has_subfield")


def to_subfield_of(apps, schema_editor):
    _flip(apps.get_model("knowledge_graph", "ConceptEdge"), "has_subfield", "subfield_of")


class Migration(migrations.Migration):
    dependencies = [
        ("knowledge_graph", "0002_reduce_relation_types"),
    ]

    operations = [
        migrations.RunPython(to_has_subfield, to_subfield_of),
        migrations.AlterField(
            model_name="conceptedge",
            name="relation",
            field=models.CharField(
                choices=[
                    ("has_subfield", "has subfield"),
                    ("prerequisite_of", "prerequisite of"),
                    ("related_to", "related to"),
                ],
                max_length=50,
            ),
        ),
    ]
