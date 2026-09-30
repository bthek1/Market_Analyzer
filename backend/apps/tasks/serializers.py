from datetime import UTC, timedelta
from datetime import datetime as dt

from django_celery_beat.models import PeriodicTask
from django_celery_results.models import TaskResult
from rest_framework import serializers


class TaskResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskResult
        fields = (
            "task_id",
            "task_name",
            "periodic_task_name",
            "status",
            "result",
            "date_created",
            "date_started",
            "date_done",
            "traceback",
            "task_args",
            "task_kwargs",
            "worker",
        )
        read_only_fields = fields


class PeriodicTaskSerializer(serializers.ModelSerializer):
    interval_display = serializers.SerializerMethodField()
    next_run_at = serializers.SerializerMethodField()

    def get_interval_display(self, obj: PeriodicTask) -> str:
        if obj.interval:
            return str(obj.interval)
        if obj.crontab:
            return str(obj.crontab)
        if obj.clocked:
            return str(obj.clocked)
        return "—"

    def get_next_run_at(self, obj: PeriodicTask) -> str | None:
        if not obj.enabled:
            return None
        try:
            schedule = obj.schedule
            if schedule is None:
                return None
            last_run = obj.last_run_at or dt.now(UTC)
            _is_due, next_seconds = schedule.is_due(last_run)
        except Exception:
            return None
        if next_seconds is None:
            return None
        return (dt.now(UTC) + timedelta(seconds=next_seconds)).isoformat()

    class Meta:
        model = PeriodicTask
        fields = (
            "id",
            "name",
            "task",
            "enabled",
            "interval_display",
            "last_run_at",
            "next_run_at",
            "total_run_count",
            "date_changed",
        )
        read_only_fields = (
            "id",
            "name",
            "task",
            "interval_display",
            "last_run_at",
            "next_run_at",
            "total_run_count",
            "date_changed",
        )
