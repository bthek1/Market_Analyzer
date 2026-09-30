import uuid

from django.contrib.postgres.indexes import GinIndex
from django.db import models


class Relation(models.TextChoices):
    HAS_SUBFIELD = "has_subfield", "has subfield"
    PREREQUISITE_FOR = "prerequisite_for", "prerequisite for"


class Concept(models.Model):
    """A node in the topic-agnostic knowledge graph."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    # `slug` is unique per SENSE; `base_slug` is the shared lexical key (slugify of the bare name).
    # Two homonyms ("pop" the genre / "pop" the stack op) share a base_slug but get distinct slugs,
    # so resolution can group senses by base_slug and disambiguate among them. The default sense
    # has slug == base_slug.
    slug = models.SlugField(max_length=200, unique=True)
    base_slug = models.SlugField(max_length=200, default="", blank=True, db_index=True)
    description = models.TextField(blank=True)
    # A one-line "what this concept is NOT" - the contrast signal that sharpens the sense judge
    # (homonym precision) and the UI ("Not to be confused with ..."). Filled lazily on expand.
    negative_description = models.TextField(blank=True)
    times_expanded = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)
        indexes = [  # noqa: RUF012
            GinIndex(
                name="concept_name_trgm",
                fields=["name"],
                opclasses=["gin_trgm_ops"],
            ),
        ]

    def save(self, *args, **kwargs):
        # Default the base (lexical) key to the slug so every node - including ones created
        # directly (tests, admin) - is groupable by base_slug without callers having to set it.
        if not self.base_slug and self.slug:
            self.base_slug = self.slug
            uf = kwargs.get("update_fields")
            if uf is not None and "base_slug" not in uf:
                kwargs["update_fields"] = [*uf, "base_slug"]
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ConceptAlias(models.Model):
    """A surface form (word) that means a given Concept - the synonymy positive signal.

    One concept can accumulate many aliases ("graph" <- {"graphs", "graph"}); the global
    uniqueness of ``slug`` is the guard that a single surface form cannot point at two concepts.
    Modelled as a related table (not a Postgres ``ArrayField``) so SQLite test migrations pass.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    concept = models.ForeignKey(Concept, related_name="aliases", on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)
        verbose_name_plural = "concept aliases"

    def __str__(self):
        return f"{self.name} -> {self.concept_id}"


class ConceptEdge(models.Model):
    """A directed, typed, weighted link between two concepts."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.ForeignKey(Concept, related_name="outgoing", on_delete=models.CASCADE)
    target = models.ForeignKey(Concept, related_name="incoming", on_delete=models.CASCADE)
    relation = models.CharField(max_length=50, choices=Relation.choices)
    weight = models.FloatField()
    times_seen = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(fields=["source", "target", "relation"], name="uniq_edge"),
        ]

    def __str__(self):
        return f"{self.source_id} -{self.relation}-> {self.target_id}"
