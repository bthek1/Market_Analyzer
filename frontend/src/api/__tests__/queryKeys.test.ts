import { describe, it, expect } from "vitest";
import { queryKeys } from "@/api/queryKeys";

describe("queryKeys", () => {
  it("auth.me returns correct key", () => {
    expect(queryKeys.auth.me()).toEqual(["auth", "me"]);
  });

  it("companies.list without query returns key with undefined", () => {
    expect(queryKeys.companies.list()).toEqual(["companies", "list", undefined]);
  });

  it("companies.list with query includes it", () => {
    expect(queryKeys.companies.list("AAPL")).toEqual(["companies", "list", "AAPL"]);
  });

  it("companies.detail includes id", () => {
    expect(queryKeys.companies.detail("abc-123")).toEqual(["companies", "detail", "abc-123"]);
  });

  it("companies.sectors returns correct key", () => {
    expect(queryKeys.companies.sectors()).toEqual(["companies", "sectors"]);
  });

  it("system.health returns correct key", () => {
    expect(queryKeys.system.health()).toEqual(["system", "health"]);
  });

  it("tasks.results without status returns key with undefined", () => {
    expect(queryKeys.tasks.results()).toEqual(["tasks", "results", undefined]);
  });

  it("tasks.results with status includes it", () => {
    expect(queryKeys.tasks.results("FAILURE")).toEqual(["tasks", "results", "FAILURE"]);
  });

  it("tasks.result includes task id", () => {
    expect(queryKeys.tasks.result("abc-123")).toEqual(["tasks", "result", "abc-123"]);
  });

  it("tasks.schedules returns correct key", () => {
    expect(queryKeys.tasks.schedules()).toEqual(["tasks", "schedules"]);
  });

  it("companies.industries without params includes undefined", () => {
    expect(queryKeys.companies.industries()).toEqual(["companies", "industries", undefined]);
  });

  it("companies.industries with params includes them", () => {
    expect(queryKeys.companies.industries({ sector: 1 })).toEqual([
      "companies",
      "industries",
      { sector: 1 },
    ]);
  });

  it("companies.marketHierarchy returns correct key with default metric", () => {
    expect(queryKeys.companies.marketHierarchy()).toEqual(["companies", "market-hierarchy", "count"]);
  });

  it("companies.marketHierarchy includes metric in key", () => {
    expect(queryKeys.companies.marketHierarchy("market_cap")).toEqual([
      "companies",
      "market-hierarchy",
      "market_cap",
    ]);
  });

  it("companies.prices includes companyId", () => {
    expect(queryKeys.companies.prices(42)).toEqual(["companies", 42, "prices"]);
  });

  it("companies.snapshots includes companyId", () => {
    expect(queryKeys.companies.snapshots(42)).toEqual(["companies", 42, "snapshots"]);
  });

  it("companies.financials includes companyId", () => {
    expect(queryKeys.companies.financials(42)).toEqual(["companies", 42, "financials"]);
  });

  it("companies.financialsPivoted includes companyId", () => {
    expect(queryKeys.companies.financialsPivoted(42)).toEqual([
      "companies",
      42,
      "financials-pivoted",
    ]);
  });

  it("companies.dividends includes companyId", () => {
    expect(queryKeys.companies.dividends(42)).toEqual(["companies", 42, "dividends"]);
  });

  it("companies.shortInterest includes companyId", () => {
    expect(queryKeys.companies.shortInterest(42)).toEqual(["companies", 42, "short-interest"]);
  });

  it("companies.institutionalHolders includes companyId", () => {
    expect(queryKeys.companies.institutionalHolders(42)).toEqual([
      "companies",
      42,
      "institutional-holders",
    ]);
  });

  it("companies.earningsDates without params includes undefined", () => {
    expect(queryKeys.companies.earningsDates(42)).toEqual([
      "companies",
      42,
      "earnings-dates",
      undefined,
    ]);
  });

  it("companies.earningsDates with params includes them", () => {
    expect(queryKeys.companies.earningsDates(42, { is_upcoming: true })).toEqual([
      "companies",
      42,
      "earnings-dates",
      { is_upcoming: true },
    ]);
  });

  it("companies.optionsExpiries includes companyId", () => {
    expect(queryKeys.companies.optionsExpiries(42)).toEqual(["companies", 42, "options"]);
  });

  it("companies.optionsChain includes companyId and expiry date", () => {
    expect(queryKeys.companies.optionsChain(42, "2026-06-20")).toEqual([
      "companies",
      42,
      "options",
      "2026-06-20",
    ]);
  });

  it("llm.models returns correct key", () => {
    expect(queryKeys.llm.models()).toEqual(["llm", "models"]);
  });
});
