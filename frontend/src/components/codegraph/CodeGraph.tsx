/* eslint-disable react-hooks/refs --
   Like ConceptGraph, this component reads a position map (`posRef`) during render to PIN
   already-laid-out nodes so the force layout does not reshuffle when filters change. The
   pinning is deliberately non-reactive (a ref, not state). */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactECharts from "echarts-for-react";
import type { CodeEdge, CodeLayer, CodeNode } from "@/types/codegraph";
import { cn } from "@/lib/utils";

/**
 * Colour encodes LAYER, not graphify's Leiden community.
 *
 * A categorical scale is only readable at a handful of values and this repo produces ~400
 * communities - painting those would be noise wearing the costume of information. Layer is
 * bounded, stable as the graph grows, and answers the question an architecture picture is
 * actually asked ("does the frontend reach into infra?"). Community remains a filter and is
 * shown in the detail panel.
 *
 * Slots 1-3 of the validated categorical palette (blue / orange / aqua), which clear the
 * all-pairs CVD and normal-vision floors in both light and dark mode - the all-pairs list is
 * the right one here because a force layout puts arbitrary nodes side by side. "other" takes
 * a neutral, so it never competes with a real layer for attention.
 */
const LAYER_COLORS: Record<CodeLayer, { light: string; dark: string; label: string }> = {
  backend: { light: "#2a78d6", dark: "#3987e5", label: "Backend" },
  frontend: { light: "#eb6834", dark: "#d95926", label: "Frontend" },
  infra: { light: "#1baf7a", dark: "#199e70", label: "Infra" },
  other: { light: "#8b8a85", dark: "#78776f", label: "Other" },
};

const LAYER_ORDER: CodeLayer[] = ["backend", "frontend", "infra", "other"];

/** Watches the `.dark` class the app toggles on <html>, so the chart restyles with the theme
 * instead of baking in light-mode hexes. */
function useIsDark(): boolean {
  const [isDark, setIsDark] = useState(
    () => typeof document !== "undefined" && document.documentElement.classList.contains("dark")
  );
  useEffect(() => {
    if (typeof MutationObserver === "undefined") return;
    const target = document.documentElement;
    const observer = new MutationObserver(() => setIsDark(target.classList.contains("dark")));
    observer.observe(target, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);
  return isDark;
}

function layerColor(layer: CodeLayer, isDark: boolean): string {
  const slot = LAYER_COLORS[layer] ?? LAYER_COLORS.other;
  return isDark ? slot.dark : slot.light;
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>]/g, (c) => (c === "&" ? "&amp;" : c === "<" ? "&lt;" : "&gt;"));
}

export interface CodeGraphProps {
  nodes: CodeNode[];
  edges: CodeEdge[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  /** Changing this remounts the chart for a fresh layout; keep it stable to merge in place. */
  layoutKey?: string;
  className?: string;
}

/**
 * Force-directed code graph (ECharts `graph` series).
 *
 * Encoding: colour = layer, size = degree (the god nodes must look like god nodes), edge
 * dash = confidence (EXTRACTED solid, INFERRED dashed) so "parsed" and "guessed" are never
 * confusable. Only the highest-degree nodes are labelled - a label on all 400 would be a wall
 * of text - and the legend is always present, so identity never rests on colour alone.
 */
export function CodeGraph({
  nodes,
  edges,
  selectedId,
  onSelect,
  layoutKey,
  className,
}: CodeGraphProps) {
  const isDark = useIsDark();
  const posRef = useRef<Map<string, [number, number]>>(new Map());
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const instRef = useRef<any>(null);

  const maxDegree = useMemo(
    () => nodes.reduce((m, n) => Math.max(m, n.degree), 0),
    [nodes]
  );

  // Only hubs get a permanent label; everything else reveals itself on hover.
  const labelThreshold = useMemo(() => {
    if (nodes.length <= 40) return 0;
    const sorted = [...nodes].map((n) => n.degree).sort((a, b) => b - a);
    return sorted[Math.min(24, sorted.length - 1)] ?? 0;
  }, [nodes]);

  const presentLayers = useMemo(() => {
    const seen = new Set(nodes.map((n) => n.layer));
    return LAYER_ORDER.filter((l) => seen.has(l));
  }, [nodes]);

  const capturePositions = useCallback(() => {
    const inst = instRef.current;
    if (!inst) return;
    try {
      const data = inst.getModel().getSeriesByIndex(0).getData();
      nodes.forEach((n, i) => {
        const layout = data.getItemLayout(i);
        if (layout && Number.isFinite(layout[0]) && Number.isFinite(layout[1])) {
          posRef.current.set(n.id, [layout[0], layout[1]]);
        }
      });
    } catch {
      // Internal layout API unavailable - degrade to merge-only (still no full re-layout).
    }
  }, [nodes]);

  const option = useMemo(() => {
    const pinned = posRef.current;
    const textColor = isDark ? "#c3c2b7" : "#52514e";

    const data = nodes.map((n) => {
      const pos = pinned.get(n.id);
      const selected = n.id === selectedId;
      const color = layerColor(n.layer, isDark);
      return {
        id: n.id,
        name: n.label,
        value: n.degree,
        // 8px floor keeps every marker clickable; sqrt so one 267-edge hub does not
        // squash the rest into dots.
        symbolSize:
          8 + (maxDegree ? Math.sqrt(n.degree / maxDegree) * 26 : 0) + (selected ? 6 : 0),
        x: pos?.[0],
        y: pos?.[1],
        fixed: Boolean(pos),
        itemStyle: {
          color,
          // A 2px surface ring separates overlapping marks.
          borderColor: selected ? (isDark ? "#ffffff" : "#0b0b0b") : isDark ? "#1a1a19" : "#fcfcfb",
          borderWidth: selected ? 2.5 : 2,
        },
        label: { show: selected || n.degree >= labelThreshold },
        _file: n.file,
        _line: n.line,
        _layer: n.layer,
        _module: n.module,
        _community: n.community_name,
      };
    });

    const links = edges.map((e) => ({
      source: e.source,
      target: e.target,
      value: e.relation,
      lineStyle: {
        // Provenance as line style, never colour alone: INFERRED is dashed and fainter.
        type: e.confidence === "EXTRACTED" ? "solid" : "dashed",
        opacity: e.confidence === "EXTRACTED" ? 0.55 : 0.35,
        width: e.confidence === "EXTRACTED" ? 1.1 : 0.9,
        color: isDark ? "#6b6a63" : "#a8a7a1",
        curveness: 0.08,
      },
      _relation: e.relation,
      _confidence: e.confidence,
    }));

    return {
      backgroundColor: "transparent",
      tooltip: {
        confine: true,
        formatter: (p: {
          dataType: string;
          data: Record<string, unknown>;
          name?: string;
        }) => {
          if (p.dataType === "edge") {
            const d = p.data as { _relation?: string; _confidence?: string };
            return `<b>${escapeHtml(d._relation ?? "")}</b><br/><span style="opacity:.7">${escapeHtml(
              d._confidence ?? ""
            )}</span>`;
          }
          const d = p.data as {
            _file?: string;
            _line?: string;
            _module?: string;
            _community?: string;
            value?: number;
          };
          return [
            `<b>${escapeHtml(p.name ?? "")}</b>`,
            `${escapeHtml(d._file ?? "")}${d._line ? `:${escapeHtml(d._line)}` : ""}`,
            `<span style="opacity:.7">${escapeHtml(d._module ?? "")} &middot; ${escapeHtml(
              d._community ?? ""
            )} &middot; ${d.value ?? 0} edges</span>`,
          ].join("<br/>");
        },
      },
      series: [
        {
          type: "graph",
          layout: "force",
          roam: true,
          draggable: true,
          data,
          links,
          force: { repulsion: 120, edgeLength: [40, 120], gravity: 0.06, friction: 0.2 },
          emphasis: { focus: "adjacency", scale: false },
          label: {
            position: "right",
            fontSize: 10,
            color: textColor,
            formatter: (p: { name: string }) =>
              p.name.length > 28 ? `${p.name.slice(0, 27)}…` : p.name,
          },
          lineStyle: { color: isDark ? "#6b6a63" : "#a8a7a1" },
        },
      ],
    };
  }, [nodes, edges, selectedId, isDark, maxDegree, labelThreshold]);

  return (
    <div className={cn("relative h-full w-full", className)}>
      <ReactECharts
        key={layoutKey}
        option={option}
        notMerge={false}
        lazyUpdate
        style={{ height: "100%", width: "100%" }}
        onChartReady={(inst) => {
          instRef.current = inst;
        }}
        onEvents={{
          click: (p: { dataType: string; data: { id?: string } }) => {
            if (p.dataType === "node" && p.data.id) onSelect?.(p.data.id);
          },
          finished: capturePositions,
        }}
      />
      {/* Legend is always present - with three-plus hues on screen, identity must not rest on
          colour alone (and it supplies the relief the light-mode aqua slot requires). */}
      <div className="pointer-events-none absolute bottom-3 left-3 flex flex-wrap items-center gap-3 rounded-lg border bg-card/90 px-3 py-2 text-xs shadow-sm backdrop-blur">
        {presentLayers.map((layer) => (
          <span key={layer} className="flex items-center gap-1.5">
            <span
              className="inline-block size-2.5 rounded-full"
              style={{ backgroundColor: layerColor(layer, isDark) }}
            />
            <span className="text-muted-foreground">{LAYER_COLORS[layer].label}</span>
          </span>
        ))}
        <span className="flex items-center gap-1.5 border-l pl-3">
          <svg width="18" height="6" aria-hidden="true">
            <line x1="0" y1="3" x2="18" y2="3" stroke="currentColor" strokeWidth="1.5" />
          </svg>
          <span className="text-muted-foreground">parsed</span>
        </span>
        <span className="flex items-center gap-1.5">
          <svg width="18" height="6" aria-hidden="true">
            <line
              x1="0"
              y1="3"
              x2="18"
              y2="3"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeDasharray="3 2"
            />
          </svg>
          <span className="text-muted-foreground">inferred</span>
        </span>
      </div>
    </div>
  );
}
