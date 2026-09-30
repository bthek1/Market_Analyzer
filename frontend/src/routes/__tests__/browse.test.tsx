import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderWithQuery } from "@/test/render";
import { MOCK_LLM_SETTINGS } from "@/test/handlers";

const BASE = "http://localhost:8004";
const RUN_ID = "77777777-7777-7777-7777-777777777777";

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

import { Route } from "@/routes/browse";

const BrowsePage = (Route as unknown as { component: React.ComponentType })
  .component;

function makeSSEStream(events: object[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const evt of events) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(evt)}\n\n`));
      }
      controller.close();
    },
  });
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("/browse", () => {
  it("renders the search box as the page's anchor", async () => {
    renderWithQuery(<BrowsePage />);
    expect(await screen.findByLabelText("Search the web")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /run/i })).toBeInTheDocument();
  });

  it("streams a run and shows steps, answer and sources", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        body: makeSSEStream([
          {
            event: "started",
            max_steps: 15,
            provider: "anthropic",
            allowed_domains: [],
            timeout_s: 300,
          },
          {
            event: "step",
            id: "row-0",
            order: 0,
            action: "go_to_url",
            action_args: {},
            url: "https://example.com/nvda",
            title: "NVDA results",
            evaluation: "found the page",
            memory: "",
            output: "open the results page",
            screenshot: "",
            status: "done",
            error: null,
          },
          {
            event: "result",
            output: "NVIDIA leads the market.",
            sources: ["https://example.com/nvda"],
            stop_reason: "complete",
            steps: 1,
            run_id: RUN_ID,
          },
        ]),
      }),
    );

    renderWithQuery(<BrowsePage />);
    const input = await screen.findByLabelText("Search the web");
    fireEvent.change(input, { target: { value: "who leads GPUs?" } });
    fireEvent.click(screen.getByRole("button", { name: /run/i }));

    expect(await screen.findByText("NVIDIA leads the market.")).toBeInTheDocument();
    expect(screen.getByText("NVDA results")).toBeInTheDocument();
    expect(screen.getByText("open the results page")).toBeInTheDocument();
    expect(screen.getByText("Sources")).toBeInTheDocument();
    expect(screen.getByText("answered")).toBeInTheDocument();
  });

  it("shows a Stop button while a run streams", async () => {
    // A stream that stays open: the page must stay in its running state.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        body: new ReadableStream({
          start(controller) {
            controller.enqueue(
              new TextEncoder().encode(
                `data: ${JSON.stringify({ event: "started", max_steps: 15, provider: "anthropic", allowed_domains: [], timeout_s: 300 })}\n\n`,
              ),
            );
          },
        }),
      }),
    );

    renderWithQuery(<BrowsePage />);
    const input = await screen.findByLabelText("Search the web");
    fireEvent.change(input, { target: { value: "slow query" } });
    fireEvent.click(screen.getByRole("button", { name: /run/i }));

    expect(await screen.findByRole("button", { name: /stop/i })).toBeInTheDocument();
  });

  it("renders the disabled empty state instead of the search box", async () => {
    server.use(
      http.get(`${BASE}/api/llm/settings/`, () =>
        HttpResponse.json({ ...MOCK_LLM_SETTINGS, browser_enabled: false }),
      ),
    );
    renderWithQuery(<BrowsePage />);

    expect(await screen.findByText(/switched off/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Search the web")).not.toBeInTheDocument();
  });

  it("lists this page's own history, not the Agents feed", async () => {
    let agentsHistoryHit = false;
    server.use(
      http.get(`${BASE}/api/llm/browser/history/`, () =>
        HttpResponse.json({
          count: 1,
          next: null,
          previous: null,
          results: [
            {
              id: RUN_ID,
              query: "earlier search",
              provider: "anthropic",
              max_steps: 15,
              status: "done",
              stop_reason: "complete",
              created_at: new Date().toISOString(),
              completed_at: new Date().toISOString(),
            },
          ],
        }),
      ),
      http.get(`${BASE}/api/llm/react/history/`, () => {
        agentsHistoryHit = true;
        return HttpResponse.json({ count: 0, next: null, previous: null, results: [] });
      }),
    );

    renderWithQuery(<BrowsePage />);
    expect(await screen.findByText("earlier search")).toBeInTheDocument();
    await waitFor(() => expect(agentsHistoryHit).toBe(false));
  });
});

describe("separation from the Agents workspace", () => {
  it("does not register the browser agent as an Agents mode", async () => {
    const { readFileSync } = await import("node:fs");
    const source = readFileSync("src/routes/agents.tsx", "utf8");
    // Guard the read itself, so an empty string can never make this pass vacuously.
    expect(source).toContain("COMPARABLE_TYPES");
    // The Agents page must not know about /browse: no browser mode, no Compare entry.
    expect(source).not.toContain('"browser"');
    expect(source).not.toContain("useBrowserAgent");
  });

  it("keeps the browser session out of the Agents session store", async () => {
    const { readFileSync } = await import("node:fs");
    const source = readFileSync("src/lib/agentsSession.ts", "utf8").toLowerCase();
    expect(source).not.toContain("browser");
  });
});
