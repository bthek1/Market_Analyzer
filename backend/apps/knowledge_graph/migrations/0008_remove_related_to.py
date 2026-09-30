"""Remove the symmetric ``related_to`` relation from the knowledge graph completely.

``related_to`` carried no hierarchy or ordering, so its edges are DELETED (not converted) and
the relation is dropped from ``ConceptEdge.relation``'s choices. Concepts that were joined to
the graph only by ``related_to`` become isolated and re-link structurally on the next expansion.

The reverse is a no-op for the delete - removed associations are not recoverable - which is
intended for a deliberate removal.
"""

from django.db import migrations, models


def delete_related_to(apps, schema_editor):
    ConceptEdge = apps.get_model("knowledge_graph", "ConceptEdge")
    ConceptEdge.objects.filter(relation="related_to").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("knowledge_graph", "0007_concept_negative_description"),
    ]

    operations = [
        migrations.RunPython(delete_related_to, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="conceptedge",
            name="relation",
            field=models.CharField(
                choices=[
                    ("has_subfield", "has subfield"),
                    ("prerequisite_for", "prerequisite for"),
                ],
                max_length=50,
            ),
        ),
    ]
