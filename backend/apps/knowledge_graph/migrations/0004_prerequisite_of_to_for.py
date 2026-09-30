"""Rename the ordering relation ``prerequisite_of`` -> ``prerequisite_for``.

A pure value rename - the edge still points foundation -> dependent, so no source/target
swap and no collision is possible (``prerequisite_for`` is a brand-new value). A plain bulk
UPDATE suffices; the reverse restores ``prerequisite_of``.
"""

from django.db import migrations, models


def to_prerequisite_for(apps, schema_editor):
    ConceptEdge = apps.get_model("knowledge_graph", "ConceptEdge")
    ConceptEdge.objects.filter(relation="prerequisite_of").update(relation="prerequisite_for")


def to_prerequisite_of(apps, schema_editor):
    ConceptEdge = apps.get_model("knowledge_graph", "ConceptEdge")
    ConceptEdge.objects.filter(relation="prerequisite_for").update(relation="prerequisite_of")


class Migration(migrations.Migration):
    dependencies = [
        ("knowledge_graph", "0003_subfield_of_to_has_subfield"),
    ]

    operations = [
        migrations.RunPython(to_prerequisite_for, to_prerequisite_of),
        migrations.AlterField(
            model_name="conceptedge",
            name="relation",
            field=models.CharField(
                choices=[
                    ("has_subfield", "has subfield"),
                    ("prerequisite_for", "prerequisite for"),
                    ("related_to", "related to"),
                ],
                max_length=50,
            ),
        ),
    ]
