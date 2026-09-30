import type { PaginatedResponse } from "@/types/companies";
import type { PeriodicTask, TaskResult, TriggerResponse } from "@/types/tasks";
import { apiClient } from "./client";

export async function getTaskResults(status?: string): Promise<PaginatedResponse<TaskResult>> {
  const params = status ? { status } : undefined;
  const { data } = await apiClient.get<PaginatedResponse<TaskResult>>("/api/tasks/results/", {
    params,
  });
  return data;
}

export async function getTaskResult(taskId: string): Promise<TaskResult> {
  const { data } = await apiClient.get<TaskResult>(`/api/tasks/results/${taskId}/`);
  return data;
}

export async function getSchedules(): Promise<PeriodicTask[]> {
  const { data } = await apiClient.get<PeriodicTask[]>("/api/tasks/schedules/");
  return data;
}

export async function toggleSchedule(id: number, enabled: boolean): Promise<PeriodicTask> {
  const { data } = await apiClient.patch<PeriodicTask>(`/api/tasks/schedules/${id}/`, { enabled });
  return data;
}

export async function triggerTask(id: number): Promise<TriggerResponse> {
  const { data } = await apiClient.post<TriggerResponse>(`/api/tasks/schedules/${id}/trigger/`);
  return data;
}
