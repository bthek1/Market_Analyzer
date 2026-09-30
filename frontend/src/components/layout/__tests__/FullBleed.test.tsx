import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { FullBleed } from "@/components/layout/FullBleed";

describe("FullBleed", () => {
  it("renders its children", () => {
    render(
      <FullBleed>
        <p>graph</p>
      </FullBleed>
    );
    expect(screen.getByText("graph")).toBeTruthy();
  });

  it("cancels the main padding and fills the viewport between header and status bar", () => {
    const { container } = render(<FullBleed>x</FullBleed>);
    const cls = (container.firstElementChild as HTMLElement).className;
    expect(cls).toContain("-mx-6");
    expect(cls).toContain("-my-8");
    expect(cls).toContain("h-[calc(100vh-5.75rem)]");
  });

  it("never bleeds to viewport width (that would sit under the sidebar)", () => {
    const { container } = render(<FullBleed>x</FullBleed>);
    const cls = (container.firstElementChild as HTMLElement).className;
    expect(cls).not.toContain("w-screen");
    expect(cls).not.toContain("50vw");
  });

  it("merges an extra className", () => {
    const { container } = render(<FullBleed className="bg-red-500">x</FullBleed>);
    expect((container.firstElementChild as HTMLElement).className).toContain(
      "bg-red-500"
    );
  });
});
