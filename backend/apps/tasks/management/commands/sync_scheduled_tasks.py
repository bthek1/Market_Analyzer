from django.core.management.base import BaseCommand
from django_celery_beat.models import CrontabSchedule, IntervalSchedule, PeriodicTask

from apps.tasks.scheduled_tasks import SCHEDULED_TASKS

"""
python manage.py sync_scheduled_tasks
"""


class Command(BaseCommand):
    help = "Sync PeriodicTask rows from scheduled_tasks.py; auto-deletes unrecognised rows."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would change without writing anything.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        for spec in SCHEDULED_TASKS:
            self._sync_task(spec, dry_run)

        self._prune(dry_run)

    def _get_schedule(self, spec: dict) -> dict:
        if spec["schedule_type"] == "interval":
            schedule, _ = IntervalSchedule.objects.get_or_create(
                every=spec["every"],
                period=spec["period"],
            )
            return {"interval": schedule, "crontab": None}
        schedule, _ = CrontabSchedule.objects.get_or_create(
            minute=spec.get("minute", "*"),
            hour=spec.get("hour", "*"),
            day_of_week=spec.get("day_of_week", "*"),
            day_of_month=spec.get("day_of_month", "*"),
            month_of_year=spec.get("month_of_year", "*"),
        )
        return {"crontab": schedule, "interval": None}

    def _sync_task(self, spec: dict, dry_run: bool) -> None:
        schedule_kwargs = self._get_schedule(spec)
        defaults = {
            "task": spec["task"],
            "enabled": spec["enabled"],
            **schedule_kwargs,
        }
        if dry_run:
            exists = PeriodicTask.objects.filter(name=spec["name"]).exists()
            action = "update" if exists else "create"
            self.stdout.write(f"[dry-run] would {action}: {spec['name']}")
            return
        _, created = PeriodicTask.objects.update_or_create(
            name=spec["name"],
            defaults=defaults,
        )
        verb = "created" if created else "updated"
        self.stdout.write(self.style.SUCCESS(f"{verb}: {spec['name']}"))

    def _prune(self, dry_run: bool) -> None:
        names = {s["name"] for s in SCHEDULED_TASKS}
        # Never prune Celery's built-in tasks (e.g. celery.backend_cleanup, which
        # purges expired result-backend rows). They live under the "celery."
        # namespace and are managed by Celery, not scheduled_tasks.py.
        stale = PeriodicTask.objects.exclude(name__in=names).exclude(name__startswith="celery.")
        for task in stale:
            if dry_run:
                self.stdout.write(f"[dry-run] would delete: {task.name}")
            else:
                task.delete()
                self.stdout.write(self.style.WARNING(f"deleted: {task.name}"))
