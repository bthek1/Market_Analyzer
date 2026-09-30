import type { PaginatedResponse } from "@/types/companies";
import type {
  Concept,
  ConceptDetail,
  GraphPayload,
  StartExpansionPayload,
} from "@/types/knowledge";
import { apiClient } from "./client";

export interface ListConceptsParams {
  search?: string;
  ordering?: string;
}

export async function listConcepts(
  params?: ListConceptsParams
): Promise<PaginatedResponse<Concept>> {
  const { data } = await apiClient.get<PaginatedResponse<Concept>>("/api/knowledge/concepts/", {
    params,
  });
  return data;
}

export async function createConcept(body: {
  name: string;
  negative_description?: string;
}): Promise<Concept> {
  const { data } = await apiClient.post<Concept>("/api/knowledge/concepts/", body);
  return data;
}

export async function getConcept(id: string): Promise<ConceptDetail> {
  const { data } = await apiClient.get<ConceptDetail>(`/api/knowledge/concepts/${id}/`);
  return data;
}

export async function deleteConcept(id: string): Promise<void> {
  await apiClient.delete(`/api/knowledge/concepts/${id}/`);
}

export async function getConceptGraph(id: string, hops = 2): Promise<GraphPayload> {
  const { data } = await apiClient.get<GraphPayload>(`/api/knowledge/concepts/${id}/graph/`, {
    params: { hops },
  });
  return data;
}

export async function startExpansion(
  id: string,
  body: StartExpansionPayload
): Promise<{ status: string; concept: string; max_depth: number }> {
  const { data } = await apiClient.post(`/api/knowledge/concepts/${id}/expand/`, body);
  return data;
}

export async function rerankConcept(
  id: string
): Promise<{ status: string; concept: string }> {
  const { data } = await apiClient.post(`/api/knowledge/concepts/${id}/rerank/`);
  return data;
}

export async function clearExpansionQueue(): Promise<{
  status: string;
  purged: number;
  epoch: number;
}> {
  const { data } = await apiClient.post("/api/knowledge/expansion/clear/");
  return data;
}

export async function autoExpand(
  maxDepth: number
): Promise<{ status: string; hubs: string[]; max_depth: number }> {
  const { data } = await apiClient.post("/api/knowledge/expansion/auto/", {
    max_depth: maxDepth,
  });
  return data;
}

export async function reduceTransitiveEdges(): Promise<{ status: string; removed: number }> {
  const { data } = await apiClient.post("/api/knowledge/edges/reduce/");
  return data;
}

export async function rerankAll(): Promise<{ status: string; queued: number }> {
  const { data } = await apiClient.post("/api/knowledge/rerank-all/");
  return data;
}
