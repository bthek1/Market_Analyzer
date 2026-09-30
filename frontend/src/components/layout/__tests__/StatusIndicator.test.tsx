import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusIndicator } from "@/components/layout/StatusIndicator";

describe("StatusIndicator", () => {
  it("renders label text", () => {
    render(<StatusIndicator label="API" ok={true} />);
    expect(screen.getByText("API")).toBeTruthy();
  });

  it("renders green dot when ok", () => {
    const { container } = render(<StatusIndicator label="API" ok={true} />);
    const dot = container.querySelector(".bg-green-500");
    expect(dot).toBeTruthy();
  });

  it("renders red dot when not ok", () => {
    const { container } = render(<StatusIndicator label="DB" ok={false} />);
    const dot = container.querySelector(".bg-red-500");
    expect(dot).toBeTruthy();
  });

  it("does not render red dot when ok", () => {
    const { container } = render(<StatusIndicator label="API" ok={true} />);
    expect(container.querySelector(".bg-red-500")).toBeNull();
  });
});
