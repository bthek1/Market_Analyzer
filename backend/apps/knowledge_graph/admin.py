from django.contrib import admin
from django.db.models import Count

from .models import Concept, ConceptAlias, ConceptEdge


@admin.register(Concept)
class ConceptAdmin(admin.ModelAdmin):
    list_display = ("name", "connections", "times_expanded", "created_at")
    search_fields = ("name", "slug")
    ordering = ("name",)

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .annotate(
                _connections=Count("outgoing", distinct=True) + Count("incoming", distinct=True)
            )
        )

    @admin.display(description="connections", ordering="_connections")
    def connections(self, obj):
        return obj._connections


@admin.register(ConceptEdge)
class ConceptEdgeAdmin(admin.ModelAdmin):
    list_display = ("source", "relation", "target", "weight", "times_seen")
    list_filter = ("relation",)
    autocomplete_fields = ("source", "target")


@admin.register(ConceptAlias)
class ConceptAliasAdmin(admin.ModelAdmin):
    list_display = ("name", "concept", "created_at")
    search_fields = ("name", "slug")
    autocomplete_fields = ("concept",)
