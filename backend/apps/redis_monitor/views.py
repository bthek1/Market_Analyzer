from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services


class RedisInfoView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        return Response(services.get_info())


class RedisKeysView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        prefix = request.query_params.get("prefix") or None
        try:
            limit = int(request.query_params.get("limit", 100))
        except ValueError:
            limit = 100
        keys = services.get_keys(prefix=prefix, limit=limit)
        return Response({"keys": keys, "count": len(keys)})


class RedisKeyValueView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, key: str) -> Response:
        return Response(services.get_key_value(key))
