from django.urls import path

from .views import RedisInfoView, RedisKeysView, RedisKeyValueView

urlpatterns = [
    path("info/", RedisInfoView.as_view(), name="redis-info"),
    path("keys/", RedisKeysView.as_view(), name="redis-keys"),
    path("keys/<path:key>/value/", RedisKeyValueView.as_view(), name="redis-key-value"),
]
