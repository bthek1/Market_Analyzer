import { useQuery } from "@tanstack/react-query";
import { getRedisKeyValue } from "@/api/redis";
import { queryKeys } from "@/api/queryKeys";

interface Props {
  redisKey: string | null;
  onClose: () => void;
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "string") {
    try {
      return JSON.stringify(JSON.parse(value), null, 2);
    } catch {
      return value;
    }
  }
  return JSON.stringify(value, null, 2);
}

export function RedisKeyValueDrawer({ redisKey, onClose }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.redis.keyValue(redisKey ?? ""),
    queryFn: () => getRedisKeyValue(redisKey!),
    enabled: redisKey !== null,
  });

  if (!redisKey) return null;

  return (
    <div className="fixed inset-0 z-50 flex" onClick={onClose}>
      <div className="flex-1" />
      <div
        className="w-full max-w-xl bg-background border-l shadow-xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <div className="min-w-0 flex-1">
            <p className="text-xs text-muted-foreground mb-0.5">Key</p>
            <p className="text-sm font-mono font-medium truncate">{redisKey}</p>
          </div>
          <button
            onClick={onClose}
            className="ml-4 text-muted-foreground hover:text-foreground text-lg leading-none"
          >
            ✕
          </button>
        </div>
        <div className="flex-1 overflow-auto p-6">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : data ? (
            <div className="space-y-3">
              <div className="flex gap-2 items-center">
                <span className="text-xs text-muted-foreground">Type:</span>
                <span className="text-xs font-mono bg-muted px-2 py-0.5 rounded">
                  {data.type}
                </span>
              </div>
              <pre className="text-xs font-mono bg-muted rounded p-4 overflow-auto whitespace-pre-wrap break-all">
                {renderValue(data.value)}
              </pre>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
