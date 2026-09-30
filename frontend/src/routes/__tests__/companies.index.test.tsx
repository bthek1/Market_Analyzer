import React from "react";
import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithQuery } from "@/test/render";

vi.mock("@tanstack/react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-router")>();
  return {
    ...actual,
    createFileRoute: () => (config: { component: React.ComponentType }) => config,
    useSearch: () => ({}),
    Link: ({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
      <a {...props}>{children}</a>
    ),
    Outlet: () => null,
  };
});

vi.mock("@/components/layout/AppShell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

describe("companies index route", () => {
  it("route module exports a component", async () => {
    const mod = await import("@/routes/companies.index");
    expect(mod.Route).toBeDefined();
    expect(typeof mod.Route.component).toBe("function");
  });

  it("renders the Companies heading", async () => {
    const { Route } = await import("@/routes/companies.index");
    const Page = Route.component as React.ComponentType;
    renderWithQuery(<Page />);
    await waitFor(() => expect(screen.getByText("Companies")).toBeTruthy());
  });

  it("renders the search input", async () => {
    const { Route } = await import("@/routes/companies.index");
    const Page = Route.component as React.ComponentType;
    renderWithQuery(<Page />);
    await waitFor(() =>
      expect(screen.getByPlaceholderText("Search symbol or name…")).toBeTruthy(),
    );
  });

  it("renders the Data loaded only filter", async () => {
    const { Route } = await import("@/routes/companies.index");
    const Page = Route.component as React.ComponentType;
    renderWithQuery(<Page />);
    await waitFor(() => expect(screen.getByText("Data loaded only")).toBeTruthy());
  });

  it("renders company rows from the API", async () => {
    const { Route } = await import("@/routes/companies.index");
    const Page = Route.component as React.ComponentType;
    renderWithQuery(<Page />);
    await waitFor(() => expect(screen.getByText("AAPL")).toBeTruthy());
  });
});
