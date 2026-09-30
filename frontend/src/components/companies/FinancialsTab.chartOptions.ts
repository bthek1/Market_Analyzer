import type { EChartsOption } from "echarts";

export function buildRevenueOption(
  dates: string[],
  rows: { metric: string; values: (number | null)[] }[],
): EChartsOption {
  const revenue = rows.find((r) => r.metric === "Total Revenue")?.values ?? [];
  const grossProfit = rows.find((r) => r.metric === "Gross Profit")?.values ?? [];
  const ebitda = rows.find((r) => r.metric === "EBITDA")?.values ?? [];
  const netIncome = rows.find((r) => r.metric === "Net Income")?.values ?? [];

  const series: EChartsOption["series"] = [
    { name: "Total Revenue", type: "bar", data: revenue },
    { name: "Net Income", type: "bar", data: netIncome },
  ];
  if (ebitda.some((v) => v !== null)) {
    (series as { name: string; type: string; data: (number | null)[] }[]).push(
      { name: "EBITDA", type: "bar", data: ebitda },
    );
  }
  if (grossProfit.some((v) => v !== null)) {
    (series as { name: string; type: string; data: (number | null)[]; smooth?: boolean }[]).push(
      { name: "Gross Profit", type: "line", smooth: true, data: grossProfit },
    );
  }

  return {
    legend: {},
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: dates },
    yAxis: {
      type: "value",
      axisLabel: { formatter: (v: number) => `$${(v / 1e9).toFixed(1)}B` },
    },
    series,
  };
}

export function buildBalanceSheetOption(
  dates: string[],
  rows: { metric: string; values: (number | null)[] }[],
): EChartsOption | null {
  const assets = rows.find((r) => r.metric === "Total Assets")?.values ?? [];
  if (assets.every((v) => v === null)) return null;

  const cash = rows.find((r) => r.metric === "Cash And Cash Equivalents")?.values ?? [];
  const liabilities = rows.find((r) => r.metric === "Total Liabilities Net Minority Interest")?.values
    ?? rows.find((r) => r.metric === "Total Liabilities")?.values ?? [];
  const equity = rows.find((r) => r.metric === "Total Stockholder Equity")?.values
    ?? rows.find((r) => r.metric === "Stockholders Equity")?.values ?? [];

  return {
    legend: {},
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    xAxis: { type: "category", data: dates },
    yAxis: {
      type: "value",
      axisLabel: { formatter: (v: number) => `$${(v / 1e9).toFixed(1)}B` },
    },
    series: [
      { name: "Cash & Equivalents", type: "bar", stack: "total", data: cash },
      { name: "Total Liabilities", type: "bar", stack: "total", data: liabilities },
      { name: "Stockholder Equity", type: "bar", stack: "total", data: equity },
    ],
  };
}

export function buildDebtEquityOption(
  dates: string[],
  rows: { metric: string; values: (number | null)[] }[],
): EChartsOption | null {
  const debt = rows.find((r) => r.metric === "Total Debt")?.values ?? [];
  const equity = rows.find((r) => r.metric === "Total Stockholder Equity")?.values
    ?? rows.find((r) => r.metric === "Stockholders Equity")?.values ?? [];

  if ([...debt, ...equity].every((v) => v === null)) return null;

  return {
    legend: {},
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: dates },
    yAxis: {
      type: "value",
      axisLabel: { formatter: (v: number) => `$${(v / 1e9).toFixed(1)}B` },
    },
    series: [
      { name: "Total Debt", type: "line", smooth: true, data: debt, color: "#ef4444" },
      { name: "Stockholder Equity", type: "line", smooth: true, data: equity, color: "#16a34a" },
    ],
  };
}

export function buildMarginsOption(
  dates: string[],
  rows: { metric: string; values: (number | null)[] }[],
): EChartsOption | null {
  const revenue = rows.find((r) => r.metric === "Total Revenue")?.values ?? [];
  const grossProfit = rows.find((r) => r.metric === "Gross Profit")?.values ?? [];
  const operatingIncome = rows.find((r) => r.metric === "Operating Income")?.values ?? [];
  const netIncome = rows.find((r) => r.metric === "Net Income")?.values ?? [];

  if (revenue.every((v) => v === null)) return null;

  const pct = (num: (number | null)[], den: (number | null)[]) =>
    num.map((v, i) => {
      const d = den[i];
      return v !== null && d ? parseFloat(((v / d) * 100).toFixed(2)) : null;
    });

  return {
    legend: {},
    tooltip: { trigger: "axis", valueFormatter: (v: number) => `${v.toFixed(1)}%` },
    xAxis: { type: "category", data: dates },
    yAxis: {
      type: "value",
      axisLabel: { formatter: (v: number) => `${v}%` },
    },
    series: [
      { name: "Gross Margin", type: "line", smooth: true, data: pct(grossProfit, revenue) },
      { name: "Operating Margin", type: "line", smooth: true, data: pct(operatingIncome, revenue) },
      { name: "Net Margin", type: "line", smooth: true, data: pct(netIncome, revenue) },
    ],
  };
}

export function buildCashFlowOption(
  dates: string[],
  rows: { metric: string; values: (number | null)[] }[],
): EChartsOption | null {
  const operating = rows.find((r) => r.metric === "Operating Cash Flow")?.values ?? [];
  const capex = rows.find((r) => r.metric === "Capital Expenditure")?.values ?? [];
  const fcf = rows.find((r) => r.metric === "Free Cash Flow")?.values ?? [];

  if ([...operating, ...capex, ...fcf].every((v) => v === null)) return null;

  return {
    legend: {},
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: dates },
    yAxis: {
      type: "value",
      axisLabel: { formatter: (v: number) => `$${(v / 1e9).toFixed(1)}B` },
    },
    series: [
      { name: "Operating CF", type: "bar", data: operating },
      { name: "CapEx", type: "bar", data: capex },
      { name: "Free CF", type: "bar", data: fcf },
    ],
  };
}
