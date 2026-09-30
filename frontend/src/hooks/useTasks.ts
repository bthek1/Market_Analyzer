import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getSchedules, getTaskResult, getTaskResults, toggleSchedule, triggerTask } from "@/api/tasks";
import { queryKeys } from "@/api/queryKeys";

export function useTaskResults(status?: string) {
  return useQuery({
    queryKey: queryKeys.tasks.results(status),
    queryFn: () => getTaskResults(status),
    refetchInterval: 10_000,
  });
}

export function useTaskResult(taskId: string) {
  return useQuery({
    queryKey: queryKeys.tasks.result(taskId),
    queryFn: () => getTaskResult(taskId),
    enabled: !!taskId,
  });
}

export function useSchedules() {
  return useQuery({
    queryKey: queryKeys.tasks.schedules(),
    queryFn: getSchedules,
    refetchInterval: 30_000,
  });
}

export function useToggleSchedule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      toggleSchedule(id, enabled),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks.schedules() });
    },
  });
}

export function useTriggerTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => triggerTask(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks.results() });
    },
  });
}
