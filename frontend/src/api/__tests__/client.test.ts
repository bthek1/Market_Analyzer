import { describe, it, expect, beforeEach, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { apiClient } from "@/api/client";
import { useAuthStore } from "@/store/auth";

const BASE_URL = "http://localhost:8004";

describe("apiClient interceptors", () => {
  beforeEach(() => {
    // localStorage.clear() is called globally in setup.ts afterEach
    useAuthStore.setState({ isAuthenticated: false, user: null });
  });

  it("attaches Authorization header when token is in localStorage", async () => {
    localStorage.setItem("access_token", "my-test-token");

    let capturedAuth: string | null = null;
    server.use(
      http.get(`${BASE_URL}/api/test/`, ({ request }) => {
        capturedAuth = request.headers.get("Authorization");
        return HttpResponse.json({ ok: true });
      })
    );

    await apiClient.get("/api/test/");
    expect(capturedAuth).toBe("Bearer my-test-token");
  });

  it("sends no Authorization header when no token in localStorage", async () => {
    let capturedAuth: string | null = "sentinel";
    server.use(
      http.get(`${BASE_URL}/api/test/`, ({ request }) => {
        capturedAuth = request.headers.get("Authorization");
        return HttpResponse.json({ ok: true });
      })
    );

    await apiClient.get("/api/test/");
    expect(capturedAuth).toBeNull();
  });

  it("retries with new token after 401 and successful refresh", async () => {
    localStorage.setItem("access_token", "expired-token");
    localStorage.setItem("refresh_token", "valid-refresh");

    let callCount = 0;
    server.use(
      http.get(`${BASE_URL}/api/protected/`, ({ request }) => {
        callCount++;
        const auth = request.headers.get("Authorization");
        if (auth === "Bearer expired-token") {
          return HttpResponse.json({ detail: "Unauthorized" }, { status: 401 });
        }
        return HttpResponse.json({ data: "secret" });
      }),
      http.post(`${BASE_URL}/api/auth/token/refresh/`, () =>
        HttpResponse.json({ access: "new-access-token" })
      )
    );

    const response = await apiClient.get("/api/protected/");
    expect(response.data).toEqual({ data: "secret" });
    expect(callCount).toBe(2);
    expect(localStorage.getItem("access_token")).toBe("new-access-token");
  });

  it("clears tokens on 401 when refresh also fails", async () => {
    localStorage.setItem("access_token", "expired");
    localStorage.setItem("refresh_token", "bad-refresh");

    const removeSpy = vi.spyOn(localStorage, "removeItem");

    server.use(
      http.get(`${BASE_URL}/api/protected/`, () =>
        HttpResponse.json({ detail: "Unauthorized" }, { status: 401 })
      ),
      http.post(`${BASE_URL}/api/auth/token/refresh/`, () =>
        HttpResponse.json({ detail: "Invalid refresh" }, { status: 401 })
      )
    );

    try {
      await apiClient.get("/api/protected/");
    } catch {
      // expected rejection
    }

    expect(removeSpy).toHaveBeenCalledWith("access_token");
    expect(removeSpy).toHaveBeenCalledWith("refresh_token");
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    removeSpy.mockRestore();
  });

  it("logs out on 401 when no refresh token exists", async () => {
    localStorage.setItem("access_token", "expired");
    useAuthStore.setState({
      isAuthenticated: true,
      user: {
        id: "u1",
        email: "user@example.com",
        first_name: "Alice",
        last_name: "Smith",
      },
    });

    server.use(
      http.get(`${BASE_URL}/api/protected/`, () =>
        HttpResponse.json({ detail: "Unauthorized" }, { status: 401 })
      )
    );

    try {
      await apiClient.get("/api/protected/");
    } catch {
      // expected rejection
    }

    expect(localStorage.getItem("access_token")).toBeNull();
    expect(localStorage.getItem("refresh_token")).toBeNull();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(useAuthStore.getState().user).toBeNull();
  });

  it("logs out when refresh endpoint returns 401", async () => {
    localStorage.setItem("access_token", "expired");
    localStorage.setItem("refresh_token", "bad-refresh");
    useAuthStore.setState({
      isAuthenticated: true,
      user: {
        id: "u1",
        email: "user@example.com",
        first_name: "Alice",
        last_name: "Smith",
      },
    });

    server.use(
      http.post(`${BASE_URL}/api/auth/token/refresh/`, () =>
        HttpResponse.json({ detail: "Invalid refresh" }, { status: 401 })
      )
    );

    await expect(
      apiClient.post("/api/auth/token/refresh/", { refresh: "bad-refresh" })
    ).rejects.toBeTruthy();

    expect(localStorage.getItem("access_token")).toBeNull();
    expect(localStorage.getItem("refresh_token")).toBeNull();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });

  it("does not call refresh endpoint when refresh token is missing", async () => {
    localStorage.setItem("access_token", "expired");

    let refreshCalled = false;
    server.use(
      http.get(`${BASE_URL}/api/protected/`, () =>
        HttpResponse.json({ detail: "Unauthorized" }, { status: 401 })
      ),
      http.post(`${BASE_URL}/api/auth/token/refresh/`, () => {
        refreshCalled = true;
        return HttpResponse.json({ access: "new-access-token" });
      })
    );

    await expect(apiClient.get("/api/protected/")).rejects.toBeTruthy();
    expect(refreshCalled).toBe(false);
  });
});
