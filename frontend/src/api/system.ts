import { apiClient } from "@/api/client";

export interface HealthResponse {
  version: string;
  db: boolean;
  redis: boolean;
  celery: boolean;
  beat: boolean;
  ollama: boolean;
}

export async function getHealth(): Promise<HealthResponse> {
  const { data } = await apiClient.get<HealthResponse>("/api/health/");
  return data;
}
