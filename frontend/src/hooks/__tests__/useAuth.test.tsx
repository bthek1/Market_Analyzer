import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderHookWithQuery } from "@/test/render";
import { useLogin, useLogout, useMe, useRegister } from "@/hooks/useAuth";
import { useAuthStore } from "@/store/auth";

const BASE_URL = "http://localhost:8004";

const mockUser = {
  id: "u1",
  email: "user@example.com",
  first_name: "Alice",
  last_name: "Smith",
  date_joined: "2024-01-01T00:00:00Z",
};

const mockTokens = { access: "access-jwt", refresh: "refresh-jwt" };

const mockNavigate = vi.fn();

vi.mock("@tanstack/react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-router")>();
  return { ...actual, useNavigate: () => mockNavigate };
});

describe("useMe", () => {
  beforeEach(() => {
    useAuthStore.setState({ isAuthenticated: false, user: null });
  });

  it("stays idle when not authenticated", () => {
    const { result } = renderHookWithQuery(() => useMe());
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("fetches user data when authenticated", async () => {
    useAuthStore.setState({ isAuthenticated: true, user: null });
    server.use(
      http.get(`${BASE_URL}/api/accounts/me/`, () => HttpResponse.json(mockUser))
    );
    const { result } = renderHookWithQuery(() => useMe());
    await waitFor(() => expect(result.current.data?.email).toBe("user@example.com"));
  });
});

describe("useLogin", () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    useAuthStore.setState({ isAuthenticated: false, user: null });
  });

  it("stores tokens in localStorage and navigates on success", async () => {
    server.use(
      http.post(`${BASE_URL}/api/auth/login/`, () =>
        HttpResponse.json({ ...mockTokens, user: mockUser })
      ),
      http.get(`${BASE_URL}/api/accounts/me/`, () => HttpResponse.json(mockUser))
    );
    const { result } = renderHookWithQuery(() => useLogin());
    act(() => {
      result.current.mutate({ email: "user@example.com", password: "pass1234" });
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(localStorage.getItem("access_token")).toBe("access-jwt");
    expect(localStorage.getItem("refresh_token")).toBe("refresh-jwt");
    expect(mockNavigate).toHaveBeenCalledWith({ to: "/" });
  });

  it("marks as error when credentials are invalid", async () => {
    server.use(
      http.post(`${BASE_URL}/api/auth/login/`, () =>
        HttpResponse.json({ non_field_errors: ["Invalid credentials."] }, { status: 400 })
      )
    );
    const { result } = renderHookWithQuery(() => useLogin());
    act(() => {
      result.current.mutate({ email: "bad@example.com", password: "wrong" });
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(localStorage.getItem("access_token")).toBeNull();
  });
});

describe("useRegister", () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    useAuthStore.setState({ isAuthenticated: false, user: null });
  });

  it("stores tokens and navigates after registration", async () => {
    server.use(
      http.post(`${BASE_URL}/api/auth/registration/`, () =>
        HttpResponse.json(mockTokens, { status: 201 })
      ),
      http.get(`${BASE_URL}/api/accounts/me/`, () => HttpResponse.json(mockUser))
    );
    const { result } = renderHookWithQuery(() => useRegister());
    act(() => {
      result.current.mutate({
        email: "new@example.com",
        password1: "validpass1",
        password2: "validpass1",
      });
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(localStorage.getItem("access_token")).toBe("access-jwt");
    expect(mockNavigate).toHaveBeenCalledWith({ to: "/" });
  });
});

describe("useLogout", () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    useAuthStore.getState().setAuth(mockUser, "token", "refresh");
  });

  it("clears auth state and navigates to login", async () => {
    server.use(
      http.post(`${BASE_URL}/api/auth/logout/`, () =>
        HttpResponse.json({ detail: "Successfully logged out." })
      )
    );
    const { result } = renderHookWithQuery(() => useLogout());
    act(() => {
      result.current.mutate();
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(mockNavigate).toHaveBeenCalledWith({ to: "/login" });
  });
});
