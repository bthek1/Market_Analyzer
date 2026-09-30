import { describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderWithQuery } from "@/test/render";
import { SessionSidebar } from "@/components/chat/SessionSidebar";

const BASE = "http://localhost:8004";

function session(overrides: Record<string, unknown> = {}) {
  return {
    id: "s-1",
    title: "AAPL valuation",
    archived: false,
    turn_count: 3,
    last_message_at: "2026-09-28T00:00:02Z",
    created_at: "2026-09-28T00:00:00Z",
    updated_at: "2026-09-28T00:00:02Z",
    ...overrides,
  };
}

function listReturns(results: Record<string, unknown>[]) {
  server.use(
    http.get(`${BASE}/api/llm/chat/sessions/`, () =>
      HttpResponse.json({ count: results.length, next: null, previous: null, results }),
    ),
  );
}

describe("SessionSidebar", () => {
  it("renders the empty state", async () => {
    listReturns([]);
    renderWithQuery(<SessionSidebar activeId={null} onOpen={vi.fn()} onNew={vi.fn()} />);

    expect(await screen.findByText(/No conversations yet/i)).toBeInTheDocument();
  });

  it("keeps the server's order rather than re-sorting", async () => {
    // The backend orders by -updated_at, so a conversation jumps to the top when it gets a
    // new turn. Re-sorting here by created_at would quietly undo that.
    listReturns([
      session({ id: "s-2", title: "Older chat, just replied to" }),
      session({ id: "s-1", title: "Newer chat, idle" }),
    ]);
    renderWithQuery(<SessionSidebar activeId={null} onOpen={vi.fn()} onNew={vi.fn()} />);

    await screen.findByText("Older chat, just replied to");
    const titles = screen.getAllByRole("button", { name: /chat,/ }).map((b) => b.textContent);
    expect(titles[0]).toContain("Older chat");
  });

  it("falls back to a placeholder when the title task has not landed", async () => {
    // A blank title is a SUPPORTED state - the task is fire-and-forget and may fail.
    listReturns([session({ title: "" })]);
    renderWithQuery(<SessionSidebar activeId={null} onOpen={vi.fn()} onNew={vi.fn()} />);

    expect(await screen.findByText("Untitled conversation")).toBeInTheDocument();
  });

  it("opens a conversation when its row is clicked", async () => {
    listReturns([session()]);
    const onOpen = vi.fn();
    renderWithQuery(<SessionSidebar activeId={null} onOpen={onOpen} onNew={vi.fn()} />);

    await userEvent.click(await screen.findByText("AAPL valuation"));

    expect(onOpen).toHaveBeenCalledWith("s-1");
  });

  it("renames a conversation", async () => {
    listReturns([session()]);
    let patched: unknown = null;
    server.use(
      http.patch(`${BASE}/api/llm/chat/sessions/:id/`, async ({ request }) => {
        patched = await request.json();
        return HttpResponse.json(session({ title: "Renamed" }));
      }),
    );
    renderWithQuery(<SessionSidebar activeId={null} onOpen={vi.fn()} onNew={vi.fn()} />);

    await userEvent.click(await screen.findByRole("button", { name: /Rename AAPL valuation/ }));
    const input = screen.getByRole("textbox", { name: /Conversation title/i });
    await userEvent.clear(input);
    await userEvent.type(input, "Renamed{Enter}");

    await waitFor(() => expect(patched).toEqual({ title: "Renamed" }));
  });

  it("starts a fresh conversation when the OPEN one is deleted", async () => {
    // Deleting cascades the turns, so the transcript on screen no longer exists. Leaving it
    // rendered would show deleted rows that the next message would not follow on from.
    listReturns([session()]);
    server.use(
      http.delete(`${BASE}/api/llm/chat/sessions/:id/`, () => new HttpResponse(null, { status: 204 })),
    );
    const onNew = vi.fn();
    renderWithQuery(<SessionSidebar activeId="s-1" onOpen={vi.fn()} onNew={onNew} />);

    await userEvent.click(await screen.findByRole("button", { name: /Delete AAPL valuation/ }));

    await waitFor(() => expect(onNew).toHaveBeenCalled());
  });

  it("does not disturb the transcript when a DIFFERENT conversation is deleted", async () => {
    listReturns([session()]);
    server.use(
      http.delete(`${BASE}/api/llm/chat/sessions/:id/`, () => new HttpResponse(null, { status: 204 })),
    );
    const onNew = vi.fn();
    renderWithQuery(<SessionSidebar activeId="s-other" onOpen={vi.fn()} onNew={onNew} />);

    await userEvent.click(await screen.findByRole("button", { name: /Delete AAPL valuation/ }));

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /Delete AAPL valuation/ })).not.toBeNull(),
    );
    expect(onNew).not.toHaveBeenCalled();
  });

  it("offers a new chat", async () => {
    listReturns([]);
    const onNew = vi.fn();
    renderWithQuery(<SessionSidebar activeId={null} onOpen={vi.fn()} onNew={onNew} />);

    await userEvent.click(screen.getByRole("button", { name: /New chat/i }));

    expect(onNew).toHaveBeenCalled();
  });
});
