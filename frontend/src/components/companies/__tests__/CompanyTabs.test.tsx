import React from "react";
import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { renderWithQuery } from "@/test/render";
import { CompanyTabs } from "@/components/companies/CompanyTabs";

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "financials", label: "Financials" },
  { key: "market", label: "Market Data" },
];

describe("CompanyTabs", () => {
  it("renders all tab labels", () => {
    const onChange = vi.fn();
    renderWithQuery(
      <CompanyTabs tabs={TABS} activeTab="overview" onChange={onChange} />,
    );
    expect(screen.getByText("Overview")).toBeTruthy();
    expect(screen.getByText("Financials")).toBeTruthy();
    expect(screen.getByText("Market Data")).toBeTruthy();
  });

  it("calls onChange with the correct key when a tab is clicked", () => {
    const onChange = vi.fn();
    renderWithQuery(
      <CompanyTabs tabs={TABS} activeTab="overview" onChange={onChange} />,
    );
    fireEvent.click(screen.getByText("Financials"));
    expect(onChange).toHaveBeenCalledWith("financials");
  });

  it("applies active styling to the current tab", () => {
    const onChange = vi.fn();
    const { container } = renderWithQuery(
      <CompanyTabs tabs={TABS} activeTab="financials" onChange={onChange} />,
    );
    const buttons = container.querySelectorAll("button");
    const financialsBtn = Array.from(buttons).find((b) => b.textContent === "Financials");
    expect(financialsBtn?.className).toContain("border-primary");
  });

  it("does not apply active class to inactive tabs", () => {
    const onChange = vi.fn();
    const { container } = renderWithQuery(
      <CompanyTabs tabs={TABS} activeTab="overview" onChange={onChange} />,
    );
    const buttons = container.querySelectorAll("button");
    const financialsBtn = Array.from(buttons).find((b) => b.textContent === "Financials");
    expect(financialsBtn?.className).not.toContain("border-primary");
  });

  it("calls onChange with the first tab key when first tab clicked", () => {
    const onChange = vi.fn();
    renderWithQuery(
      <CompanyTabs tabs={TABS} activeTab="financials" onChange={onChange} />,
    );
    fireEvent.click(screen.getByText("Overview"));
    expect(onChange).toHaveBeenCalledWith("overview");
  });
});
