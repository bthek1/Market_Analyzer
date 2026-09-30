import React from "react";
import { describe, it, expect } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderWithQuery } from "@/test/render";
import { SyncPanel } from "@/components/companies/SyncPanel";
import { MOCK_SYNC_STATUS, MOCK_TASK_RESULT } from "@/test/handlers";

const BASE = "http://localhost:8004";

// ---------------------------------------------------------------------------
// timeAgo display standard
// ---------------------------------------------------------------------------

describe("timeAgo display", () => {
  it("shows 'just now' for timestamps under 60s old", async () => {
    const ts = new Date(Date.now() - 30_000).toISOString();
    server.use(
      http.get(`${BASE}/api/companies/:id/sync-status/`, () =>
        HttpResponse.json({ ...MOCK_SYNC_STATUS, snapshot: ts }),
      ),
    );
    renderWithQuery(<SyncPanel companyId={1} dataType="snapshot" />);
    await waitFor(() => expect(screen.getByText(/just now/)).toBeTruthy());
  });

  it("shows 'Xm ago' for timestamps 1-59m old", async () => {
    const ts = new Date(Date.now() - 45 * 60_000).toISOString();
    server.use(
      http.get(`${BASE}/api/companies/:id/sync-status/`, () =>
        HttpResponse.json({ ...MOCK_SYNC_STATUS, snapshot: ts }),
      ),
    );
    renderWithQuery(<SyncPanel companyId={1} dataType="snapshot" />);
    await waitFor(() => expect(screen.getByText(/45m ago/)).toBeTruthy());
  });

  it("shows 'Xh ago' for timestamps 1-23h old", async () => {
    const ts = new Date(Date.now() - 3 * 60 * 60_000).toISOString();
    server.use(
      http.get(`${BASE}/api/companies/:id/sync-status/`, () =>
        HttpResponse.json({ ...MOCK_SYNC_STATUS, snapshot: ts }),
      ),
    );
    renderWithQuery(<SyncPanel companyId={1} dataType="snapshot" />);
    await waitFor(() => expect(screen.getByText(/3h ago/)).toBeTruthy());
  });

  it("shows 'Xd ago' for timestamps over 24h old", async () => {
    const ts = new Date(Date.now() - 2 * 24 * 60 * 60_000).toISOString();
    server.use(
      http.get(`${BASE}/api/companies/:id/sync-status/`, () =>
        HttpResponse.json({ ...MOCK_SYNC_STATUS, snapshot: ts }),
      ),
    );
    renderWithQuery(<SyncPanel companyId={1} dataType="snapshot" />);
    await waitFor(() => expect(screen.getByText(/2d ago/)).toBeTruthy());
  });

  it("shows 'Never synced' when timestamp is null", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/sync-status/`, () =>
        HttpResponse.json({ ...MOCK_SYNC_STATUS, earnings: null }),
      ),
    );
    renderWithQuery(<SyncPanel companyId={1} dataType="earnings" />);
    await waitFor(() => expect(screen.getByText(/Never synced/)).toBeTruthy());
  });

  it("shows a date string (not negative) for future timestamps", async () => {
    const futureTs = new Date(Date.now() + 24 * 60 * 60_000).toISOString();
    server.use(
      http.get(`${BASE}/api/companies/:id/sync-status/`, () =>
        HttpResponse.json({ ...MOCK_SYNC_STATUS, snapshot: futureTs }),
      ),
    );
    renderWithQuery(<SyncPanel companyId={1} dataType="snapshot" />);
    await waitFor(() => {
      const el = screen.getByText(/Last synced:/);
      expect(el.textContent).not.toMatch(/-\d+/);
    });
  });
});

describe("SyncPanel", () => {
  it("renders 'Never synced' when status is null for the data type", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/sync-status/`, () =>
        HttpResponse.json({ ...MOCK_SYNC_STATUS, dividends: null }),
      ),
    );
    renderWithQuery(<SyncPanel companyId={1} dataType="dividends" />);
    await waitFor(() => expect(screen.getByText(/Never synced/)).toBeTruthy());
  });

  it("renders 'Last synced' when timestamp is present", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/sync-status/`, () =>
        HttpResponse.json(MOCK_SYNC_STATUS),
      ),
    );
    renderWithQuery(<SyncPanel companyId={1} dataType="snapshot" />);
    await waitFor(() => expect(screen.getByText(/Last synced:/)).toBeTruthy());
  });

  it("renders 'Sync' button", async () => {
    renderWithQuery(<SyncPanel companyId={1} dataType="dividends" />);
    await waitFor(() => expect(screen.getByRole("button", { name: /^Sync$/i })).toBeTruthy());
  });

  it("clicking Sync fires the trigger mutation", async () => {
    let triggered = false;
    server.use(
      http.post(`${BASE}/api/companies/:id/sync/:dataType/`, () => {
        triggered = true;
        return HttpResponse.json({ task_id: "task-abc", status: "queued" }, { status: 202 });
      }),
    );
    renderWithQuery(<SyncPanel companyId={1} dataType="dividends" />);
    const btn = await screen.findByRole("button", { name: /^Sync$/i });
    fireEvent.click(btn);
    await waitFor(() => expect(triggered).toBe(true));
  });

  it("shows 'Syncing...' and disables button while task is in progress", async () => {
    server.use(
      http.post(`${BASE}/api/companies/:id/sync/:dataType/`, () =>
        HttpResponse.json({ task_id: "task-running", status: "queued" }, { status: 202 }),
      ),
      http.get(`${BASE}/api/tasks/results/:taskId/`, () =>
        HttpResponse.json({ ...MOCK_TASK_RESULT, task_id: "task-running", status: "PENDING" }),
      ),
    );
    renderWithQuery(<SyncPanel companyId={1} dataType="dividends" />);
    const btn = await screen.findByRole("button", { name: /^Sync$/i });
    fireEvent.click(btn);
    await waitFor(() => expect(screen.getByText(/Syncing/i)).toBeTruthy());
    expect(screen.getByRole("button")).toHaveProperty("disabled", true);
  });

  it("shows 'Sync failed' message when task fails", async () => {
    server.use(
      http.post(`${BASE}/api/companies/:id/sync/:dataType/`, () =>
        HttpResponse.json({ task_id: "task-fail", status: "queued" }, { status: 202 }),
      ),
      http.get(`${BASE}/api/tasks/results/:taskId/`, () =>
        HttpResponse.json({ ...MOCK_TASK_RESULT, task_id: "task-fail", status: "FAILURE" }),
      ),
    );
    renderWithQuery(<SyncPanel companyId={1} dataType="dividends" />);
    const btn = await screen.findByRole("button", { name: /^Sync$/i });
    fireEvent.click(btn);
    await waitFor(() => expect(screen.getByText(/Sync failed/)).toBeTruthy(), { timeout: 5000 });
  });
});
