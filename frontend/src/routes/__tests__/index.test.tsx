import React from "react";
import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderWithQuery } from "@/test/render";
import {
  MOCK_PAGINATED_COMPANIES,
  MOCK_PAGINATED_SECTORS,
} from "@/test/handlers";

const BASE = "http://localhost:8004";

vi.mock("@tanstack/react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-router")>();
  return {
    ...actual,
    createFileRoute: () => (config: { component: React.ComponentType }) => config,
    Link: ({
      children,
      to,
      ...props
    }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { to?: string }) => (
      <a href={to} {...props}>
        {children}
      </a>
    ),
  };
});

vi.mock("@/components/layout/AppShell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/hooks/useAuth", () => ({
  useMe: () => ({ data: { email: "test@example.com" } }),
}));

async function renderDashboard() {
  const { Route } = await import("@/routes/index");
  const Page = Route.component as React.ComponentType;
  renderWithQuery(<Page />);
}

describe("Dashboard route", () => {
  it("renders the Dashboard heading", async () => {
    await renderDashboard();
    await waitFor(() => expect(screen.getByText("Dashboard")).toBeTruthy());
  });

  it("shows a welcome message with the user email", async () => {
    await renderDashboard();
    await waitFor(() =>
      expect(screen.getByText(/Welcome back.*test@example\.com/)).toBeTruthy(),
    );
  });

  it("shows the Companies Tracked stat card", async () => {
    await renderDashboard();
    await waitFor(() => expect(screen.getByText(/Companies Tracked/i)).toBeTruthy());
  });

  it("displays the company count from the API", async () => {
    server.use(
      http.get(`${BASE}/api/companies/`, () =>
        HttpResponse.json({ ...MOCK_PAGINATED_COMPANIES, count: 42 }),
      ),
    );
    await renderDashboard();
    await waitFor(() => expect(screen.getByText("42")).toBeTruthy());
  });

  it("shows the Sectors stat card", async () => {
    await renderDashboard();
    await waitFor(() => expect(screen.getByText(/^Sectors$/i)).toBeTruthy());
  });

  it("displays the sector count from the API", async () => {
    server.use(
      http.get(`${BASE}/api/companies/sectors/`, () =>
        HttpResponse.json({ ...MOCK_PAGINATED_SECTORS, count: 11 }),
      ),
    );
    await renderDashboard();
    await waitFor(() => expect(screen.getByText("11")).toBeTruthy());
  });

  it("shows the Market Map stat card", async () => {
    await renderDashboard();
    await waitFor(() => expect(screen.getAllByText(/Market Map/i).length).toBeGreaterThan(0));
  });

  it("shows the Quick Access section heading", async () => {
    await renderDashboard();
    await waitFor(() => expect(screen.getByText(/Quick Access/i)).toBeTruthy());
  });

  it("renders a Company Search quick-nav card", async () => {
    await renderDashboard();
    await waitFor(() => expect(screen.getByText("Company Search")).toBeTruthy());
  });

  it("renders a Task Monitor quick-nav card", async () => {
    await renderDashboard();
    await waitFor(() => expect(screen.getByText("Task Monitor")).toBeTruthy());
  });

  it("renders a Redis Monitor quick-nav card", async () => {
    await renderDashboard();
    await waitFor(() => expect(screen.getByText("Redis Monitor")).toBeTruthy());
  });

  it("does not render deprecated Sector Explorer or Industry Explorer cards", async () => {
    await renderDashboard();
    await waitFor(() => expect(screen.getByText("Dashboard")).toBeTruthy());
    expect(screen.queryByText("Sector Explorer")).toBeNull();
    expect(screen.queryByText("Industry Explorer")).toBeNull();
  });

  it("links the Sectors stat card to /market-map", async () => {
    await renderDashboard();
    await waitFor(() => {
      const links = screen.getAllByRole("link");
      const marketMapLinks = links.filter(
        (l) => (l as HTMLAnchorElement).href?.includes("market-map"),
      );
      expect(marketMapLinks.length).toBeGreaterThan(0);
    });
  });

  it("shows bootstrap progress bar when companies exist", async () => {
    server.use(
      http.get(`${BASE}/api/companies/`, ({ request }) => {
        const url = new URL(request.url);
        const isBootstrapped = url.searchParams.get("is_bootstrapped");
        if (isBootstrapped === "true") {
          return HttpResponse.json({ ...MOCK_PAGINATED_COMPANIES, count: 30 });
        }
        return HttpResponse.json({ ...MOCK_PAGINATED_COMPANIES, count: 50 });
      }),
    );
    await renderDashboard();
    await waitFor(() =>
      expect(screen.getByText(/30 of 50 bootstrapped/i)).toBeTruthy(),
    );
  });

  it("shows dash placeholder when company count is zero", async () => {
    server.use(
      http.get(`${BASE}/api/companies/`, () =>
        HttpResponse.json({ ...MOCK_PAGINATED_COMPANIES, count: 0, results: [] }),
      ),
    );
    await renderDashboard();
    await waitFor(() => expect(screen.getByText("Companies Tracked")).toBeTruthy());
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThan(0);
  });
});
