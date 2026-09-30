from django.urls import path

from .views import (
    PeriodicTaskListView,
    PeriodicTaskToggleView,
    PeriodicTaskTriggerView,
    TaskResultDetailView,
    TaskResultListView,
)

urlpatterns = [
    path("results/", TaskResultListView.as_view(), name="task-result-list"),
    path("results/<str:task_id>/", TaskResultDetailView.as_view(), name="task-result-detail"),
    path("schedules/", PeriodicTaskListView.as_view(), name="periodic-task-list"),
    path("schedules/<int:pk>/", PeriodicTaskToggleView.as_view(), name="periodic-task-toggle"),
    path(
        "schedules/<int:pk>/trigger/",
        PeriodicTaskTriggerView.as_view(),
        name="periodic-task-trigger",
    ),
]
