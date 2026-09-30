import { apiClient } from "./client";
import type { RedisInfo, RedisKeyValue, RedisKeysResponse } from "@/types/redis";

export async function getRedisInfo(): Promise<RedisInfo> {
  const { data } = await apiClient.get<RedisInfo>("/api/redis/info/");
  return data;
}

export async function getRedisKeys(params?: {
  prefix?: string;
  limit?: number;
}): Promise<RedisKeysResponse> {
  const { data } = await apiClient.get<RedisKeysResponse>("/api/redis/keys/", { params });
  return data;
}

export async function getRedisKeyValue(key: string): Promise<RedisKeyValue> {
  const { data } = await apiClient.get<RedisKeyValue>(
    `/api/redis/keys/${encodeURIComponent(key)}/value/`,
  );
  return data;
}
