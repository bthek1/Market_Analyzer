import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { login, register, logout, refreshToken, getMe } from "@/api/auth";

const BASE_URL = "http://localhost:8004";

const mockUser = {
  id: "abc-123",
  email: "user@example.com",
  first_name: "Alice",
  last_name: "Smith",
  date_joined: "2024-01-01T00:00:00Z",
};

const mockTokens = { access: "access-jwt", refresh: "refresh-jwt" };

describe("login", () => {
  it("posts to /api/auth/login/ and returns tokens + user", async () => {
    server.use(
      http.post(`${BASE_URL}/api/auth/login/`, () =>
        HttpResponse.json({ ...mockTokens, user: mockUser })
      )
    );

    const result = await login("user@example.com", "pass1234");
    expect(result.access).toBe("access-jwt");
    expect(result.refresh).toBe("refresh-jwt");
    expect(result.user.email).toBe("user@example.com");
  });

  it("throws on 400 bad credentials", async () => {
    server.use(
      http.post(`${BASE_URL}/api/auth/login/`, () =>
        HttpResponse.json({ non_field_errors: ["Invalid credentials"] }, { status: 400 })
      )
    );

    await expect(login("bad@example.com", "wrong")).rejects.toThrow();
  });
});

describe("register", () => {
  it("posts to /api/auth/registration/ and returns tokens", async () => {
    server.use(
      http.post(`${BASE_URL}/api/auth/registration/`, () =>
        HttpResponse.json(mockTokens, { status: 201 })
      )
    );

    const result = await register({
      email: "new@example.com",
      password1: "securepass!",
      password2: "securepass!",
    });
    expect(result.access).toBe("access-jwt");
    expect(result.refresh).toBe("refresh-jwt");
  });

  it("throws on 400 duplicate email", async () => {
    server.use(
      http.post(`${BASE_URL}/api/auth/registration/`, () =>
        HttpResponse.json({ email: ["A user is already registered."] }, { status: 400 })
      )
    );

    await expect(
      register({ email: "dup@example.com", password1: "pass!", password2: "pass!" })
    ).rejects.toThrow();
  });
});

describe("logout", () => {
  it("posts to /api/auth/logout/ and resolves", async () => {
    let called = false;
    server.use(
      http.post(`${BASE_URL}/api/auth/logout/`, () => {
        called = true;
        return HttpResponse.json({ detail: "Successfully logged out." });
      })
    );

    await logout();
    expect(called).toBe(true);
  });
});

describe("refreshToken", () => {
  it("posts to /api/auth/token/refresh/ and returns new access token", async () => {
    server.use(
      http.post(`${BASE_URL}/api/auth/token/refresh/`, () =>
        HttpResponse.json({ access: "new-access-jwt" })
      )
    );

    const result = await refreshToken("refresh-jwt");
    expect(result.access).toBe("new-access-jwt");
  });
});

describe("getMe", () => {
  it("gets /api/accounts/me/ and returns user", async () => {
    server.use(
      http.get(`${BASE_URL}/api/accounts/me/`, () => HttpResponse.json(mockUser))
    );

    const result = await getMe();
    expect(result.email).toBe("user@example.com");
    expect(result.id).toBe("abc-123");
  });

  it("throws on 401 when unauthenticated", async () => {
    server.use(
      http.get(`${BASE_URL}/api/accounts/me/`, () =>
        HttpResponse.json({ detail: "Authentication credentials were not provided." }, { status: 401 })
      )
    );

    await expect(getMe()).rejects.toThrow();
  });
});
