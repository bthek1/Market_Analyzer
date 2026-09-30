import React from "react";
import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithQuery } from "@/test/render";
import { CompanyTable } from "@/components/companies/CompanyTable";
import { MOCK_COMPANY } from "@/test/handlers";

vi.mock("@tanstack/react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-router")>();
  return {
    ...actual,
    Link: ({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
      <a {...props}>{children}</a>
    ),
  };
});

const defaultParams = { page: 1, page_size: 25, ordering: "symbol" };
const noop = () => {};

describe("CompanyTable", () => {
  it("renders empty state when no companies", () => {
    renderWithQuery(
      <CompanyTable companies={[]} count={0} params={defaultParams} onParamsChange={noop} />,
    );
    expect(screen.getByText("No companies found.")).toBeTruthy();
  });

  it("renders symbol and name", () => {
    renderWithQuery(
      <CompanyTable
        companies={[MOCK_COMPANY]}
        count={1}
        params={defaultParams}
        onParamsChange={noop}
      />,
    );
    expect(screen.getByText("AAPL")).toBeTruthy();
    expect(screen.getByText("Apple Inc.")).toBeTruthy();
  });

  it("renders exchange display", () => {
    renderWithQuery(
      <CompanyTable
        companies={[MOCK_COMPANY]}
        count={1}
        params={defaultParams}
        onParamsChange={noop}
      />,
    );
    expect(screen.getByText("NASDAQ")).toBeTruthy();
  });

  it("renders sector and industry names", () => {
    renderWithQuery(
      <CompanyTable
        companies={[MOCK_COMPANY]}
        count={1}
        params={defaultParams}
        onParamsChange={noop}
      />,
    );
    expect(screen.getByText("Technology")).toBeTruthy();
    expect(screen.getByText("Consumer Electronics")).toBeTruthy();
  });

  it("renders dash when exchange is blank", () => {
    const company = { ...MOCK_COMPANY, exchange: "" as const, exchange_display: "" };
    renderWithQuery(
      <CompanyTable
        companies={[company]}
        count={1}
        params={defaultParams}
        onParamsChange={noop}
      />,
    );
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThan(0);
  });

  it("shows pagination controls", () => {
    renderWithQuery(
      <CompanyTable
        companies={[MOCK_COMPANY]}
        count={50}
        params={defaultParams}
        onParamsChange={noop}
      />,
    );
    expect(screen.getByText(/Page 1 of 2/)).toBeTruthy();
  });

  it("shows total company count", () => {
    renderWithQuery(
      <CompanyTable
        companies={[MOCK_COMPANY]}
        count={42}
        params={defaultParams}
        onParamsChange={noop}
      />,
    );
    expect(screen.getByText("42 companies")).toBeTruthy();
  });
});
