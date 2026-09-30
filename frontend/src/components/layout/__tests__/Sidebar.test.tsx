import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Sidebar } from "@/components/layout/Sidebar";
import { NAV_LINKS } from "@/components/layout/nav";

const mockPathname = { current: "/" };

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
    useRouterState: () => ({ location: { pathname: mockPathname.current } }),
  };
});

describe("Sidebar", () => {
  it("renders every nav label", () => {
    render(<Sidebar collapsed={false} onToggle={() => {}} />);
    for (const { label } of NAV_LINKS) {
      expect(screen.getByText(label)).toBeTruthy();
    }
  });

  it("hides labels visually when collapsed", () => {
    render(<Sidebar collapsed={true} onToggle={() => {}} />);
    expect(screen.getByText("Dashboard").className).toContain("md:sr-only");
  });

  it("keeps labels visible when expanded", () => {
    render(<Sidebar collapsed={false} onToggle={() => {}} />);
    expect(screen.getByText("Dashboard").className).not.toContain("sr-only");
  });

  it("fires onToggle from the collapse button", () => {
    const onToggle = vi.fn();
    render(<Sidebar collapsed={false} onToggle={onToggle} />);
    fireEvent.click(screen.getByLabelText("Collapse sidebar"));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("fires onToggle from the expand button when collapsed", () => {
    const onToggle = vi.fn();
    render(<Sidebar collapsed={true} onToggle={onToggle} />);
    fireEvent.click(screen.getAllByLabelText("Expand sidebar")[0]);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("marks the current route as active", () => {
    mockPathname.current = "/companies";
    render(<Sidebar collapsed={false} onToggle={() => {}} />);
    const active = screen.getByText("Companies").closest("a");
    expect(active?.getAttribute("aria-current")).toBe("page");
    expect(screen.getByText("Tasks").closest("a")?.getAttribute("aria-current")).toBeNull();
    mockPathname.current = "/";
  });

  it("treats a sub-route as active for its parent link", () => {
    mockPathname.current = "/companies/abc-123";
    render(<Sidebar collapsed={false} onToggle={() => {}} />);
    expect(
      screen.getByText("Companies").closest("a")?.getAttribute("aria-current")
    ).toBe("page");
    expect(
      screen.getByText("Dashboard").closest("a")?.getAttribute("aria-current")
    ).toBeNull();
    mockPathname.current = "/";
  });

  it("renders a backdrop only while the mobile drawer is open", () => {
    const onClose = vi.fn();
    const { rerender } = render(
      <Sidebar collapsed={false} onToggle={() => {}} mobileOpen={false} />
    );
    expect(screen.queryByTestId("sidebar-backdrop")).toBeNull();

    rerender(
      <Sidebar
        collapsed={false}
        onToggle={() => {}}
        mobileOpen={true}
        onMobileClose={onClose}
      />
    );
    fireEvent.click(screen.getByTestId("sidebar-backdrop"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
