from django.contrib import admin
from django.urls import include, path

from core.views import HealthView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", HealthView.as_view()),
    path("api/auth/", include("dj_rest_auth.urls")),
    path("api/auth/registration/", include("dj_rest_auth.registration.urls")),
    path("api/accounts/", include("apps.accounts.urls")),
    path("api/companies/", include("apps.companies.urls")),
    path("api/tasks/", include("apps.tasks.urls")),
    path("api/redis/", include("apps.redis_monitor.urls")),
    path("api/llm/", include("apps.llm_analysis.urls")),
    path("api/knowledge/", include("apps.knowledge_graph.urls")),
    path("api/codegraph/", include("apps.codegraph.urls")),
]
