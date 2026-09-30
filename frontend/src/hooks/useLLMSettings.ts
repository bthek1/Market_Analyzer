import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchLLMSettings, updateLLMSettings } from "@/api/llm";
import { queryKeys } from "@/api/queryKeys";
import type { LLMSettingsUpdate } from "@/types/llm";

export function useLLMSettings() {
  return useQuery({
    queryKey: queryKeys.llm.settings(),
    queryFn: fetchLLMSettings,
  });
}

export function useUpdateLLMSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: LLMSettingsUpdate) => updateLLMSettings(payload),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.llm.settings(), data);
    },
  });
}
