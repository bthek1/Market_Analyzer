import React from "react";
import { describe, it, expect, vi } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderWithQuery } from "@/test/render";
import { SyncFreshnessWidget } from "@/components/companies/SyncFreshnessChart";

vi.mock("echarts-for-react", () => ({
  default: () => <div data-testid="echart" />,
}));

const BASE = "http://localhost:8004";
const ZERO = { lt_1h: 0, h1_6: 0, h6_24: 0, d1_7: 0, d7_30: 0, gt_30d: 0, never: 0 };

const MOCK_AGGREGATE = {
  total_companies: 3,
  data_types: [
    { label: "Prices", buckets: { ...ZERO, lt_1h: 2, never: 1 } },
    { label: "Snapshot", buckets: { ...ZERO, never: 3 } },
  ],
};

const MOCK_MATRIX = {
  total_companies: 3,
  symbols: ["AAPL", "MSFT", "ZM"],
  data_types: [
    { label: "Prices", buckets: [0, 0, 6] },
    { label: "Snapshot", buckets: [6, 6, 6] },
  ],
};

function mockEndpoints(aggregate = MOCK_AGGREGATE, matrix = MOCK_MATRIX) {
  server.use(
    http.get(`${BASE}/api/companies/sync-freshness/`, () => HttpResponse.json(aggregate)),
    http.get(`${BASE}/api/companies/sync-freshness/matrix/`, () => HttpResponse.json(matrix)),
  );
}

async function switchToPerCompany() {
  await userEvent.click(screen.getByRole("button", { name: "Per company" }));
}

describe("SyncFreshnessWidget", () => {
  it("renders the card title", async () => {
    mockEndpoints();
    renderWithQuery(<SyncFreshnessWidget />);
    await waitFor(() => expect(screen.getByText("Sync Coverage by Data Type")).toBeTruthy());
  });

  it("renders skeleton while the aggregate query is loading", () => {
    server.use(
      http.get(`${BASE}/api/companies/sync-freshness/`, async () => {
        await new Promise(() => {});
        return HttpResponse.json(MOCK_AGGREGATE);
      }),
    );
    const { container } = renderWithQuery(<SyncFreshnessWidget />);
    expect(container.querySelector(".animate-pulse")).toBeTruthy();
  });

  it("defaults to the percentage view", async () => {
    mockEndpoints();
    renderWithQuery(<SyncFreshnessWidget />);
    await waitFor(() => expect(screen.getByTestId("echart")).toBeTruthy());
    expect(screen.getByText(/Each bar = all 3 tracked companies/)).toBeTruthy();
  });

  it("does not fetch the matrix until the per-company view is selected", async () => {
    let matrixCalls = 0;
    server.use(
      http.get(`${BASE}/api/companies/sync-freshness/`, () => HttpResponse.json(MOCK_AGGREGATE)),
      http.get(`${BASE}/api/companies/sync-freshness/matrix/`, () => {
        matrixCalls += 1;
        return HttpResponse.json(MOCK_MATRIX);
      }),
    );
    renderWithQuery(<SyncFreshnessWidget />);
    await waitFor(() => expect(screen.getByTestId("echart")).toBeTruthy());
    expect(matrixCalls).toBe(0);

    await switchToPerCompany();
    await waitFor(() => expect(matrixCalls).toBe(1));
  });

  it("switches to the per-company tick view", async () => {
    mockEndpoints();
    const { container } = renderWithQuery(<SyncFreshnessWidget />);
    await waitFor(() => expect(screen.getByTestId("echart")).toBeTruthy());

    await switchToPerCompany();
    await waitFor(() => expect(container.querySelectorAll("svg").length).toBe(2));
    expect(screen.queryByTestId("echart")).toBeNull();
  });

  it("renders one tick per company per data type", async () => {
    mockEndpoints();
    const { container } = renderWithQuery(<SyncFreshnessWidget />);
    await switchToPerCompany();
    await waitFor(() => expect(container.querySelectorAll("svg").length).toBe(2));
    // 2 data types x 3 companies
    expect(container.querySelectorAll("svg rect").length).toBe(6);
  });

  it("shows the alphabetical symbol range in the description", async () => {
    mockEndpoints();
    renderWithQuery(<SyncFreshnessWidget />);
    await switchToPerCompany();
    await waitFor(() => expect(screen.getByText(/\(AAPL to ZM\)/)).toBeTruthy());
  });

  it("colors never-synced ticks gray and fresh ticks green", async () => {
    mockEndpoints();
    const { container } = renderWithQuery(<SyncFreshnessWidget />);
    await switchToPerCompany();
    await waitFor(() => expect(container.querySelectorAll("svg rect").length).toBe(6));

    const pricesTicks = container.querySelectorAll("svg")[0].querySelectorAll("rect");
    expect(pricesTicks[0].getAttribute("fill")).toBe("#22c55e"); // AAPL, < 1h
    expect(pricesTicks[2].getAttribute("fill")).toBe("#374151"); // ZM, never
  });

  it("shows the same coverage percentage as the aggregate view", async () => {
    mockEndpoints();
    renderWithQuery(<SyncFreshnessWidget />);
    await switchToPerCompany();
    // Prices: 2 of 3 synced -> 67%; Snapshot: 0 of 3 -> 0%
    await waitFor(() => expect(screen.getByText("67%")).toBeTruthy());
    expect(screen.getByText("0%")).toBeTruthy();
  });

  it("shows a tooltip with the hovered company on mouse move", async () => {
    mockEndpoints();
    const { container } = renderWithQuery(<SyncFreshnessWidget />);
    await switchToPerCompany();
    await waitFor(() => expect(container.querySelectorAll("svg").length).toBe(2));

    const strip = container.querySelectorAll("svg")[0];
    strip.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: 300, height: 28 }) as DOMRect;
    fireEvent.mouseMove(strip, { clientX: 10 });

    await waitFor(() => expect(screen.getByText("AAPL")).toBeTruthy());
    expect(screen.getByText("< 1h")).toBeTruthy();
  });

  it("hides the tooltip on mouse leave", async () => {
    mockEndpoints();
    const { container } = renderWithQuery(<SyncFreshnessWidget />);
    await switchToPerCompany();
    await waitFor(() => expect(container.querySelectorAll("svg").length).toBe(2));

    const strip = container.querySelectorAll("svg")[0];
    strip.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: 300, height: 28 }) as DOMRect;
    fireEvent.mouseMove(strip, { clientX: 10 });
    await waitFor(() => expect(screen.getByText("AAPL")).toBeTruthy());

    fireEvent.mouseLeave(strip);
    await waitFor(() => expect(screen.queryByText("< 1h")).toBeNull());
  });

  it("switches back to the percentage view", async () => {
    mockEndpoints();
    renderWithQuery(<SyncFreshnessWidget />);
    await switchToPerCompany();
    await waitFor(() => expect(screen.getByText(/Each tick = one of 3 companies/)).toBeTruthy());

    await userEvent.click(screen.getByRole("button", { name: "Percentage" }));
    await waitFor(() => expect(screen.getByTestId("echart")).toBeTruthy());
    expect(screen.getByText(/Each bar = all 3 tracked companies/)).toBeTruthy();
  });

  it("renders skeleton while the matrix query is loading", async () => {
    server.use(
      http.get(`${BASE}/api/companies/sync-freshness/`, () => HttpResponse.json(MOCK_AGGREGATE)),
      http.get(`${BASE}/api/companies/sync-freshness/matrix/`, async () => {
        await new Promise(() => {});
        return HttpResponse.json(MOCK_MATRIX);
      }),
    );
    const { container } = renderWithQuery(<SyncFreshnessWidget />);
    await waitFor(() => expect(screen.getByTestId("echart")).toBeTruthy());
    await switchToPerCompany();
    await waitFor(() => expect(container.querySelector(".animate-pulse")).toBeTruthy());
  });

  it("handles an empty matrix without crashing", async () => {
    mockEndpoints(
      { total_companies: 0, data_types: [] },
      { total_companies: 0, symbols: [], data_types: [] },
    );
    const { container } = renderWithQuery(<SyncFreshnessWidget />);
    await switchToPerCompany();
    await waitFor(() => expect(screen.getByText(/Each tick = one of 0 companies/)).toBeTruthy());
    expect(container.querySelectorAll("svg rect").length).toBe(0);
  });
});
