import { describe, it, expect, beforeEach, vi } from "vitest";
import { useUIStore } from "@/store/ui";

describe("useUIStore", () => {
  beforeEach(() => {
    localStorage.clear();
    useUIStore.setState({ sidebarCollapsed: false });
  });

  it("defaults to an expanded sidebar", () => {
    expect(useUIStore.getState().sidebarCollapsed).toBe(false);
  });

  it("toggleSidebar flips the flag and persists it", () => {
    useUIStore.getState().toggleSidebar();
    expect(useUIStore.getState().sidebarCollapsed).toBe(true);
    expect(localStorage.getItem("sidebar_collapsed")).toBe("1");

    useUIStore.getState().toggleSidebar();
    expect(useUIStore.getState().sidebarCollapsed).toBe(false);
    expect(localStorage.getItem("sidebar_collapsed")).toBe("0");
  });

  it("setSidebarCollapsed writes the given value", () => {
    useUIStore.getState().setSidebarCollapsed(true);
    expect(useUIStore.getState().sidebarCollapsed).toBe(true);
    expect(localStorage.getItem("sidebar_collapsed")).toBe("1");
  });

  it("reads the persisted value on store creation", async () => {
    localStorage.setItem("sidebar_collapsed", "1");
    vi.resetModules();
    const fresh = await import("@/store/ui");
    expect(fresh.useUIStore.getState().sidebarCollapsed).toBe(true);
  });
});
