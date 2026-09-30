from typing import ClassVar

from django.contrib import admin
from solo.admin import SingletonModelAdmin

from .models import AgentRun, AgentStep, LLMSettings

admin.site.register(LLMSettings, SingletonModelAdmin)


class AgentStepInline(admin.TabularInline):
    model = AgentStep
    extra = 0
    can_delete = False
    # Spine columns; the kind-specific payload lives in ``meta`` (shown on the change page).
    readonly_fields = (
        "order",
        "key",
        "label",
        "status",
        "output",
        "error",
        "meta",
        "created_at",
    )
    fields = readonly_fields
    ordering = ("order",)


@admin.register(AgentRun)
class AgentRunAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "user", "query_short", "model", "status", "created_at")
    list_filter = ("kind", "status")
    search_fields = ("query", "user__email")
    readonly_fields = ("id", "meta", "created_at", "completed_at")
    inlines: ClassVar = [AgentStepInline]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user")

    @admin.display(description="Query")
    def query_short(self, obj):
        return obj.query[:80]


@admin.register(AgentStep)
class AgentStepAdmin(admin.ModelAdmin):
    list_display = ("id", "run", "order", "key", "label", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("run__id", "key")
    readonly_fields = ("id", "run", "meta", "created_at", "started_at", "completed_at")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("run")
