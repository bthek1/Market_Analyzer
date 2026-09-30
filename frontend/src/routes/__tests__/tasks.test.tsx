import React from "react";
import { describe, it, expect, vi } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { renderWithQuery } from "@/test/render";

vi.mock("@tanstack/react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-router")>();
  return {
    ...actual,
    createFileRoute: () => (config: { component: React.ComponentType }) => config,
  };
});

vi.mock("@/components/layout/AppShell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/components/tasks/TaskResultsTable", () => ({
  TaskResultsTable: () => <div data-testid="task-results-table">Task Results</div>,
}));

vi.mock("@/components/tasks/ScheduledTasksTable", () => ({
  ScheduledTasksTable: () => <div data-testid="scheduled-tasks-table">Scheduled Tasks</div>,
}));

vi.mock("@/components/companies/SyncFreshnessChart", () => ({
  SyncFreshnessWidget: () => <div data-testid="sync-freshness-widget">Sync Freshness</div>,
}));

vi.mock("@/components/companies/SummaryProgressWidget", () => ({
  SummaryProgressWidget: () => (
    <div data-testid="summary-progress-widget">Summary Progress</div>
  ),
}));

async function renderTasksPage() {
  const { Route } = await import("@/routes/tasks");
  const Page = Route.component as React.ComponentType;
  renderWithQuery(<Page />);
}

describe("Tasks route", () => {
  it("renders the Celery Tasks heading", async () => {
    await renderTasksPage();
    await waitFor(() => expect(screen.getByText("Celery Tasks")).toBeTruthy());
  });

  it("renders all four tab labels", async () => {
    await renderTasksPage();
    await waitFor(() => {
      expect(screen.getByText("Recent Executions")).toBeTruthy();
      expect(screen.getByText("Schedules")).toBeTruthy();
      expect(screen.getByText("Data Sync Freshness")).toBeTruthy();
      expect(screen.getByText("AI Summary Progress")).toBeTruthy();
    });
  });

  it("shows TaskResultsTable by default", async () => {
    await renderTasksPage();
    await waitFor(() => expect(screen.getByTestId("task-results-table")).toBeTruthy());
    expect(screen.queryByTestId("scheduled-tasks-table")).toBeNull();
    expect(screen.queryByTestId("sync-freshness-widget")).toBeNull();
  });

  it("shows ScheduledTasksTable when Schedules tab is clicked", async () => {
    await renderTasksPage();
    await waitFor(() => expect(screen.getByText("Schedules")).toBeTruthy());
    fireEvent.click(screen.getByText("Schedules"));
    await waitFor(() => expect(screen.getByTestId("scheduled-tasks-table")).toBeTruthy());
    expect(screen.queryByTestId("task-results-table")).toBeNull();
    expect(screen.queryByTestId("sync-freshness-widget")).toBeNull();
  });

  it("shows SyncFreshnessWidget when Data Sync Freshness tab is clicked", async () => {
    await renderTasksPage();
    await waitFor(() => expect(screen.getByText("Data Sync Freshness")).toBeTruthy());
    fireEvent.click(screen.getByText("Data Sync Freshness"));
    await waitFor(() => expect(screen.getByTestId("sync-freshness-widget")).toBeTruthy());
    expect(screen.queryByTestId("task-results-table")).toBeNull();
    expect(screen.queryByTestId("scheduled-tasks-table")).toBeNull();
  });

  it("switches back to Recent Executions from another tab", async () => {
    await renderTasksPage();
    await waitFor(() => expect(screen.getByText("Data Sync Freshness")).toBeTruthy());
    fireEvent.click(screen.getByText("Data Sync Freshness"));
    await waitFor(() => expect(screen.getByTestId("sync-freshness-widget")).toBeTruthy());
    fireEvent.click(screen.getByText("Recent Executions"));
    await waitFor(() => expect(screen.getByTestId("task-results-table")).toBeTruthy());
    expect(screen.queryByTestId("sync-freshness-widget")).toBeNull();
  });

  it("shows SummaryProgressWidget when AI Summary Progress tab is clicked", async () => {
    await renderTasksPage();
    await waitFor(() => expect(screen.getByText("AI Summary Progress")).toBeTruthy());
    fireEvent.click(screen.getByText("AI Summary Progress"));
    await waitFor(() =>
      expect(screen.getByTestId("summary-progress-widget")).toBeTruthy(),
    );
    expect(screen.queryByTestId("task-results-table")).toBeNull();
    expect(screen.queryByTestId("sync-freshness-widget")).toBeNull();
  });

  it("hides SummaryProgressWidget when switching away from AI Summary Progress tab", async () => {
    await renderTasksPage();
    await waitFor(() => expect(screen.getByText("AI Summary Progress")).toBeTruthy());
    fireEvent.click(screen.getByText("AI Summary Progress"));
    await waitFor(() =>
      expect(screen.getByTestId("summary-progress-widget")).toBeTruthy(),
    );
    fireEvent.click(screen.getByText("Recent Executions"));
    await waitFor(() => expect(screen.getByTestId("task-results-table")).toBeTruthy());
    expect(screen.queryByTestId("summary-progress-widget")).toBeNull();
  });
});
