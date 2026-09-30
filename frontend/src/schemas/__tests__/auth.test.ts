import { describe, it, expect } from "vitest";
import { loginSchema, registerSchema } from "@/schemas/auth";

describe("loginSchema", () => {
  it("parses valid input", () => {
    const result = loginSchema.safeParse({ email: "user@example.com", password: "secret" });
    expect(result.success).toBe(true);
  });

  it("rejects invalid email", () => {
    const result = loginSchema.safeParse({ email: "not-an-email", password: "secret" });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0].path).toContain("email");
    }
  });

  it("rejects missing password", () => {
    const result = loginSchema.safeParse({ email: "user@example.com" });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0].path).toContain("password");
    }
  });
});

describe("registerSchema", () => {
  it("parses valid input with optional fields", () => {
    const result = registerSchema.safeParse({
      email: "new@example.com",
      password1: "securepass",
      password2: "securepass",
      first_name: "Alice",
    });
    expect(result.success).toBe(true);
  });

  it("rejects password shorter than 8 characters", () => {
    const result = registerSchema.safeParse({
      email: "x@example.com",
      password1: "short",
      password2: "short",
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0].path).toContain("password1");
    }
  });

  it("parses without optional fields", () => {
    const result = registerSchema.safeParse({
      email: "x@example.com",
      password1: "validpass",
      password2: "validpass",
    });
    expect(result.success).toBe(true);
  });

  it("rejects mismatched passwords", () => {
    const result = registerSchema.safeParse({
      email: "x@example.com",
      password1: "validpass1",
      password2: "differentpass",
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0].path).toContain("password2");
    }
  });
});
