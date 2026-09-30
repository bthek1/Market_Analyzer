import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  autoExpand,
  clearExpansionQueue,
  createConcept,
  deleteConcept,
  getConcept,
  getConceptGraph,
  listConcepts,
  reduceTransitiveEdges,
  rerankAll,
  rerankConcept,
  startExpansion,
  type ListConceptsParams,
} from "@/api/knowledge";
import { queryKeys } from "@/api/queryKeys";
import type { StartExpansionPayload } from "@/types/knowledge";

/**
 * Concept list (with per-concept connection counts). Pass `poll` to refetch on an interval so
 * the list - and its connection badges - grow live while an async expansion is running.
 */
export function useConcepts(params?: ListConceptsParams, poll = false) {
  return useQuery({
    queryKey: queryKeys.knowledge.concepts(params),
    queryFn: () => listConcepts(params),
    refetchInterval: poll ? 4000 : false,
  });
}

/**
 * Concept detail (description, expanded status, neighbor edges). Pass `poll` to refetch on an
 * interval so the panel updates once the async expansion of this node lands.
 */
export function useConcept(id: string | null, poll = false) {
  return useQuery({
    queryKey: queryKeys.knowledge.concept(id ?? ""),
    queryFn: () => getConcept(id as string),
    enabled: !!id,
    refetchInterval: poll ? 4000 : false,
  });
}

/**
 * Subgraph for the visualisation. While the selected node is still expanding (or new
 * nodes are arriving), callers can pass `poll` to refetch on an interval so the graph
 * grows live after an async expansion was started.
 */
export function useConceptGraph(id: string | null, hops: number, poll = false) {
  return useQuery({
    queryKey: queryKeys.knowledge.graph(id ?? "", hops),
    queryFn: () => getConceptGraph(id as string, hops),
    enabled: !!id,
    refetchInterval: poll ? 4000 : false,
  });
}

export function useCreateConcept() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string }) => createConcept(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledge", "concepts"] });
    },
  });
}

export function useDeleteConcept() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteConcept(id),
    onSuccess: (_data, id) => {
      // The node and its edges are gone - drop its detail cache and refetch the list +
      // any open subgraph so the deleted node disappears everywhere.
      queryClient.removeQueries({ queryKey: queryKeys.knowledge.concept(id) });
      queryClient.invalidateQueries({ queryKey: ["knowledge", "concepts"] });
      queryClient.invalidateQueries({ queryKey: ["knowledge", "graph"] });
    },
  });
}

export function useRerankConcept() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => rerankConcept(id),
    onSuccess: (_data, id) => {
      // The rerank-and-prune runs async (Celery); pruned edges land after this returns, so the
      // route turns on live polling to pick them up. Invalidate so caches refresh once it lands.
      queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.concept(id) });
      queryClient.invalidateQueries({ queryKey: ["knowledge", "concepts"] });
      queryClient.invalidateQueries({ queryKey: ["knowledge", "graph"] });
    },
  });
}

export function useAutoExpand() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (maxDepth: number) => autoExpand(maxDepth),
    onSuccess: () => {
      // The crawl runs async (Celery); new nodes/edges land over the next seconds. Invalidate so
      // caches refresh, and the route turns on live polling to watch the graph grow.
      queryClient.invalidateQueries({ queryKey: ["knowledge", "concepts"] });
      queryClient.invalidateQueries({ queryKey: ["knowledge", "graph"] });
    },
  });
}

export function useClearExpansionQueue() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => clearExpansionQueue(),
    onSuccess: () => {
      // The crawl is stopping; refresh the frontier so its size stops climbing, and the graph/
      // lists so counts settle once the last in-flight tasks finish.
      queryClient.invalidateQueries({ queryKey: ["knowledge", "concepts"] });
      queryClient.invalidateQueries({ queryKey: ["knowledge", "graph"] });
    },
  });
}

export function useRerankAll() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => rerankAll(),
    onSuccess: () => {
      // The rerank-and-prune of every over-trigger hub runs async (Celery); pruned edges land
      // after this returns, so the route turns on live polling to pick them up. Invalidate so
      // caches refresh once the tasks land.
      queryClient.invalidateQueries({ queryKey: ["knowledge", "graph"] });
      queryClient.invalidateQueries({ queryKey: ["knowledge", "concepts"] });
    },
  });
}

export function useReduceTransitiveEdges() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => reduceTransitiveEdges(),
    onSuccess: () => {
      // Redundant edges were removed graph-wide (synchronously). Refresh any open subgraph and
      // the concept list so the pruned hierarchy and connection counts reflect the reduction.
      queryClient.invalidateQueries({ queryKey: ["knowledge", "graph"] });
      queryClient.invalidateQueries({ queryKey: ["knowledge", "concepts"] });
    },
  });
}

export function useStartExpansion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: StartExpansionPayload }) =>
      startExpansion(id, body),
    onSuccess: (_data, { id }) => {
      // The expansion runs async (Celery), so the new description/edges/connection counts
      // arrive after this returns - the route turns on live polling to pick them up. We still
      // invalidate here so the caches are refreshed the moment the task lands.
      queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.concept(id) });
      queryClient.invalidateQueries({ queryKey: ["knowledge", "concepts"] });
      queryClient.invalidateQueries({ queryKey: ["knowledge", "graph"] });
    },
  });
}
