import uuid

import django.db.models.deletion
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations, models


class AddIndexPostgresOnly(migrations.AddIndex):
    """AddIndex that applies its SQL only on PostgreSQL.

    The model state still gains the index (so ``makemigrations`` stays quiet), but the
    GIN/``gin_trgm_ops`` DDL is skipped on other backends (e.g. SQLite used in tests),
    which do not support it.
    """

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor != "postgresql":
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor != "postgresql":
            return
        super().database_backwards(app_label, schema_editor, from_state, to_state)


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        TrigramExtension(),  # no-op on non-PostgreSQL backends
        migrations.CreateModel(
            name="Concept",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=200)),
                ("slug", models.SlugField(max_length=200, unique=True)),
                ("description", models.TextField(blank=True)),
                ("times_expanded", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ("name",),
            },
        ),
        migrations.CreateModel(
            name="ConceptEdge",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "relation",
                    models.CharField(
                        choices=[
                            ("subfield_of", "subfield of"),
                            ("prerequisite_of", "prerequisite of"),
                            ("uses", "uses"),
                            ("applies_to", "applies to"),
                            ("related_to", "related to"),
                        ],
                        max_length=50,
                    ),
                ),
                ("weight", models.FloatField()),
                ("times_seen", models.PositiveIntegerField(default=1)),
                (
                    "source",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="outgoing",
                        to="knowledge_graph.concept",
                    ),
                ),
                (
                    "target",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="incoming",
                        to="knowledge_graph.concept",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="conceptedge",
            constraint=models.UniqueConstraint(
                fields=("source", "target", "relation"), name="uniq_edge"
            ),
        ),
        AddIndexPostgresOnly(
            model_name="concept",
            index=GinIndex(fields=["name"], name="concept_name_trgm", opclasses=["gin_trgm_ops"]),
        ),
    ]
