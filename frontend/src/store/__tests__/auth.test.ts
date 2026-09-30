import { describe, it, expect, beforeEach } from "vitest";
import { useAuthStore } from "@/store/auth";

const mockUser = {
  id: "abc-123",
  email: "test@example.com",
  first_name: "Test",
  last_name: "User",
};

describe("useAuthStore", () => {
  beforeEach(() => {
    useAuthStore.setState({ isAuthenticated: false, user: null });
  });

  it("initial state is unauthenticated when no token in localStorage", () => {
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(useAuthStore.getState().user).toBeNull();
  });

  it("setAuth stores tokens in localStorage and marks authenticated", () => {
    useAuthStore.getState().setAuth(mockUser, "access-token-123", "refresh-token-456");
    expect(localStorage.getItem("access_token")).toBe("access-token-123");
    expect(localStorage.getItem("refresh_token")).toBe("refresh-token-456");
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
    expect(useAuthStore.getState().user?.email).toBe("test@example.com");
  });

  it("clearAuth removes tokens from localStorage and marks unauthenticated", () => {
    useAuthStore.getState().setAuth(mockUser, "access-token-123", "refresh-token-456");
    useAuthStore.getState().clearAuth();
    expect(localStorage.getItem("access_token")).toBeNull();
    expect(localStorage.getItem("refresh_token")).toBeNull();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(useAuthStore.getState().user).toBeNull();
  });
});
