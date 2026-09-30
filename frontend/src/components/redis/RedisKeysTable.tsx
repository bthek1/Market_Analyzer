import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getRedisKeys } from "@/api/redis";
import { queryKeys } from "@/api/queryKeys";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { RedisKeyValueDrawer } from "./RedisKeyValueDrawer";
import type { RedisKey } from "@/types/redis";

function TtlBadge({ ttl }: { ttl: number }) {
  if (ttl === -1) {
    return (
      <span className="text-xs text-muted-foreground font-mono">persistent</span>
    );
  }
  if (ttl === -2) {
    return <span className="text-xs text-destructive font-mono">expired</span>;
  }
  const color =
    ttl < 60 ? "text-destructive" : ttl < 300 ? "text-amber-500" : "text-green-500";
  const label =
    ttl >= 86400
      ? `${Math.floor(ttl / 86400)}d`
      : ttl >= 3600
        ? `${Math.floor(ttl / 3600)}h`
        : ttl >= 60
          ? `${Math.floor(ttl / 60)}m`
          : `${ttl}s`;
  return <span className={`text-xs font-mono ${color}`}>{label}</span>;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getPrefix(key: string): string {
  const idx = key.indexOf(":");
  return idx > -1 ? key.slice(0, idx) : key.split("-")[0];
}

function buildNamespaces(keys: RedisKey[]): { prefix: string; count: number }[] {
  const counts: Record<string, number> = {};
  for (const k of keys) {
    const p = getPrefix(k.key);
    counts[p] = (counts[p] ?? 0) + 1;
  }
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([prefix, count]) => ({ prefix, count }));
}

export function RedisKeysTable() {
  const [search, setSearch] = useState("");
  const [activePrefix, setActivePrefix] = useState<string | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: queryKeys.redis.keys(activePrefix ?? undefined),
    queryFn: () => getRedisKeys({ prefix: activePrefix ?? undefined, limit: 200 }),
    refetchInterval: 15_000,
  });

  const allKeys = data?.keys ?? [];
  const namespaces = buildNamespaces(allKeys);

  const filtered = search
    ? allKeys.filter((k) => k.key.toLowerCase().includes(search.toLowerCase()))
    : allKeys;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2 items-center">
        <button
          onClick={() => setActivePrefix(null)}
          className={`px-3 py-1 rounded-md text-xs font-medium transition-colors ${
            activePrefix === null
              ? "bg-primary text-primary-foreground"
              : "bg-muted text-muted-foreground hover:text-foreground"
          }`}
        >
          All{data ? ` (${data.count})` : ""}
        </button>
        {namespaces.map(({ prefix, count }) => (
          <button
            key={prefix}
            onClick={() => setActivePrefix(prefix === activePrefix ? null : prefix)}
            className={`px-3 py-1 rounded-md text-xs font-medium transition-colors ${
              activePrefix === prefix
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:text-foreground"
            }`}
          >
            {prefix} ({count})
          </button>
        ))}
      </div>

      <input
        type="text"
        placeholder="Search keys..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="w-full max-w-sm rounded-md border bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
      />

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading...</p>
      ) : (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Key</TableHead>
                <TableHead className="w-20">Type</TableHead>
                <TableHead className="w-24">TTL</TableHead>
                <TableHead className="w-24 text-right">Size</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-center text-muted-foreground text-sm py-8">
                    No keys found
                  </TableCell>
                </TableRow>
              ) : (
                filtered.map((k) => (
                  <TableRow
                    key={k.key}
                    className="cursor-pointer hover:bg-muted/50"
                    onClick={() => setSelectedKey(k.key)}
                  >
                    <TableCell className="font-mono text-xs max-w-xs truncate">{k.key}</TableCell>
                    <TableCell>
                      <span className="text-xs bg-muted px-1.5 py-0.5 rounded font-mono">
                        {k.type}
                      </span>
                    </TableCell>
                    <TableCell>
                      <TtlBadge ttl={k.ttl} />
                    </TableCell>
                    <TableCell className="text-right text-xs text-muted-foreground">
                      {formatBytes(k.size_bytes)}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}

      <RedisKeyValueDrawer
        redisKey={selectedKey}
        onClose={() => setSelectedKey(null)}
      />
    </div>
  );
}
