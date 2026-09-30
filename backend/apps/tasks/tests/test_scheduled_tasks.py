import importlib
import re

import pytest

from apps.tasks.scheduled_tasks import SCHEDULED_TASKS

VALID_INTERVAL_PERIODS = {"seconds", "minutes", "hours", "days", "microseconds"}
DOTTED_PATH_RE = re.compile(r"^[a-z_][a-z0-9_.]*$")

REQUIRED_KEYS = {"name", "task", "schedule_type", "enabled"}
INTERVAL_KEYS = {"every", "period"}
CRONTAB_KEYS = {"minute", "hour", "day_of_week", "day_of_month", "month_of_year"}
KNOWN_KEYS = REQUIRED_KEYS | INTERVAL_KEYS | CRONTAB_KEYS

EXPECTED_TASK_NAMES = {
    "companies-discover-new-symbols-weekly",
    "companies-bootstrap-tick",
    "companies-backfill-snapshot-fields-weekly",
    "companies-tick-price-sync",
    "companies-tick-snapshot-sync",
    "companies-tick-options-sync",
    "companies-tick-profile-sync",
    "companies-tick-earnings-dates-sync",
    "companies-tick-dividend-sync",
    "companies-tick-financial-sync",
    "companies-tick-institutional-holders-sync",
    "companies-tick-short-interest-sync",
    "companies-tick-summary-generation",
}


class TestScheduledTasksStructure:
    def test_is_a_list(self):
        assert isinstance(SCHEDULED_TASKS, list)

    def test_not_empty(self):
        assert len(SCHEDULED_TASKS) > 0

    @pytest.mark.parametrize("spec", SCHEDULED_TASKS)
    def test_required_keys_present(self, spec):
        missing = REQUIRED_KEYS - spec.keys()
        assert not missing, f"{spec['name']!r} missing keys: {missing}"

    @pytest.mark.parametrize("spec", SCHEDULED_TASKS)
    def test_no_unknown_keys(self, spec):
        unknown = spec.keys() - KNOWN_KEYS
        assert not unknown, f"{spec['name']!r} has unrecognised keys: {unknown}"

    @pytest.mark.parametrize("spec", SCHEDULED_TASKS)
    def test_name_is_non_empty_string(self, spec):
        assert isinstance(spec["name"], str) and spec["name"].strip()

    @pytest.mark.parametrize("spec", SCHEDULED_TASKS)
    def test_task_is_dotted_path(self, spec):
        assert DOTTED_PATH_RE.match(spec["task"]), (
            f"{spec['name']!r} task {spec['task']!r} is not a valid dotted path"
        )

    @pytest.mark.parametrize("spec", SCHEDULED_TASKS)
    def test_task_function_is_importable(self, spec):
        """Catch typos in task paths before they reach production."""
        module_path, fn_name = spec["task"].rsplit(".", 1)
        try:
            module = importlib.import_module(module_path)
        except ImportError as exc:
            pytest.fail(f"{spec['name']!r}: cannot import module {module_path!r}: {exc}")
        assert hasattr(module, fn_name), (
            f"{spec['name']!r}: {module_path!r} has no attribute {fn_name!r}"
        )

    @pytest.mark.parametrize("spec", SCHEDULED_TASKS)
    def test_enabled_is_boolean(self, spec):
        assert isinstance(spec["enabled"], bool)

    @pytest.mark.parametrize("spec", SCHEDULED_TASKS)
    def test_schedule_type_is_valid(self, spec):
        assert spec["schedule_type"] in ("interval", "crontab")

    @pytest.mark.parametrize(
        "spec",
        [s for s in SCHEDULED_TASKS if s.get("schedule_type") == "interval"],
    )
    def test_interval_has_every_and_period(self, spec):
        missing = INTERVAL_KEYS - spec.keys()
        assert not missing, f"{spec['name']!r} missing interval keys: {missing}"

    @pytest.mark.parametrize(
        "spec",
        [s for s in SCHEDULED_TASKS if s.get("schedule_type") == "interval"],
    )
    def test_interval_every_is_positive_int(self, spec):
        assert isinstance(spec["every"], int) and spec["every"] > 0

    @pytest.mark.parametrize(
        "spec",
        [s for s in SCHEDULED_TASKS if s.get("schedule_type") == "interval"],
    )
    def test_interval_period_is_valid(self, spec):
        assert spec["period"] in VALID_INTERVAL_PERIODS, (
            f"{spec['name']!r} has unknown period {spec['period']!r}"
        )

    @pytest.mark.parametrize(
        "spec",
        [s for s in SCHEDULED_TASKS if s.get("schedule_type") == "crontab"],
    )
    def test_crontab_fields_are_strings(self, spec):
        for key in CRONTAB_KEYS:
            if key in spec:
                assert isinstance(spec[key], str), f"{spec['name']!r} {key!r} must be a string"

    @pytest.mark.parametrize(
        "spec",
        [s for s in SCHEDULED_TASKS if s.get("schedule_type") == "crontab"],
    )
    def test_crontab_minute_is_valid(self, spec):
        minute = spec.get("minute", "*")
        if minute == "*":
            return
        for part in minute.replace("-", ",").split(","):
            assert part.isdigit() and 0 <= int(part) <= 59, (
                f"{spec['name']!r} has invalid minute value {minute!r}"
            )

    @pytest.mark.parametrize(
        "spec",
        [s for s in SCHEDULED_TASKS if s.get("schedule_type") == "crontab"],
    )
    def test_crontab_hour_is_valid(self, spec):
        hour = spec.get("hour", "*")
        if hour == "*":
            return
        for part in hour.replace("-", ",").split(","):
            assert part.isdigit() and 0 <= int(part) <= 23, (
                f"{spec['name']!r} has invalid hour value {hour!r}"
            )

    @pytest.mark.parametrize(
        "spec",
        [s for s in SCHEDULED_TASKS if s.get("schedule_type") == "crontab"],
    )
    def test_crontab_day_of_week_is_valid(self, spec):
        dow = spec.get("day_of_week", "*")
        if dow == "*":
            return
        for part in dow.replace("-", ",").split(","):
            assert part.isdigit() and 0 <= int(part) <= 6, (
                f"{spec['name']!r} has invalid day_of_week value {dow!r}"
            )

    def test_names_are_unique(self):
        names = [s["name"] for s in SCHEDULED_TASKS]
        assert len(names) == len(set(names)), "Duplicate task names found"

    def test_task_paths_are_unique(self):
        tasks = [s["task"] for s in SCHEDULED_TASKS]
        assert len(tasks) == len(set(tasks)), "Duplicate task paths found"

    def test_expected_task_names_all_present(self):
        names = {s["name"] for s in SCHEDULED_TASKS}
        missing = EXPECTED_TASK_NAMES - names
        assert not missing, f"Expected tasks missing from SCHEDULED_TASKS: {missing}"


def _to_minutes(spec: dict) -> int:
    """Convert an interval spec to minutes for comparison."""
    period = spec["period"]
    every = spec["every"]
    if period == "minutes":
        return every
    if period == "hours":
        return every * 60
    if period == "days":
        return every * 60 * 24
    return every  # seconds — treated as <1 minute; always < any threshold


class TestScheduledTasksBusinessRules:
    """Rolling-tick schedule constraints."""

    def _by_name(self, name: str) -> dict:
        return next(s for s in SCHEDULED_TASKS if s["name"] == name)

    def test_bootstrap_tick_runs_at_most_every_30_minutes(self):
        spec = self._by_name("companies-bootstrap-tick")
        assert spec["schedule_type"] == "interval"
        assert _to_minutes(spec) <= 30

    def test_daily_ticks_run_at_most_every_60_minutes(self):
        for name in (
            "companies-tick-price-sync",
            "companies-tick-snapshot-sync",
            "companies-tick-options-sync",
        ):
            spec = self._by_name(name)
            assert spec["schedule_type"] == "interval", f"{name} should be interval"
            assert _to_minutes(spec) <= 60, f"{name} interval too long for daily coverage"

    def test_weekly_ticks_run_at_most_every_6_hours(self):
        for name in (
            "companies-tick-profile-sync",
            "companies-tick-earnings-dates-sync",
            "companies-tick-dividend-sync",
        ):
            spec = self._by_name(name)
            assert spec["schedule_type"] == "interval", f"{name} should be interval"
            assert _to_minutes(spec) <= 360, f"{name} interval too long for weekly coverage"

    def test_financial_tick_runs_at_most_every_24_hours(self):
        spec = self._by_name("companies-tick-financial-sync")
        assert spec["schedule_type"] == "interval"
        assert _to_minutes(spec) <= 1440, "Financial tick too infrequent for monthly coverage"

    def test_institutional_holders_tick_runs_at_most_every_3_days(self):
        spec = self._by_name("companies-tick-institutional-holders-sync")
        assert spec["schedule_type"] == "interval"
        assert _to_minutes(spec) <= 4320

    def test_short_interest_tick_runs_at_most_every_3_days(self):
        spec = self._by_name("companies-tick-short-interest-sync")
        assert spec["schedule_type"] == "interval"
        assert _to_minutes(spec) <= 4320

    def test_summary_tick_runs_at_most_every_12_hours(self):
        spec = self._by_name("companies-tick-summary-generation")
        assert spec["schedule_type"] == "interval"
        assert _to_minutes(spec) <= 720

    def test_options_weekday_guard_is_in_task_not_schedule(self):
        # The schedule runs every 30 min all week; the task itself skips on weekends.
        spec = self._by_name("companies-tick-options-sync")
        assert spec.get("day_of_week") is None, (
            "Weekday guard belongs inside tick_options_sync, not in the schedule"
        )

    def test_discovery_still_runs_weekly_via_crontab(self):
        spec = self._by_name("companies-discover-new-symbols-weekly")
        assert spec["schedule_type"] == "crontab"
        assert spec.get("day_of_week") is not None

    def test_backfill_still_runs_weekly_via_crontab(self):
        spec = self._by_name("companies-backfill-snapshot-fields-weekly")
        assert spec["schedule_type"] == "crontab"
        assert spec.get("day_of_week") is not None
