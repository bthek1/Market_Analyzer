import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { WorkspaceSwitch } from "@/components/layout/WorkspaceSwitch";

vi.mock("@tanstack/react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-router")>();
  return {
    ...actual,
    // `href={to}`, matching Sidebar.test.tsx. A mock that spreads `to` onto an <a> drops
    // the destination and makes every link untestable - that drift is what hid a broken
    // link on /agents until issue #8 phase 6.
    Link: ({
      to,
      children,
      ...props
    }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { to: string }) => (
      <a href={to} {...props}>
        {children}
      </a>
    ),
  };
});

describe("WorkspaceSwitch", () => {
  it("offers both workspaces", () => {
    render(<WorkspaceSwitch active="/agents" />);

    expect(screen.getByRole("link", { name: "Workflows" })).toHaveAttribute(
      "href",
      "/agents",
    );
    expect(screen.getByRole("link", { name: "Chat" })).toHaveAttribute("href", "/chat");
  });

  it("marks the current workspace for assistive tech, not just colour", () => {
    render(<WorkspaceSwitch active="/chat" />);

    expect(screen.getByRole("link", { name: "Chat" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Workflows" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("switches which one is current", () => {
    const { rerender } = render(<WorkspaceSwitch active="/agents" />);
    expect(screen.getByRole("link", { name: "Workflows" })).toHaveAttribute(
      "aria-current",
      "page",
    );

    rerender(<WorkspaceSwitch active="/chat" />);

    expect(screen.getByRole("link", { name: "Chat" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("stays navigable rather than being disabled mid-run", () => {
    // A run keeps going server-side (`stream_in_background` drives it on a daemon thread)
    // and both pages reconnect to an unfinished one on arrival, so there is nothing to
    // protect the user from by blocking the switch - the old mode toggle disabled itself
    // while running, which made sense only when leaving meant losing the run.
    render(<WorkspaceSwitch active="/agents" />);

    for (const name of ["Workflows", "Chat"]) {
      const link = screen.getByRole("link", { name });
      expect(link).not.toHaveAttribute("disabled");
      expect(link).not.toHaveAttribute("aria-disabled");
    }
  });
});
