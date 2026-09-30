import { describe, it, expect } from "vitest";
import { NAV_LINKS, isNavActive } from "@/components/layout/nav";

describe("NAV_LINKS", () => {
  it("lists every authenticated page once", () => {
    expect(NAV_LINKS.map((l) => l.to)).toEqual([
      "/",
      "/companies",
      "/market-map",
      "/tasks",
      "/redis",
      "/agents",
      "/chat",
      "/browse",
      "/knowledge",
      "/code-graph",
    ]);
  });

  it("lists Browse as a sibling of Agents, not a sub-route of it", () => {
    // /browse is its own page; nothing should make it a child of the Agents workspace.
    expect(isNavActive("/agents", "/browse")).toBe(false);
    expect(isNavActive("/browse", "/browse")).toBe(true);
  });

  it("gives every entry a label and an icon", () => {
    for (const link of NAV_LINKS) {
      expect(link.label.length).toBeGreaterThan(0);
      expect(typeof link.icon).not.toBe("undefined");
    }
  });

  it("uses a distinct icon per entry (the collapsed rail is icon-only)", () => {
    expect(new Set(NAV_LINKS.map((l) => l.icon)).size).toBe(NAV_LINKS.length);
  });
});

describe("isNavActive", () => {
  it("matches an exact path", () => {
    expect(isNavActive("/companies", "/companies")).toBe(true);
  });

  it("matches a sub-route to its parent link", () => {
    expect(isNavActive("/companies", "/companies/abc-123")).toBe(true);
  });

  it("does not match an unrelated path with the same prefix", () => {
    expect(isNavActive("/companies", "/companies-archive")).toBe(false);
  });

  it("matches the dashboard only at the root", () => {
    expect(isNavActive("/", "/")).toBe(true);
    expect(isNavActive("/", "/companies")).toBe(false);
    expect(isNavActive("/", "/knowledge")).toBe(false);
  });

  it("does not mark other links active on a sub-route", () => {
    expect(isNavActive("/tasks", "/companies/abc-123")).toBe(false);
  });
});
