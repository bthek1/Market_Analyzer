import React from "react";
import { describe, it, expect, vi } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { renderWithQuery } from "@/test/render";
import { stripUndefinedNodes, formatMarketCap } from "@/routes/market-map.utils";

vi.mock("echarts-for-react", () => ({
  default: () => <div data-testid="echart" />,
}));

vi.mock("@tanstack/react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-router")>();
  return {
    ...actual,
    createFileRoute: () => (config: { component: React.ComponentType }) => config,
    Link: ({
      children,
      ...props
    }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => <a {...props}>{children}</a>,
    Outlet: () => null,
  };
});

vi.mock("@/components/layout/AppShell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

describe("stripUndefinedNodes", () => {
  it("removes nodes whose name is undefined", () => {
    const input = [
      { name: "Technology", value: 5, company_count: 5 },
      { name: "undefined", value: 2, company_count: 2 },
    ];
    const result = stripUndefinedNodes(input);
    expect(result).toHaveLength(1);
    expect(result[0].name).toBe("Technology");
  });

  it("removes nodes whose name is an empty string", () => {
    const input = [
      { name: "Technology", value: 5, company_count: 5 },
      { name: "", value: 1, company_count: 1 },
    ];
    const result = stripUndefinedNodes(input);
    expect(result).toHaveLength(1);
  });

  it("recursively strips undefined children", () => {
    const input = [
      {
        name: "Technology",
        value: 5,
        company_count: 5,
        children: [
          { name: "Software", value: 3, company_count: 3 },
          { name: "undefined", value: 2, company_count: 2 },
        ],
      },
    ];
    const result = stripUndefinedNodes(input);
    expect(result[0].children).toHaveLength(1);
    expect(result[0].children![0].name).toBe("Software");
  });

  it("preserves valid nodes and their structure", () => {
    const input = [
      {
        name: "Healthcare",
        value: 8,
        company_count: 8,
        children: [{ name: "Biotech", value: 8, company_count: 8 }],
      },
    ];
    const result = stripUndefinedNodes(input);
    expect(result).toHaveLength(1);
    expect(result[0].children).toHaveLength(1);
  });
});

describe("market-map route", () => {
  it("route module exports a component", async () => {
    const mod = await import("@/routes/market-map");
    expect(mod.Route).toBeDefined();
    expect(typeof mod.Route.component).toBe("function");
  });

  it("renders the Market Map heading", async () => {
    const { Route } = await import("@/routes/market-map");
    const Page = Route.component as React.ComponentType;
    renderWithQuery(<Page />);
    await waitFor(() => expect(screen.getByText("Market Map")).toBeTruthy());
  });

  it("renders sunburst and treemap toggle buttons", async () => {
    const { Route } = await import("@/routes/market-map");
    const Page = Route.component as React.ComponentType;
    renderWithQuery(<Page />);
    await waitFor(() => {
      expect(screen.getByText("sunburst")).toBeTruthy();
      expect(screen.getByText("treemap")).toBeTruthy();
    });
  });

  it("renders Industry and Sector table column headers", async () => {
    const { Route } = await import("@/routes/market-map");
    const Page = Route.component as React.ComponentType;
    renderWithQuery(<Page />);
    await waitFor(() => {
      expect(screen.getByText("Industry")).toBeTruthy();
      expect(screen.getByText("Sector")).toBeTruthy();
    });
  });

  it("renders the chart after data loads", async () => {
    const { Route } = await import("@/routes/market-map");
    const Page = Route.component as React.ComponentType;
    renderWithQuery(<Page />);
    await waitFor(() => expect(screen.getByTestId("echart")).toBeTruthy());
  });

  it("switches between sunburst and treemap on button click", async () => {
    const { Route } = await import("@/routes/market-map");
    const Page = Route.component as React.ComponentType;
    renderWithQuery(<Page />);
    await waitFor(() => screen.getByText("treemap"));
    fireEvent.click(screen.getByText("treemap"));
    expect(screen.getByText("treemap")).toBeTruthy();
  });

  it("renders Count and Market Cap metric toggle buttons", async () => {
    const { Route } = await import("@/routes/market-map");
    const Page = Route.component as React.ComponentType;
    renderWithQuery(<Page />);
    await waitFor(() => {
      expect(screen.getByText("Count")).toBeTruthy();
      expect(screen.getByText("Market Cap")).toBeTruthy();
    });
  });

  it("table column header changes to Market Cap when metric toggled", async () => {
    const { Route } = await import("@/routes/market-map");
    const Page = Route.component as React.ComponentType;
    renderWithQuery(<Page />);
    await waitFor(() => screen.getByText("Companies"));
    fireEvent.click(screen.getByText("Market Cap"));
    await waitFor(() => expect(screen.getByText("Market Cap", { selector: "th" })).toBeTruthy());
  });

  it("table column header reverts to Companies when Count metric selected", async () => {
    const { Route } = await import("@/routes/market-map");
    const Page = Route.component as React.ComponentType;
    renderWithQuery(<Page />);
    await waitFor(() => screen.getByText("Companies"));
    fireEvent.click(screen.getByText("Market Cap"));
    await waitFor(() => screen.getByText("Market Cap", { selector: "th" }));
    fireEvent.click(screen.getByText("Count"));
    await waitFor(() => expect(screen.getByText("Companies")).toBeTruthy());
  });
});

describe("formatMarketCap", () => {
  it("formats trillions", () => {
    expect(formatMarketCap(2_400_000_000_000)).toBe("$2.4T");
  });

  it("formats billions", () => {
    expect(formatMarketCap(1_500_000_000)).toBe("$1.5B");
  });

  it("formats millions", () => {
    expect(formatMarketCap(12_000_000)).toBe("$12.0M");
  });

  it("formats small values as plain dollars", () => {
    expect(formatMarketCap(999)).toBe("$999");
  });

  it("formats zero", () => {
    expect(formatMarketCap(0)).toBe("$0");
  });
});
