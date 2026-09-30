from django.urls import path

from .views import CodeGraphNodeView, CodeGraphView

urlpatterns = [
    path("graph/", CodeGraphView.as_view(), name="codegraph-graph"),
    path("nodes/<path:node_id>/", CodeGraphNodeView.as_view(), name="codegraph-node"),
]
