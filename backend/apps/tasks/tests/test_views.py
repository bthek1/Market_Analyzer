import uuid
from unittest.mock import MagicMock, patch

import pytest
from django_celery_beat.models import IntervalSchedule, PeriodicTask
from django_celery_results.models import TaskResult


def make_result(**kwargs) -> TaskResult:
    defaults = {
        "task_id": str(uuid.uuid4()),
        "task_name": "apps.companies.tasks.sync_company_profiles",
        "status": "SUCCESS",
        "result": '{"created": 1, "synced": 2, "failed": 0}',
    }
    defaults.update(kwargs)
    return TaskResult.objects.create(**defaults)


def make_schedule(
    name="test-task", task="apps.companies.tasks.sync_company_profiles", enabled=True
):
    schedule, _ = IntervalSchedule.objects.get_or_create(every=1, period="hours")
    task_obj, _ = PeriodicTask.objects.get_or_create(
        name=name,
        defaults={"task": task, "interval": schedule, "enabled": enabled},
    )
    return task_obj


@pytest.mark.django_db
class TestTaskResultListView:
    url = "/api/tasks/results/"

    def test_requires_auth(self, api_client):
        assert api_client.get(self.url).status_code == 401

    def test_returns_paginated_list(self, auth_client):
        make_result()
        make_result()
        response = auth_client.get(self.url)
        assert response.status_code == 200
        assert response.data["count"] == 2

    def test_ordered_by_date_done_descending(self, auth_client):
        r1 = make_result(task_name="task.a")
        r2 = make_result(task_name="task.b")
        response = auth_client.get(self.url)
        ids = [r["task_id"] for r in response.data["results"]]
        assert ids.index(r2.task_id) < ids.index(r1.task_id)

    def test_filter_by_status(self, auth_client):
        make_result(status="SUCCESS")
        make_result(status="FAILURE")
        response = auth_client.get(self.url + "?status=FAILURE")
        assert response.data["count"] == 1
        assert response.data["results"][0]["status"] == "FAILURE"

    def test_filter_status_case_insensitive(self, auth_client):
        make_result(status="SUCCESS")
        make_result(status="FAILURE")
        response = auth_client.get(self.url + "?status=success")
        assert response.data["count"] == 1

    def test_response_fields(self, auth_client):
        make_result()
        data = auth_client.get(self.url).data["results"][0]
        for field in ["task_id", "task_name", "status", "result", "date_created", "date_done"]:
            assert field in data


@pytest.mark.django_db
class TestTaskResultDetailView:
    def _url(self, task_id):
        return f"/api/tasks/results/{task_id}/"

    def test_requires_auth(self, api_client):
        r = make_result()
        assert api_client.get(self._url(r.task_id)).status_code == 401

    def test_returns_task_result(self, auth_client):
        r = make_result(task_name="my.task")
        response = auth_client.get(self._url(r.task_id))
        assert response.status_code == 200
        assert response.data["task_id"] == r.task_id
        assert response.data["task_name"] == "my.task"

    def test_unknown_id_returns_404(self, auth_client):
        response = auth_client.get(self._url("nonexistent-id"))
        assert response.status_code == 404


@pytest.fixture()
def periodic_task():
    from django_celery_beat.models import IntervalSchedule, PeriodicTask

    schedule, _ = IntervalSchedule.objects.get_or_create(every=24, period=IntervalSchedule.HOURS)
    task, _ = PeriodicTask.objects.get_or_create(
        name="yfinance-sync-company-profiles-daily",
        defaults={
            "task": "apps.companies.tasks.sync_company_profiles",
            "interval": schedule,
            "enabled": True,
        },
    )
    return task


@pytest.mark.django_db
class TestPeriodicTaskListView:
    url = "/api/tasks/schedules/"

    def test_requires_auth(self, api_client):
        assert api_client.get(self.url).status_code == 401

    def test_returns_all_schedules(self, auth_client, periodic_task):
        response = auth_client.get(self.url)
        assert response.status_code == 200
        assert any(t["name"] == periodic_task.name for t in response.data)

    def test_not_paginated(self, auth_client):
        response = auth_client.get(self.url)
        assert isinstance(response.data, list)

    def test_response_fields(self, auth_client, periodic_task):
        response = auth_client.get(self.url)
        task = response.data[0]
        for field in [
            "id",
            "name",
            "task",
            "enabled",
            "interval_display",
            "last_run_at",
            "total_run_count",
        ]:
            assert field in task

    def test_interval_display_populated(self, auth_client, periodic_task):
        response = auth_client.get(self.url)
        task = next(t for t in response.data if t["name"] == periodic_task.name)
        assert task["interval_display"] != ""


@pytest.mark.django_db
class TestPeriodicTaskToggleView:
    def _url(self, pk):
        return f"/api/tasks/schedules/{pk}/"

    def test_requires_auth(self, api_client):
        t = make_schedule()
        assert (
            api_client.patch(self._url(t.pk), {"enabled": False}, format="json").status_code == 401
        )

    def test_disable_task(self, auth_client):
        t = make_schedule(enabled=True)
        response = auth_client.patch(self._url(t.pk), {"enabled": False}, format="json")
        assert response.status_code == 200
        assert response.data["enabled"] is False
        t.refresh_from_db()
        assert t.enabled is False

    def test_enable_task(self, auth_client):
        t = make_schedule(name="disabled-task", enabled=False)
        response = auth_client.patch(self._url(t.pk), {"enabled": True}, format="json")
        assert response.status_code == 200
        assert response.data["enabled"] is True

    def test_unknown_id_returns_404(self, auth_client):
        response = auth_client.patch(self._url(99999), {"enabled": False}, format="json")
        assert response.status_code == 404

    def test_non_boolean_returns_400(self, auth_client):
        t = make_schedule(name="another-task")
        response = auth_client.patch(self._url(t.pk), {"enabled": "yes"}, format="json")
        assert response.status_code == 400


@pytest.mark.django_db
class TestPeriodicTaskTriggerView:
    def _url(self, pk):
        return f"/api/tasks/schedules/{pk}/trigger/"

    def test_requires_auth(self, api_client):
        t = make_schedule(name="trigger-auth-test")
        assert api_client.post(self._url(t.pk)).status_code == 401

    def test_returns_task_id(self, auth_client):
        t = make_schedule(name="trigger-test")
        fake_id = str(uuid.uuid4())
        mock_result = MagicMock()
        mock_result.id = fake_id
        with patch("apps.tasks.views.current_app.send_task", return_value=mock_result):
            response = auth_client.post(self._url(t.pk))
        assert response.status_code == 202
        assert response.data["task_id"] == fake_id

    def test_sends_correct_task_name(self, auth_client):
        t = make_schedule(name="trigger-name-test", task="apps.companies.tasks.bulk_import_tickers")
        mock_result = MagicMock()
        mock_result.id = str(uuid.uuid4())
        with patch("apps.tasks.views.current_app.send_task", return_value=mock_result) as mock_send:
            auth_client.post(self._url(t.pk))
        mock_send.assert_called_once_with("apps.companies.tasks.bulk_import_tickers")

    def test_unknown_id_returns_404(self, auth_client):
        response = auth_client.post(self._url(99999))
        assert response.status_code == 404
