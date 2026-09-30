import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getLatestSummary, getSummaryList, triggerSummaryGeneration } from "@/api/companies";
import { queryKeys } from "@/api/queryKeys";
import type { CompanySummary, PaginatedResponse } from "@/types/companies";

export function useCompanySummary(symbol: string): {
  summary: CompanySummary | undefined;
  isLoading: boolean;
  isError: boolean;
  notFound: boolean;
  generate: () => void;
  isGenerating: boolean;
} {
  const queryClient = useQueryClient();

  const { data, isLoading, isError, error } = useQuery({
    queryKey: queryKeys.companies.summaryLatest(symbol),
    queryFn: () => getLatestSummary(symbol),
    retry: false,
  });

  const mutation = useMutation({
    mutationFn: () => triggerSummaryGeneration(symbol),
    onSuccess: () => {
      let attempts = 0;
      const interval = setInterval(() => {
        attempts++;
        queryClient.invalidateQueries({ queryKey: queryKeys.companies.summaryLatest(symbol) });
        queryClient.invalidateQueries({ queryKey: queryKeys.companies.summaryList(symbol) });
        if (attempts >= 10) clearInterval(interval);
      }, 3000);
    },
  });

  const notFound =
    isError && (error as { response?: { status?: number } })?.response?.status === 404;

  return {
    summary: data,
    isLoading,
    isError,
    notFound,
    generate: mutation.mutate,
    isGenerating: mutation.isPending,
  };
}

export function useCompanySummaryList(symbol: string): {
  summaries: CompanySummary[];
  isLoading: boolean;
} {
  const { data, isLoading } = useQuery<PaginatedResponse<CompanySummary>>({
    queryKey: queryKeys.companies.summaryList(symbol),
    queryFn: () => getSummaryList(symbol),
    retry: false,
  });

  return { summaries: data?.results ?? [], isLoading };
}
