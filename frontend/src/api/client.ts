import axios from "axios";
import { useAuthStore } from "@/store/auth";

const BASE_URL = import.meta.env.VITE_API_BASE_URL as string;

export const apiClient = axios.create({
  baseURL: BASE_URL,
  headers: { "Content-Type": "application/json" },
  withCredentials: true,
});

function forceLogout(): void {
  useAuthStore.getState().clearAuth();
  if (window.location.pathname !== "/login") {
    window.location.href = "/login";
  }
}

/**
 * Refresh the access token once. Returns the new token, or null after forcing a logout.
 *
 * Exported because the SSE paths use raw `fetch` - axios cannot stream a response body - and
 * so never reach the response interceptor below. Without this they are the only requests in
 * the app that do NOT silently recover from an expired access token, which on /chat showed
 * up as every reply coming back blank while the rest of the app worked.
 */
export async function refreshAccessToken(): Promise<string | null> {
  const refresh = localStorage.getItem("refresh_token");
  if (!refresh) {
    forceLogout();
    return null;
  }
  try {
    const { data } = await axios.post(
      `${BASE_URL}/api/auth/token/refresh/`,
      { refresh },
      { withCredentials: true },
    );
    localStorage.setItem("access_token", data.access);
    return data.access as string;
  } catch {
    forceLogout();
    return null;
  }
}

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    if (error.response?.status !== 401) {
      return Promise.reject(error);
    }

    if (!original || original._retry) {
      forceLogout();
      return Promise.reject(error);
    }

    const isRefreshRequest = String(original.url || "").includes(
      "/api/auth/token/refresh/",
    );
    const refresh = localStorage.getItem("refresh_token");

    if (!refresh || isRefreshRequest) {
      forceLogout();
      return Promise.reject(error);
    }

    if (error.response?.status === 401 && !original._retry) {
      original._retry = true;
      try {
        const { data } = await axios.post(
          `${BASE_URL}/api/auth/token/refresh/`,
          { refresh },
          { withCredentials: true },
        );
        localStorage.setItem("access_token", data.access);
        original.headers.Authorization = `Bearer ${data.access}`;
        return apiClient(original);
      } catch {
        forceLogout();
      }
    }
    return Promise.reject(error);
  },
);
