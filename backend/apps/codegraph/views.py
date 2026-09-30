from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services

# A missing graph is the state EVERY fresh clone and prod deploy is in (graphify-out/ is
# gitignored), so it gets a structured 404 the frontend renders as an empty state - not a 500.
NOT_BUILT = {
    "detail": "The code graph has not been built yet.",
    "hint": "Run `graphify extract . --code-only` at the repo root, then `graphify cluster-only .`",
}


def _int_param(request: Request, name: str) -> int | None:
    raw = request.query_params.get(name)
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except ValueError:
        return None


class CodeGraphView(APIView):
    """Filtered {nodes, edges, stats, facets} projection of the graphify code graph."""

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        limit = _int_param(request, "limit") or services.DEFAULT_LIMIT
        try:
            payload = services.get_subgraph(
                kind=request.query_params.get("kind") or None,
                layer=request.query_params.get("layer") or None,
                module=request.query_params.get("module") or None,
                confidence=request.query_params.get("confidence") or None,
                relation=request.query_params.get("relation") or None,
                community=_int_param(request, "community"),
                search=request.query_params.get("search") or None,
                path_prefix=request.query_params.get("path") or None,
                limit=limit,
            )
        except services.GraphNotBuiltError:
            return Response(NOT_BUILT, status=status.HTTP_404_NOT_FOUND)
        except services.GraphUnreadableError:
            return Response(
                {"detail": "The code graph file is present but could not be parsed."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(payload)


class CodeGraphNodeView(APIView):
    """One node with its immediate neighbours, for the selection panel."""

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, node_id: str) -> Response:
        try:
            detail = services.get_node_detail(node_id)
        except services.GraphNotBuiltError:
            return Response(NOT_BUILT, status=status.HTTP_404_NOT_FOUND)
        except services.GraphUnreadableError:
            return Response(
                {"detail": "The code graph file is present but could not be parsed."},
                status=status.HTTP_409_CONFLICT,
            )
        if detail is None:
            return Response({"detail": "Node not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(detail)
