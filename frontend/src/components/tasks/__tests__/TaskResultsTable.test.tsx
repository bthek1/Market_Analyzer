import { describe, it, expect } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderWithQuery } from "@/test/render";
import { TaskResultsTable } from "@/components/tasks/TaskResultsTable";
import { MOCK_PAGINATED_TASK_RESULTS, MOCK_TASK_RESULT } from "@/test/handlers";

const BASE = "http://localhost:8004";

describe("TaskResultsTable", () => {
  it("shows task name after load", async () => {
    server.use(
      http.get(`${BASE}/api/tasks/results/`, () =>
        HttpResponse.json(MOCK_PAGINATED_TASK_RESULTS),
      ),
    );
    renderWithQuery(<TaskResultsTable />);
    await waitFor(() =>
      expect(screen.getAllByText("sync_company_profiles").length).toBeGreaterThan(0),
    );
  });

  it("formats dates as dd/mm/yyyy, hh:mm:ss AM/PM", async () => {
    server.use(
      http.get(`${BASE}/api/tasks/results/`, () =>
        HttpResponse.json(MOCK_PAGINATED_TASK_RESULTS),
      ),
    );
    renderWithQuery(<TaskResultsTable />);
    await waitFor(() =>
      expect(
        screen.getAllByText(
          /^\d{2}\/\d{2}\/\d{4}, \d{2}:\d{2}:\d{2} (AM|PM)$/,
        ).length,
      ).toBeGreaterThan(0),
    );
  });

  it("renders a status badge for each result", async () => {
    server.use(
      http.get(`${BASE}/api/tasks/results/`, () =>
        HttpResponse.json(MOCK_PAGINATED_TASK_RESULTS),
      ),
    );
    renderWithQuery(<TaskResultsTable />);
    await waitFor(() => expect(screen.getByText("Success")).toBeTruthy());
    expect(screen.getByText("Failure")).toBeTruthy();
  });

  it("shows loading text initially", () => {
    server.use(
      http.get(`${BASE}/api/tasks/results/`, async () => {
        await new Promise(() => {});
        return HttpResponse.json(MOCK_PAGINATED_TASK_RESULTS);
      }),
    );
    renderWithQuery(<TaskResultsTable />);
    expect(screen.getByText("Loading...")).toBeTruthy();
  });

  it("expands row to show result on click", async () => {
    server.use(
      http.get(`${BASE}/api/tasks/results/`, () =>
        HttpResponse.json({
          count: 1,
          next: null,
          previous: null,
          results: [MOCK_TASK_RESULT],
        }),
      ),
    );
    renderWithQuery(<TaskResultsTable />);
    await waitFor(() => screen.getByText("sync_company_profiles"));
    fireEvent.click(screen.getAllByText("sync_company_profiles")[0].closest("tr")!);
    await waitFor(() => expect(screen.getByText(/Task ID:/)).toBeTruthy());
  });

  it("shows no results message when list is empty", async () => {
    server.use(
      http.get(`${BASE}/api/tasks/results/`, () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
    );
    renderWithQuery(<TaskResultsTable />);
    await waitFor(() =>
      expect(screen.getByText("No task results found.")).toBeTruthy(),
    );
  });

  it("passes status filter when filter button clicked", async () => {
    let capturedUrl = "";
    server.use(
      http.get(`${BASE}/api/tasks/results/`, ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json(MOCK_PAGINATED_TASK_RESULTS);
      }),
    );
    renderWithQuery(<TaskResultsTable />);
    await waitFor(() => screen.getAllByText("Success").length > 0);
    // first "Success" is the filter button
    fireEvent.click(screen.getAllByText("Success")[0]);
    await waitFor(() => expect(capturedUrl).toContain("status=SUCCESS"));
  });
});
