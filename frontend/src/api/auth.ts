import { apiClient } from "./client";
import type { LoginResponse, RegisterRequest, RegisterResponse, User } from "@/types/auth";

export async function login(email: string, password: string): Promise<LoginResponse> {
  const { data } = await apiClient.post<LoginResponse>("/api/auth/login/", { email, password });
  return data;
}

export async function register(payload: RegisterRequest): Promise<RegisterResponse> {
  const { data } = await apiClient.post<RegisterResponse>("/api/auth/registration/", payload);
  return data;
}

export async function logout(): Promise<void> {
  await apiClient.post("/api/auth/logout/");
}

export async function refreshToken(refresh: string): Promise<{ access: string }> {
  const { data } = await apiClient.post<{ access: string }>("/api/auth/token/refresh/", {
    refresh,
  });
  return data;
}

export async function getMe(): Promise<User> {
  const { data } = await apiClient.get<User>("/api/accounts/me/");
  return data;
}
