import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { Markdown } from "@/components/Markdown";

// These exercise the real react-markdown + remark-gfm pipeline (no mock), since
// the whole point of the wrapper is that GFM features render as proper HTML.
describe("Markdown", () => {
  it("renders a GFM pipe table as a real <table>", () => {
    const md = [
      "| Company | Why Invest |",
      "|---------|------------|",
      "| Apple | Ecosystem dominance |",
      "| NVIDIA | AI chips |",
    ].join("\n");

    render(<Markdown>{md}</Markdown>);

    const table = screen.getByRole("table");
    expect(table).toBeInTheDocument();
    // Header cells + body cells come through as table semantics, not raw "|" text.
    expect(within(table).getByText("Company")).toBeInTheDocument();
    expect(within(table).getByText("Apple")).toBeInTheDocument();
    expect(within(table).getByText("NVIDIA")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(3); // 1 header + 2 body
  });

  it("renders standard CommonMark (headings)", () => {
    render(<Markdown># Hello</Markdown>);
    expect(screen.getByRole("heading", { name: "Hello" })).toBeInTheDocument();
  });

  it("renders GFM strikethrough", () => {
    const { container } = render(<Markdown>{"~~gone~~"}</Markdown>);
    expect(container.querySelector("del")).toHaveTextContent("gone");
  });
});
