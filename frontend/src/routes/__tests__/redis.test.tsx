import React from "react";
import { describe, it, expect, vi } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { renderWithQuery } from "@/test/render";

vi.mock("@tanstack/react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-router")>();
  return {
    ...actual,
    createFileRoute: () => (config: { component: React.ComponentType }) => config,
    Link: ({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
      <a {...props}>{children}</a>
    ),
    Outlet: () => null,
  };
});

vi.mock("@/components/layout/AppShell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

describe("redis route", () => {
  it("exports a Route with a component", async () => {
    const mod = await import("@/routes/redis");
    expect(mod.Route).toBeDefined();
    expect(typeof mod.Route.component).toBe("function");
  });

  it("renders the Redis Monitor heading", async () => {
    const { Route } = await import("@/routes/redis");
    const Page = Route.component as React.ComponentType;
    renderWithQuery(<Page />);
    await waitFor(() => expect(screen.getByText("Redis Monitor")).toBeTruthy());
  });

  it("renders Server Info and Keys tabs", async () => {
    const { Route } = await import("@/routes/redis");
    const Page = Route.component as React.ComponentType;
    renderWithQuery(<Page />);
    await waitFor(() => {
      expect(screen.getByText("Server Info")).toBeTruthy();
      expect(screen.getByText("Keys")).toBeTruthy();
    });
  });

  it("shows stat cards on Server Info tab by default", async () => {
    const { Route } = await import("@/routes/redis");
    const Page = Route.component as React.ComponentType;
    renderWithQuery(<Page />);
    await waitFor(() => expect(screen.getByText("Redis Version")).toBeTruthy());
  });

  it("switching to Keys tab shows the keys table", async () => {
    const { Route } = await import("@/routes/redis");
    const Page = Route.component as React.ComponentType;
    renderWithQuery(<Page />);
    await waitFor(() => expect(screen.getByText("Keys")).toBeTruthy());
    fireEvent.click(screen.getByText("Keys"));
    await waitFor(() => expect(screen.getByText("celery-task-meta-abc123")).toBeTruthy());
  });

  it("switching back to Server Info hides the keys table", async () => {
    const { Route } = await import("@/routes/redis");
    const Page = Route.component as React.ComponentType;
    renderWithQuery(<Page />);
    fireEvent.click(screen.getByText("Keys"));
    await waitFor(() => expect(screen.getByText("celery-task-meta-abc123")).toBeTruthy());
    fireEvent.click(screen.getByText("Server Info"));
    await waitFor(() => expect(screen.getByText("Redis Version")).toBeTruthy());
    expect(screen.queryByText("celery-task-meta-abc123")).toBeNull();
  });
});
