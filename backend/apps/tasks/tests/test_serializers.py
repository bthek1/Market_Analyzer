import uuid
from datetime import UTC
from datetime import datetime as dt

import pytest
from django_celery_beat.models import CrontabSchedule, IntervalSchedule, PeriodicTask
from django_celery_results.models import TaskResult

from apps.tasks.serializers import PeriodicTaskSerializer, TaskResultSerializer


def make_task_result(**kwargs) -> TaskResult:
    defaults = {
        "task_id": str(uuid.uuid4()),
        "task_name": "apps.companies.tasks.sync_company_profiles",
        "status": "SUCCESS",
        "result": '{"created": 1}',
    }
    defaults.update(kwargs)
    return TaskResult.objects.create(**defaults)


@pytest.mark.django_db
class TestTaskResultSerializer:
    def test_serializes_required_fields(self):
        tr = make_task_result()
        data = TaskResultSerializer(tr).data
        for field in [
            "task_id",
            "task_name",
            "status",
            "result",
            "date_created",
            "date_done",
            "traceback",
            "worker",
        ]:
            assert field in data

    def test_null_fields_serialize_as_none(self):
        tr = make_task_result(traceback=None, worker=None)
        data = TaskResultSerializer(tr).data
        assert data["traceback"] is None
        assert data["worker"] is None

    def test_status_value_preserved(self):
        tr = make_task_result(status="FAILURE")
        assert TaskResultSerializer(tr).data["status"] == "FAILURE"


@pytest.mark.django_db
class TestPeriodicTaskSerializerIntervalDisplay:
    def _make(self, name, **interval_kwargs) -> PeriodicTask:
        schedule, _ = IntervalSchedule.objects.get_or_create(every=1, period="hours")
        task, _ = PeriodicTask.objects.get_or_create(
            name=name,
            defaults={"task": "some.task", "interval": schedule},
        )
        return task

    def test_interval_display_for_interval_schedule(self):
        schedule, _ = IntervalSchedule.objects.get_or_create(every=12, period="hours")
        task, _ = PeriodicTask.objects.get_or_create(
            name="interval-display-test",
            defaults={"task": "some.task", "interval": schedule},
        )
        data = PeriodicTaskSerializer(task).data
        assert data["interval_display"] != ""
        assert data["interval_display"] != "—"

    def test_interval_display_for_crontab_schedule(self):
        cron, _ = CrontabSchedule.objects.get_or_create(
            minute="0",
            hour="2",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
        )
        task, _ = PeriodicTask.objects.get_or_create(
            name="crontab-display-test",
            defaults={"task": "some.task", "crontab": cron},
        )
        data = PeriodicTaskSerializer(task).data
        assert data["interval_display"] != ""
        assert data["interval_display"] != "—"

    def test_interval_display_fallback_when_no_schedule(self):
        task = PeriodicTask(
            name="no-schedule-task",
            task="some.task",
            interval=None,
            crontab=None,
        )
        data = PeriodicTaskSerializer(task).data
        assert data["interval_display"] == "—"

    def test_serializes_enabled_field(self):
        task = self._make("enabled-test")
        task.enabled = False
        task.save()
        data = PeriodicTaskSerializer(task).data
        assert data["enabled"] is False

    def test_serializes_total_run_count(self):
        task = self._make("runcount-test")
        data = PeriodicTaskSerializer(task).data
        assert isinstance(data["total_run_count"], int)


@pytest.mark.django_db
class TestPeriodicTaskSerializerNextRunAt:
    def _interval_task(self, name: str, enabled: bool = True) -> PeriodicTask:
        schedule, _ = IntervalSchedule.objects.get_or_create(every=24, period="hours")
        task, _ = PeriodicTask.objects.get_or_create(
            name=name,
            defaults={"task": "some.task", "interval": schedule, "enabled": enabled},
        )
        task.enabled = enabled
        task.save(update_fields=["enabled"])
        return task

    def test_next_run_at_is_future_iso_string_for_enabled_interval_task(self):
        task = self._interval_task("next-run-interval-enabled")
        data = PeriodicTaskSerializer(task).data
        assert data["next_run_at"] is not None
        parsed = dt.fromisoformat(data["next_run_at"])
        assert parsed > dt.now(UTC)

    def test_next_run_at_is_none_for_disabled_task(self):
        task = self._interval_task("next-run-disabled", enabled=False)
        data = PeriodicTaskSerializer(task).data
        assert data["next_run_at"] is None

    def test_next_run_at_is_future_iso_string_for_enabled_crontab_task(self):
        cron, _ = CrontabSchedule.objects.get_or_create(
            minute="0",
            hour="3",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
        )
        task, _ = PeriodicTask.objects.get_or_create(
            name="next-run-crontab-enabled",
            defaults={"task": "some.task", "crontab": cron, "enabled": True},
        )
        data = PeriodicTaskSerializer(task).data
        assert data["next_run_at"] is not None
        parsed = dt.fromisoformat(data["next_run_at"])
        assert parsed > dt.now(UTC)

    def test_next_run_at_is_none_when_no_schedule(self):
        task = PeriodicTask(
            name="next-run-no-schedule", task="some.task", interval=None, crontab=None
        )
        data = PeriodicTaskSerializer(task).data
        assert data["next_run_at"] is None
