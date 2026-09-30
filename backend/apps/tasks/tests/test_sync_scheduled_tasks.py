from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django_celery_beat.models import IntervalSchedule, PeriodicTask

TASK_NAME = "yfinance-sync-company-profiles-daily"
TASK_PATH = "apps.companies.tasks.sync_company_profiles"

FAKE_REGISTRY = [
    {
        "name": TASK_NAME,
        "task": TASK_PATH,
        "schedule_type": "interval",
        "every": 24,
        "period": "hours",
        "enabled": True,
    }
]


def _run(*args, **kwargs):
    out = StringIO()
    call_command("sync_scheduled_tasks", *args, stdout=out, **kwargs)
    return out.getvalue()


def _make_periodic_task(name: str, every: int = 1) -> PeriodicTask:
    schedule, _ = IntervalSchedule.objects.get_or_create(every=every, period="hours")
    return PeriodicTask.objects.create(name=name, task="some.task", interval=schedule)


@pytest.mark.django_db
class TestSyncScheduledTasksCreate:
    def test_creates_periodic_task(self):
        with patch(
            "apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", FAKE_REGISTRY
        ):
            _run()
        assert PeriodicTask.objects.filter(name=TASK_NAME).exists()

    def test_created_task_has_correct_schedule(self):
        with patch(
            "apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", FAKE_REGISTRY
        ):
            _run()
        task = PeriodicTask.objects.get(name=TASK_NAME)
        assert task.interval.every == 24
        assert task.interval.period == IntervalSchedule.HOURS

    def test_created_task_points_to_correct_function(self):
        with patch(
            "apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", FAKE_REGISTRY
        ):
            _run()
        task = PeriodicTask.objects.get(name=TASK_NAME)
        assert task.task == TASK_PATH

    def test_created_task_is_enabled(self):
        with patch(
            "apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", FAKE_REGISTRY
        ):
            _run()
        task = PeriodicTask.objects.get(name=TASK_NAME)
        assert task.enabled is True

    def test_output_says_created(self):
        with patch(
            "apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", FAKE_REGISTRY
        ):
            out = _run()
        assert "created" in out


@pytest.mark.django_db
class TestSyncScheduledTasksIdempotent:
    def test_running_twice_does_not_duplicate(self):
        with patch(
            "apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", FAKE_REGISTRY
        ):
            _run()
            _run()
        assert PeriodicTask.objects.filter(name=TASK_NAME).count() == 1

    def test_second_run_output_says_updated(self):
        with patch(
            "apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", FAKE_REGISTRY
        ):
            _run()
            out = _run()
        assert "updated" in out


@pytest.mark.django_db
class TestSyncScheduledTasksUpdate:
    def test_updates_changed_schedule(self):
        with patch(
            "apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", FAKE_REGISTRY
        ):
            _run()

        modified = [{**FAKE_REGISTRY[0], "every": 48}]
        with patch("apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", modified):
            _run()

        task = PeriodicTask.objects.get(name=TASK_NAME)
        assert task.interval.every == 48

    def test_updates_enabled_flag(self):
        with patch(
            "apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", FAKE_REGISTRY
        ):
            _run()

        disabled = [{**FAKE_REGISTRY[0], "enabled": False}]
        with patch("apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", disabled):
            _run()

        task = PeriodicTask.objects.get(name=TASK_NAME)
        assert task.enabled is False

    def test_updates_task_path(self):
        with patch(
            "apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", FAKE_REGISTRY
        ):
            _run()

        renamed = [{**FAKE_REGISTRY[0], "task": "apps.companies.tasks.bulk_import_tickers"}]
        with patch("apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", renamed):
            _run()

        task = PeriodicTask.objects.get(name=TASK_NAME)
        assert task.task == "apps.companies.tasks.bulk_import_tickers"


CRONTAB_REGISTRY = [
    {
        "name": "crontab-task",
        "task": "apps.companies.tasks.sync_company_profiles",
        "schedule_type": "crontab",
        "minute": "0",
        "hour": "2",
        "day_of_week": "0",
        "enabled": True,
    }
]


@pytest.mark.django_db
class TestSyncScheduledTasksCrontab:
    def test_creates_crontab_task(self):
        with patch(
            "apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", CRONTAB_REGISTRY
        ):
            _run()
        task = PeriodicTask.objects.get(name="crontab-task")
        assert task.crontab is not None
        assert task.interval is None

    def test_crontab_fields_are_correct(self):
        with patch(
            "apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", CRONTAB_REGISTRY
        ):
            _run()
        task = PeriodicTask.objects.get(name="crontab-task")
        assert task.crontab.minute == "0"
        assert task.crontab.hour == "2"
        assert task.crontab.day_of_week == "0"


@pytest.mark.django_db
class TestSyncScheduledTasksPrune:
    def test_stale_row_deleted_on_every_run(self):
        _make_periodic_task("stale-task")
        with patch(
            "apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", FAKE_REGISTRY
        ):
            _run()
        assert not PeriodicTask.objects.filter(name="stale-task").exists()

    def test_stale_row_deletion_message_printed(self):
        _make_periodic_task("stale-task")
        with patch(
            "apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", FAKE_REGISTRY
        ):
            out = _run()
        assert "deleted" in out
        assert "stale-task" in out

    def test_known_task_not_pruned(self):
        with patch(
            "apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", FAKE_REGISTRY
        ):
            _run()
        assert PeriodicTask.objects.filter(name=TASK_NAME).exists()

    def test_multiple_stale_rows_all_deleted(self):
        _make_periodic_task("stale-a")
        _make_periodic_task("stale-b")
        with patch(
            "apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", FAKE_REGISTRY
        ):
            _run()
        assert not PeriodicTask.objects.filter(name__in=["stale-a", "stale-b"]).exists()

    def test_celery_builtin_task_not_pruned(self):
        # Celery auto-creates celery.backend_cleanup (purges expired result rows);
        # it must survive a sync even though it is not in SCHEDULED_TASKS.
        _make_periodic_task("celery.backend_cleanup")
        with patch(
            "apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", FAKE_REGISTRY
        ):
            out = _run()
        assert PeriodicTask.objects.filter(name="celery.backend_cleanup").exists()
        assert "celery.backend_cleanup" not in out

    def test_celery_namespace_not_pruned(self):
        _make_periodic_task("celery.some_other_internal")
        with patch(
            "apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", FAKE_REGISTRY
        ):
            _run()
        assert PeriodicTask.objects.filter(name="celery.some_other_internal").exists()


@pytest.mark.django_db
class TestSyncScheduledTasksDryRun:
    def test_dry_run_does_not_create_rows(self):
        with patch(
            "apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", FAKE_REGISTRY
        ):
            _run("--dry-run")
        assert not PeriodicTask.objects.filter(name=TASK_NAME).exists()

    def test_dry_run_prints_intent(self):
        with patch(
            "apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", FAKE_REGISTRY
        ):
            out = _run("--dry-run")
        assert "[dry-run]" in out
        assert TASK_NAME in out

    def test_dry_run_shows_update_when_row_exists(self):
        with patch(
            "apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", FAKE_REGISTRY
        ):
            _run()
            out = _run("--dry-run")
        assert "would update" in out

    def test_dry_run_does_not_delete_stale_rows(self):
        _make_periodic_task("stale-task")
        with patch(
            "apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", FAKE_REGISTRY
        ):
            _run("--dry-run")
        assert PeriodicTask.objects.filter(name="stale-task").exists()

    def test_dry_run_shows_would_delete_for_stale_rows(self):
        _make_periodic_task("stale-task")
        with patch(
            "apps.tasks.management.commands.sync_scheduled_tasks.SCHEDULED_TASKS", FAKE_REGISTRY
        ):
            out = _run("--dry-run")
        assert "would delete" in out
        assert "stale-task" in out
