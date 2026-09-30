import { useQuery } from "@tanstack/react-query";
import { getHealth } from "@/api/system";
import { queryKeys } from "@/api/queryKeys";

export function useSystemStatus() {
  const { data, isError } = useQuery({
    queryKey: queryKeys.system.health(),
    queryFn: getHealth,
    refetchInterval: 30_000,
    retry: false,
  });

  const version = import.meta.env.DEV ? "dev" : (data?.version ?? "...");

  return {
    version,
    backendOk: !isError && data !== undefined,
    dbOk: !isError && (data?.db ?? false),
    redisOk: !isError && (data?.redis ?? false),
    celeryOk: !isError && (data?.celery ?? false),
    beatOk: !isError && (data?.beat ?? false),
    ollamaOk: !isError && (data?.ollama ?? false),
  };
}
