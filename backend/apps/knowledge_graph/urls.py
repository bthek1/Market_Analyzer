from django.urls import path

from .views import (
    AutoExpandView,
    ConceptDetailView,
    ConceptExpandView,
    ConceptGraphView,
    ConceptListCreateView,
    ConceptRerankView,
    ExpansionClearView,
    ReduceTransitiveEdgesView,
    RerankAllView,
)

urlpatterns = [
    path("concepts/", ConceptListCreateView.as_view(), name="kg-concept-list"),
    path("expansion/auto/", AutoExpandView.as_view(), name="kg-expansion-auto"),
    path("expansion/clear/", ExpansionClearView.as_view(), name="kg-expansion-clear"),
    path("edges/reduce/", ReduceTransitiveEdgesView.as_view(), name="kg-edges-reduce"),
    path("rerank-all/", RerankAllView.as_view(), name="kg-rerank-all"),
    path("concepts/<uuid:pk>/", ConceptDetailView.as_view(), name="kg-concept-detail"),
    path("concepts/<uuid:pk>/graph/", ConceptGraphView.as_view(), name="kg-concept-graph"),
    path("concepts/<uuid:pk>/expand/", ConceptExpandView.as_view(), name="kg-concept-expand"),
    path("concepts/<uuid:pk>/rerank/", ConceptRerankView.as_view(), name="kg-concept-rerank"),
]
