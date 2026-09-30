import { describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import { renderWithQuery } from "@/test/render";

vi.mock("@tanstack/react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-router")>();
  return {
    ...actual,
    createFileRoute: () => (config: { component: React.ComponentType }) => config,
    // `href={to}` - see Sidebar.test.tsx. A mock that drops the destination makes every
    // link on the page invisible to getByRole("link").
    Link: ({
      to,
      children,
      ...props
    }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { to: string }) => (
      <a href={to} {...props}>
        {children}
      </a>
    ),
    Outlet: () => null,
    useRouterState: () => ({ location: { pathname: "/chat" } }),
  };
});

async function loadPage() {
  const { Route } = await import("@/routes/chat");
  const Page = Route.component as React.ComponentType;
  renderWithQuery(<Page />);
  await waitFor(() => screen.getByRole("textbox", { name: /message/i }));
}

describe("Chat route", () => {
  it("renders the conversation workspace", async () => {
    await loadPage();

    expect(screen.getByRole("button", { name: /New chat/i })).toBeTruthy();
    expect(screen.getByRole("textbox", { name: /message/i })).toBeTruthy();
    expect(screen.getByText(/Ask about a company/i)).toBeTruthy();
  });

  it("offers a two-way switch back to the workflow workspace", async () => {
    // The reverse of the assertion on /agents. A switch that only works one way strands
    // the user on whichever page they landed on.
    await loadPage();

    // Scoped to the switch: the AppShell sidebar carries its own "Chat" nav link, so an
    // unscoped query matches two elements and the assertion becomes ambiguous.
    const switcher = within(screen.getByRole("navigation", { name: "Workspace" }));
    const chat = switcher.getByRole("link", { name: "Chat" });
    const workflows = switcher.getByRole("link", { name: "Workflows" });

    expect(chat).toHaveAttribute("aria-current", "page");
    expect(workflows).toHaveAttribute("href", "/agents");
    expect(workflows).not.toHaveAttribute("aria-current");
  });

  it("falls back to a generic heading until the title task lands", async () => {
    // A blank title is a supported state - the task is fire-and-forget and may fail.
    await loadPage();

    expect(screen.getByRole("heading", { name: "Chat" })).toBeTruthy();
  });
});
