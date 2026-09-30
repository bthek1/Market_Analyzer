import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { renderWithQuery } from "@/test/render";
import { AppShell } from "@/components/layout/AppShell";
import { useUIStore } from "@/store/ui";

vi.mock("@tanstack/react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-router")>();
  return {
    ...actual,
    Link: ({
      to,
      children,
      ...props
    }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { to: string }) => (
      <a href={to} {...props}>
        {children}
      </a>
    ),
    useRouterState: () => ({ location: { pathname: "/" } }),
  };
});

vi.mock("@/hooks/useAuth", () => ({
  useMe: () => ({ data: { email: "test@example.com" } }),
  useLogout: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@/components/layout/StatusOverlay", () => ({
  StatusBar: () => <div data-testid="status-bar" />,
}));

describe("AppShell", () => {
  beforeEach(() => {
    localStorage.clear();
    useUIStore.setState({ sidebarCollapsed: false });
  });

  it("renders nav links in the sidebar, not the topbar", () => {
    renderWithQuery(
      <AppShell>
        <p>page body</p>
      </AppShell>
    );
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(nav.closest("aside")).not.toBeNull();
    for (const label of ["Dashboard", "Companies", "Knowledge", "Code Graph"]) {
      expect(nav.textContent).toContain(label);
    }
    // The topbar keeps only the user actions.
    const header = document.querySelector("header");
    expect(header?.textContent).toContain("Logout");
    expect(header?.textContent).not.toContain("Companies");
  });

  it("renders the page body, user email and status bar", () => {
    renderWithQuery(
      <AppShell>
        <p>page body</p>
      </AppShell>
    );
    expect(screen.getByText("page body")).toBeTruthy();
    expect(screen.getByText("test@example.com")).toBeTruthy();
    expect(screen.getByTestId("status-bar")).toBeTruthy();
  });

  it("collapsing the sidebar updates the shared store", () => {
    renderWithQuery(
      <AppShell>
        <p>page body</p>
      </AppShell>
    );
    fireEvent.click(screen.getByLabelText("Collapse sidebar"));
    expect(useUIStore.getState().sidebarCollapsed).toBe(true);
    expect(localStorage.getItem("sidebar_collapsed")).toBe("1");
    expect(screen.getAllByLabelText("Expand sidebar").length).toBeGreaterThan(0);
  });

  it("starts collapsed when the stored preference says so", () => {
    useUIStore.setState({ sidebarCollapsed: true });
    renderWithQuery(
      <AppShell>
        <p>page body</p>
      </AppShell>
    );
    expect(screen.getAllByLabelText("Expand sidebar").length).toBeGreaterThan(0);
    expect(screen.queryByLabelText("Collapse sidebar")).toBeNull();
  });

  it("the mobile menu button opens the drawer and the backdrop closes it", () => {
    renderWithQuery(
      <AppShell>
        <p>page body</p>
      </AppShell>
    );
    expect(screen.queryByTestId("sidebar-backdrop")).toBeNull();

    fireEvent.click(screen.getByLabelText("Open navigation"));
    expect(screen.getByTestId("sidebar-backdrop")).toBeTruthy();

    fireEvent.click(screen.getByTestId("sidebar-backdrop"));
    expect(screen.queryByTestId("sidebar-backdrop")).toBeNull();
  });

  it("closes the drawer when a nav link is followed", () => {
    renderWithQuery(
      <AppShell>
        <p>page body</p>
      </AppShell>
    );
    fireEvent.click(screen.getByLabelText("Open navigation"));
    fireEvent.click(screen.getByText("Tasks"));
    expect(screen.queryByTestId("sidebar-backdrop")).toBeNull();
  });
});
