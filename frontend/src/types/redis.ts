export interface RedisKeyspaceDb {
  keys: number;
  expires: number;
}

export interface RedisInfo {
  redis_version: string;
  uptime_in_seconds: number;
  connected_clients: number;
  used_memory_human: string;
  used_memory_peak_human: string;
  mem_fragmentation_ratio: number;
  total_commands_processed: number;
  instantaneous_ops_per_sec: number;
  keyspace_hits: number;
  keyspace_misses: number;
  keyspace: Record<string, RedisKeyspaceDb>;
}

export interface RedisKey {
  key: string;
  type: string;
  ttl: number;
  size_bytes: number;
}

export interface RedisKeysResponse {
  keys: RedisKey[];
  count: number;
}

export interface RedisKeyValue {
  type: string;
  value: string | string[] | [string, number][] | Record<string, string> | null;
}
