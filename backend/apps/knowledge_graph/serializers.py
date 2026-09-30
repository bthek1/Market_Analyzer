from rest_framework import serializers

from .models import Concept, ConceptEdge, Relation


class ConceptSerializer(serializers.ModelSerializer):
    connections = serializers.SerializerMethodField()
    reach = serializers.SerializerMethodField()

    class Meta:
        model = Concept
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "negative_description",
            "times_expanded",
            "connections",
            "reach",
            "created_at",
        )
        read_only_fields = fields

    def get_reach(self, obj) -> int | None:
        # Recursive structural reach (subfields + prerequisite-for, transitively). Only the
        # subgraph endpoint computes and attaches it; elsewhere (list/detail) it is absent.
        return getattr(obj, "reach", None)

    def get_connections(self, obj) -> int:
        annotated = getattr(obj, "connections", None)
        if annotated is not None:
            return annotated
        # Count structural links (has_subfield + prerequisite_for) to match the annotated path
        # used by the list/subgraph views.
        structural = (Relation.HAS_SUBFIELD, Relation.PREREQUISITE_FOR)
        return (
            obj.outgoing.filter(relation__in=structural).count()
            + obj.incoming.filter(relation__in=structural).count()
        )


class ConceptRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Concept
        fields = ("id", "name", "slug")


class ConceptEdgeSerializer(serializers.ModelSerializer):
    source = ConceptRefSerializer(read_only=True)
    target = ConceptRefSerializer(read_only=True)

    class Meta:
        model = ConceptEdge
        fields = ("id", "source", "target", "relation", "weight", "times_seen")


class ConceptDetailSerializer(ConceptSerializer):
    outgoing = ConceptEdgeSerializer(many=True, read_only=True)
    incoming = ConceptEdgeSerializer(many=True, read_only=True)

    class Meta(ConceptSerializer.Meta):
        fields = (*ConceptSerializer.Meta.fields, "outgoing", "incoming")
        read_only_fields = fields


class GraphSerializer(serializers.Serializer):
    nodes = ConceptSerializer(many=True, read_only=True)
    edges = ConceptEdgeSerializer(many=True, read_only=True)


class CreateNodeSerializer(serializers.Serializer):
    """Create a new starting node, optionally seeding its negative meaning."""

    name = serializers.CharField(max_length=200)
    # Optional "what this concept is NOT" seed. Applied only to a freshly created node; the LLM
    # overwrites it on the first expansion, so this is just a starting hint.
    negative_description = serializers.CharField(
        required=False, allow_blank=True, default="", trim_whitespace=True
    )

    def validate_name(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("This field may not be blank.")
        return value


class StartExpansionSerializer(serializers.Serializer):
    """Start (or re-run) the recursive expansion loop from a node.

    ``max_depth`` is absent -> the view falls back to the configured default.
    """

    max_depth = serializers.IntegerField(required=False, min_value=1, max_value=5)
    force = serializers.BooleanField(required=False, default=False)


# Re-export for callers that want the relation choices.
RELATION_CHOICES = Relation.choices
