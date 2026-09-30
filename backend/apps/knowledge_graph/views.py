from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .config import max_depth, rerank_target
from .models import Concept
from .serializers import (
    ConceptDetailSerializer,
    ConceptSerializer,
    CreateNodeSerializer,
    GraphSerializer,
    StartExpansionSerializer,
)
from .services import (
    all_over_trigger_nodes,
    build_subgraph,
    clear_expansion_queue,
    connection_count_annotation,
    current_cancel_epoch,
    reduce_transitive_edges,
    resolve_concept,
    structure_reach_for,
    top_reach_concept_ids,
)
from .tasks import crawl_hub_task, expand_concept_task, rerank_node_task


class ConceptListCreateView(generics.ListCreateAPIView):
    """List concepts (filter ?search=) or create a new starting node."""

    permission_classes = (IsAuthenticated,)
    serializer_class = ConceptSerializer
    filter_backends = (OrderingFilter,)
    ordering_fields = ("created_at", "name", "connections")
    ordering = ("-connections", "name")

    def get_queryset(self):
        qs = Concept.objects.annotate(connections=connection_count_annotation())
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(name__icontains=search)
        return qs

    def list(self, request: Request, *args, **kwargs) -> Response:
        # `reach` is a recursive graph metric, not a DB column, so it cannot go through the DB
        # OrderingFilter. When the client asks to order by it, compute reach for the whole
        # (search-)filtered set, attach it, sort in Python, then paginate as usual. Any other
        # ordering takes the normal DB path (reach stays null and uncomputed - no cost).
        ordering = request.query_params.get("ordering")
        if ordering not in ("reach", "-reach"):
            return super().list(request, *args, **kwargs)
        concepts = list(self.get_queryset())
        reaches = structure_reach_for([c.pk for c in concepts])
        for c in concepts:
            c.reach = reaches.get(str(c.pk), 0)
        ascending = ordering == "reach"
        concepts.sort(
            key=lambda c: (c.reach, c.connections or 0, c.name.lower()),
            reverse=not ascending,
        )
        page = self.paginate_queryset(concepts)
        target = page if page is not None else concepts
        serializer = self.get_serializer(target, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = CreateNodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        name = serializer.validated_data["name"]
        negative = serializer.validated_data.get("negative_description", "").strip()
        concept, created = resolve_concept(name)
        # Seed the negative meaning only on a brand-new node, never clobbering an existing one
        # (resolve_concept may return a pre-existing concept for a colliding name).
        if created and negative:
            concept.negative_description = negative
            concept.save(update_fields=["negative_description"])
        out = ConceptSerializer(concept).data
        return Response(out, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class ConceptDetailView(generics.RetrieveDestroyAPIView):
    """Retrieve a concept with its edges, or delete it.

    Deleting a Concept cascades to its ConceptEdge rows (both incoming and outgoing) via the
    FK ``on_delete=CASCADE``, so the node and all its links disappear from the graph at once.
    """

    permission_classes = (IsAuthenticated,)
    serializer_class = ConceptDetailSerializer

    def get_queryset(self):
        return Concept.objects.prefetch_related(
            "outgoing__source",
            "outgoing__target",
            "incoming__source",
            "incoming__target",
        )


class ConceptGraphView(APIView):
    """Return the subgraph around a concept as {nodes, edges} for visualisation."""

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk) -> Response:
        root = get_object_or_404(Concept, pk=pk)
        try:
            hops = int(request.query_params.get("hops", 2))
        except (TypeError, ValueError):
            hops = 2
        hops = max(1, min(hops, 4))
        data = build_subgraph(root, hops=hops)
        return Response(GraphSerializer(data).data)


class ConceptExpandView(APIView):
    """Start (or re-run) the recursive expansion loop from a node."""

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk) -> Response:
        concept = get_object_or_404(Concept, pk=pk)
        serializer = StartExpansionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        depth = serializer.validated_data.get("max_depth") or max_depth()
        force = serializer.validated_data.get("force", False)
        epoch = current_cancel_epoch()
        if depth <= 1:
            # 1st degree: expand just this node so its neighbours land as frontier nodes.
            # ``force`` lets an already-expanded node be re-expanded.
            expand_concept_task.delay(str(concept.pk), depth, force=force, epoch=epoch)
        else:
            # 2nd+ degree: crawl this node's EXISTING unexpanded frontier outward ring by ring
            # (the same crawl auto-expand uses), so "2nd degree" expands the selected node's
            # neighbours - not just brand-new nodes, which is what ``expand_concept_task`` would
            # do. ``rings = depth - 1``: ring 1 is the neighbours, ring 2 their neighbours, etc.
            crawl_hub_task.delay(str(concept.pk), depth - 1, epoch=epoch)
        return Response(
            {"status": "started", "concept": str(concept.pk), "max_depth": depth},
            status=status.HTTP_202_ACCEPTED,
        )


class AutoExpandView(APIView):
    """Auto-expand: crawl the top-N highest-REACH concepts outward by ``max_depth`` rings.

    Picks the hubs that anchor the most knowledge structure server-side (highest recursive reach
    = subfields + prerequisite-for, the same metric the graph colours by) and seeds a ring crawl
    on each that expands their unexpanded frontier outward - ring 1 (depth 1), then ring 2 (depth
    2), then ring 3 (depth 3) as it recurses. Each crawl carries the current cancel epoch so a
    "Clear queue" stops the whole run.
    """

    permission_classes = (IsAuthenticated,)
    TOP_N = 5

    def post(self, request: Request) -> Response:
        serializer = StartExpansionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        depth = serializer.validated_data.get("max_depth") or max_depth()
        epoch = current_cancel_epoch()
        hub_ids = top_reach_concept_ids(self.TOP_N)
        for cid in hub_ids:
            crawl_hub_task.delay(cid, depth, epoch=epoch)
        return Response(
            {"status": "started", "hubs": hub_ids, "max_depth": depth},
            status=status.HTTP_202_ACCEPTED,
        )


class ConceptRerankView(APIView):
    """Manually queue an LLM rerank-and-prune of a concept's edges.

    Unlike the automatic >30 trigger fired during expansion, the manual button cleans the node
    down to the configured target whenever it has more edges than that - so a user can tidy a
    node on demand without waiting for it to grow past 30.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk) -> Response:
        concept = get_object_or_404(Concept, pk=pk)
        rerank_node_task.delay(
            str(concept.pk), trigger=rerank_target(), epoch=current_cancel_epoch()
        )
        return Response(
            {"status": "started", "concept": str(concept.pk)},
            status=status.HTTP_202_ACCEPTED,
        )


class RerankAllView(APIView):
    """Queue an LLM rerank-and-prune for EVERY node currently over the rerank trigger.

    The graph-wide companion to the per-node rerank button: instead of cleaning one selected
    concept, it fans a rerank task out across all hubs over the trigger (the same set the periodic
    sweep targets). Returns how many nodes were queued. Each queued task self-guards (no-ops if the
    node has since dropped under the trigger), so this is safe to click repeatedly.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        epoch = current_cancel_epoch()
        node_ids = all_over_trigger_nodes()
        for node_id in node_ids:
            rerank_node_task.delay(str(node_id), epoch=epoch)
        return Response(
            {"status": "started", "queued": len(node_ids)}, status=status.HTTP_202_ACCEPTED
        )


class ReduceTransitiveEdgesView(APIView):
    """Graph-wide transitive reduction: drop edges implied by a longer same-relation path.

    Removes a redundant A -has_subfield-> C when a longer path A -> B -> C already exists,
    leaving the cleaner chain. Runs synchronously (pure DB work, no LLM) and returns the number
    of edges removed so the UI can report it immediately. Idempotent - safe to click repeatedly.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        removed = reduce_transitive_edges()
        return Response({"status": "reduced", "removed": removed}, status=status.HTTP_200_OK)


class ExpansionClearView(APIView):
    """Stop the running expansion crawl: purge the queue and cancel queued/in-flight tasks.

    Bumps the cancel epoch (so already-queued and worker-prefetched tasks self-drop) and purges
    the broker queue. Use this to halt a runaway auto-expand - new expansions started afterwards
    run normally because they are stamped with the new epoch.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        result = clear_expansion_queue()
        return Response({"status": "cleared", **result}, status=status.HTTP_200_OK)
