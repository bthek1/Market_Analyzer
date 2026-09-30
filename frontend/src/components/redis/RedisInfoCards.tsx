import { useQuery } from "@tanstack/react-query";
import { getRedisInfo } from "@/api/redis";
import { queryKeys } from "@/api/queryKeys";

function formatUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border bg-card p-4 space-y-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-lg font-semibold tabular-nums">{value}</p>
    </div>
  );
}

export function RedisInfoCards() {
  const { data, isLoading, dataUpdatedAt } = useQuery({
    queryKey: queryKeys.redis.info(),
    queryFn: getRedisInfo,
    refetchInterval: 10_000,
  });

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">Loading...</p>;
  }

  if (!data) return null;

  const totalKeys = Object.values(data.keyspace).reduce((sum, db) => sum + db.keys, 0);
  const totalExpires = Object.values(data.keyspace).reduce((sum, db) => sum + db.expires, 0);
  const hitRate =
    data.keyspace_hits + data.keyspace_misses > 0
      ? ((data.keyspace_hits / (data.keyspace_hits + data.keyspace_misses)) * 100).toFixed(1) + "%"
      : "—";

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        <StatCard label="Redis Version" value={data.redis_version} />
        <StatCard label="Uptime" value={formatUptime(data.uptime_in_seconds)} />
        <StatCard label="Connected Clients" value={data.connected_clients} />
        <StatCard label="Memory Used" value={data.used_memory_human} />
        <StatCard label="Memory Peak" value={data.used_memory_peak_human} />
        <StatCard label="Fragmentation Ratio" value={data.mem_fragmentation_ratio.toFixed(2)} />
        <StatCard label="Total Keys" value={totalKeys} />
        <StatCard label="Keys with Expiry" value={totalExpires} />
        <StatCard label="Ops/sec" value={data.instantaneous_ops_per_sec} />
        <StatCard label="Cache Hit Rate" value={hitRate} />
        <StatCard label="Total Commands" value={data.total_commands_processed.toLocaleString()} />
      </div>
      {dataUpdatedAt > 0 && (
        <p className="text-xs text-muted-foreground">
          Updated {new Date(dataUpdatedAt).toLocaleTimeString()} · auto-refreshes every 10s
        </p>
      )}
    </div>
  );
}
