import type { ChartNode } from "@/types/companies";

export function stripUndefinedNodes(nodes: ChartNode[]): ChartNode[] {
  return nodes
    .filter((n) => n.name && n.name !== "undefined")
    .map((n) => ({
      ...n,
      children: n.children ? stripUndefinedNodes(n.children) : undefined,
    }));
}

export function formatMarketCap(value: number): string {
  if (value >= 1e12) return `$${(value / 1e12).toFixed(1)}T`;
  if (value >= 1e9) return `$${(value / 1e9).toFixed(1)}B`;
  if (value >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
  return `$${value.toLocaleString()}`;
}
