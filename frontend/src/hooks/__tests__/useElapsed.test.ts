import { describe, it, expect } from "vitest";
import { renderHook } from "@testing-library/react";
import { useElapsed } from "@/hooks/useElapsed";

describe("useElapsed", () => {
  it("starts null when idle", () => {
    const { result } = renderHook(({ running }) => useElapsed(running), {
      initialProps: { running: false },
    });
    expect(result.current).toBeNull();
  });

  it("stays null while running (timer not yet frozen)", () => {
    const { result } = renderHook(({ running }) => useElapsed(running), {
      initialProps: { running: true },
    });
    expect(result.current).toBeNull();
  });

  it("freezes a non-negative elapsed value on the falling edge", () => {
    const { result, rerender } = renderHook(({ running }) => useElapsed(running), {
      initialProps: { running: false },
    });

    rerender({ running: true });
    expect(result.current).toBeNull();

    rerender({ running: false });
    expect(result.current).not.toBeNull();
    expect(result.current).toBeGreaterThanOrEqual(0);
  });

  it("clears the frozen value when a new run starts", () => {
    const { result, rerender } = renderHook(({ running }) => useElapsed(running), {
      initialProps: { running: false },
    });

    rerender({ running: true });
    rerender({ running: false });
    expect(result.current).not.toBeNull();

    rerender({ running: true });
    expect(result.current).toBeNull();
  });
});
