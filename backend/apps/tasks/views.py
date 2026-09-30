from celery import current_app
from django_celery_beat.models import PeriodicTask
from django_celery_results.models import TaskResult
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import PeriodicTaskSerializer, TaskResultSerializer


class TaskResultListView(generics.ListAPIView):
    serializer_class = TaskResultSerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        qs = TaskResult.objects.order_by("-date_done")
        task_status = self.request.query_params.get("status")
        if task_status:
            qs = qs.filter(status=task_status.upper())
        return qs


class TaskResultDetailView(generics.RetrieveAPIView):
    serializer_class = TaskResultSerializer
    permission_classes = (IsAuthenticated,)
    queryset = TaskResult.objects.all()
    lookup_field = "task_id"


class PeriodicTaskListView(generics.ListAPIView):
    serializer_class = PeriodicTaskSerializer
    permission_classes = (IsAuthenticated,)
    queryset = PeriodicTask.objects.select_related("interval", "crontab", "clocked").order_by(
        "name"
    )
    pagination_class = None


class PeriodicTaskToggleView(APIView):
    permission_classes = (IsAuthenticated,)

    def patch(self, request: Request, pk: int) -> Response:
        try:
            task = PeriodicTask.objects.get(pk=pk)
        except PeriodicTask.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        enabled = request.data.get("enabled")
        if not isinstance(enabled, bool):
            return Response({"enabled": "Must be a boolean."}, status=status.HTTP_400_BAD_REQUEST)
        task.enabled = enabled
        task.save(update_fields=["enabled"])
        return Response(PeriodicTaskSerializer(task).data)


class PeriodicTaskTriggerView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int) -> Response:
        try:
            task = PeriodicTask.objects.get(pk=pk)
        except PeriodicTask.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        result = current_app.send_task(task.task)
        return Response({"task_id": result.id}, status=status.HTTP_202_ACCEPTED)
