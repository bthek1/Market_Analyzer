import { describe, it, expect } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderWithQuery } from "@/test/render";
import { ScheduledTasksTable } from "@/components/tasks/ScheduledTasksTable";
import { MOCK_PERIODIC_TASK } from "@/test/handlers";

const BASE = "http://localhost:8004";

describe("ScheduledTasksTable", () => {
  it("renders task name and schedule", async () => {
    server.use(
      http.get(`${BASE}/api/tasks/schedules/`, () =>
        HttpResponse.json([MOCK_PERIODIC_TASK]),
      ),
    );
    renderWithQuery(<ScheduledTasksTable />);
    await waitFor(() =>
      expect(screen.getByText("yfinance-sync-company-profiles-daily")).toBeTruthy(),
    );
    expect(screen.getByText("every 24 hours")).toBeTruthy();
  });

  it("renders run count", async () => {
    server.use(
      http.get(`${BASE}/api/tasks/schedules/`, () =>
        HttpResponse.json([MOCK_PERIODIC_TASK]),
      ),
    );
    renderWithQuery(<ScheduledTasksTable />);
    await waitFor(() => expect(screen.getByText("42")).toBeTruthy());
  });

  it("formats last/next run as dd/mm/yyyy, hh:mm:ss AM/PM", async () => {
    server.use(
      http.get(`${BASE}/api/tasks/schedules/`, () =>
        HttpResponse.json([MOCK_PERIODIC_TASK]),
      ),
    );
    renderWithQuery(<ScheduledTasksTable />);
    await waitFor(() =>
      expect(
        screen.getAllByText(
          /^\d{2}\/\d{2}\/\d{4}, \d{2}:\d{2}:\d{2} (AM|PM)$/,
        ).length,
      ).toBeGreaterThan(0),
    );
  });

  it("renders enabled toggle switch", async () => {
    server.use(
      http.get(`${BASE}/api/tasks/schedules/`, () =>
        HttpResponse.json([MOCK_PERIODIC_TASK]),
      ),
    );
    renderWithQuery(<ScheduledTasksTable />);
    await waitFor(() => screen.getByRole("switch"));
    const toggle = screen.getByRole("switch");
    expect(toggle.getAttribute("aria-checked")).toBe("true");
  });

  it("calls toggle on switch click", async () => {
    let patchCalled = false;
    server.use(
      http.get(`${BASE}/api/tasks/schedules/`, () =>
        HttpResponse.json([MOCK_PERIODIC_TASK]),
      ),
      http.patch(`${BASE}/api/tasks/schedules/:id/`, async () => {
        patchCalled = true;
        return HttpResponse.json({ ...MOCK_PERIODIC_TASK, enabled: false });
      }),
    );
    renderWithQuery(<ScheduledTasksTable />);
    await waitFor(() => screen.getByRole("switch"));
    fireEvent.click(screen.getByRole("switch"));
    await waitFor(() => expect(patchCalled).toBe(true));
  });

  it("renders Run now button", async () => {
    server.use(
      http.get(`${BASE}/api/tasks/schedules/`, () =>
        HttpResponse.json([MOCK_PERIODIC_TASK]),
      ),
    );
    renderWithQuery(<ScheduledTasksTable />);
    await waitFor(() => expect(screen.getByText("Run now")).toBeTruthy());
  });

  it("calls trigger on Run now click", async () => {
    let triggerCalled = false;
    server.use(
      http.get(`${BASE}/api/tasks/schedules/`, () =>
        HttpResponse.json([MOCK_PERIODIC_TASK]),
      ),
      http.post(`${BASE}/api/tasks/schedules/:id/trigger/`, () => {
        triggerCalled = true;
        return HttpResponse.json({ task_id: "new-uuid" }, { status: 202 });
      }),
    );
    renderWithQuery(<ScheduledTasksTable />);
    await waitFor(() => screen.getByText("Run now"));
    fireEvent.click(screen.getByText("Run now"));
    await waitFor(() => expect(triggerCalled).toBe(true));
  });

  it("renders Next Run column header", async () => {
    server.use(
      http.get(`${BASE}/api/tasks/schedules/`, () =>
        HttpResponse.json([MOCK_PERIODIC_TASK]),
      ),
    );
    renderWithQuery(<ScheduledTasksTable />);
    await waitFor(() =>
      expect(screen.getByText("Next Run")).toBeTruthy(),
    );
  });

  it("renders next_run_at date when task is enabled", async () => {
    server.use(
      http.get(`${BASE}/api/tasks/schedules/`, () =>
        HttpResponse.json([{ ...MOCK_PERIODIC_TASK, enabled: true, next_run_at: "2026-05-29T00:00:00Z" }]),
      ),
    );
    renderWithQuery(<ScheduledTasksTable />);
    await waitFor(() =>
      expect(screen.getByText(/29\/05\/2026/)).toBeTruthy(),
    );
  });

  it("renders dash for next_run_at when task is disabled", async () => {
    server.use(
      http.get(`${BASE}/api/tasks/schedules/`, () =>
        HttpResponse.json([{ ...MOCK_PERIODIC_TASK, enabled: false, next_run_at: null }]),
      ),
    );
    renderWithQuery(<ScheduledTasksTable />);
    await waitFor(() => screen.getByRole("switch"));
    const cells = screen.getAllByText("—");
    expect(cells.length).toBeGreaterThan(0);
  });

  it("shows no scheduled tasks message when empty", async () => {
    server.use(
      http.get(`${BASE}/api/tasks/schedules/`, () => HttpResponse.json([])),
    );
    renderWithQuery(<ScheduledTasksTable />);
    await waitFor(() =>
      expect(screen.getByText("No scheduled tasks.")).toBeTruthy(),
    );
  });
});
