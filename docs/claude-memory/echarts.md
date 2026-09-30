---
name: echarts
description: "ECharts v6 + echarts-for-react v3 — full reference: chart types, API, patterns, TypeScript, performance, testing, v6 changes"
metadata: 
  node_type: memory
  type: project
  originSessionId: 2eb2bce6-71b8-422e-9cb4-85ebbd82aadd
---

## Stack (this project)

- **echarts** v6.1.0 + **echarts-for-react** v3.0.6
- Import: `import ReactECharts from "echarts-for-react"` (default export)
- Types: `import type { EChartsOption } from "echarts"`
- Both recharts and echarts are installed; ECharts is the active library

---

## Chart Types ECharts Supports

| Type | Series value | Notes |
|---|---|---|
| Line | `"line"` | trend analysis |
| Bar | `"bar"` | categorical comparisons; horizontal by swapping xAxis/yAxis types |
| Scatter | `"scatter"` | correlation; supports jittering (v6) |
| Pie | `"pie"` | proportions |
| Candlestick | `"candlestick"` | financial OHLC; data order = `[open, close, low, high]` |
| Boxplot | `"boxplot"` | statistics |
| Heatmap | `"heatmap"` | density |
| Treemap | `"treemap"` | hierarchical; `leafDepth`, `levels`, `breadcrumb` |
| Sunburst | `"sunburst"` | radial hierarchy; `nodeClick: "rootToNode"` |
| Graph | `"graph"` | relationship networks |
| Lines | `"lines"` | directional flows on map/cartesian |
| Map | `"map"` | geographic |
| Parallel | `"parallel"` | multi-dimensional |
| Funnel | `"funnel"` | conversion |
| Gauge | `"gauge"` | measurement |
| Custom | `"custom"` | user-defined via `renderItem` callback |
| Chord | `"chord"` | NEW in v6 — relationship networks with gradient edges |
| Beeswarm | `"beeswarm"` | NEW in v6 — non-overlapping scatter on category axis |

---

## ECharts v6 Key Changes (upgrading from v5)

**New in v6:**
- Chord and Beeswarm chart types
- New default theme with design tokens (different colors and padding from v5)
- Dynamic theme switching at runtime without chart disposal
- Dark mode with system preference detection
- Matrix coordinate system (covariance matrices, periodic tables)
- Broken axis with torn-paper effect (`type: "break"`)
- Enhanced candlestick label positioning for stock trading UIs
- Axis label overflow + overlap prevention enabled by default

**Breaking changes (v5 → v6):**
- Default theme colors changed — to keep v5 look: `import 'echarts/theme/v5'` and `echarts.init(el, 'v5')`
- Axis labels/names may shift due to new overflow prevention — disable with `grid.outerBoundsMode: "none"` or `xAxis.nameMoveOverlap: false`
- Rich text now inherits plain label styles by default — disable with `richInheritPlainLabel: false`
- Most apps need **no changes** — v6 is broadly backward compatible

---

## echarts-for-react Props

| Prop | Type | Default | Notes |
|---|---|---|---|
| `option` | `EChartsOption` | required | chart config |
| `style` | `CSSProperties` | `{height:"300px"}` | always set explicit height |
| `className` | `string` | — | CSS class on container div |
| `theme` | `string` | — | registered theme name |
| `notMerge` | `boolean` | `false` | `true` = full replace on every option update |
| `replaceMerge` | `string \| string[]` | — | selective replace on `setOption` |
| `lazyUpdate` | `boolean` | `false` | defer rendering to next frame |
| `showLoading` | `boolean` | `false` | loading mask |
| `loadingOption` | `object` | — | loading mask config |
| `onChartReady` | `(instance) => void` | — | called once after init |
| `onEvents` | `Record<string, fn>` | — | event bindings (`click`, `mouseover`, etc.) |
| `opts` | `object` | — | passed to `echarts.init()` — e.g. `{renderer:"svg"}` |
| `autoResize` | `boolean` | `true` | window resize auto-triggers chart resize |

**Getting the ECharts instance (ref pattern):**
```ts
const ref = useRef<InstanceType<typeof ReactECharts>>(null);
const instance = ref.current?.getEchartsInstance();
// instance gives access to: resize(), getDataURL(), setOption(), dispose(), on/off()
```

---

## TypeScript — Full Import vs Tree-Shaking

**This project uses full import** (simplest, fine at current scale):
```ts
import ReactECharts from "echarts-for-react";
import type { EChartsOption } from "echarts";
```

**Tree-shaking (use if bundle size becomes a concern):**
Switch to `ReactEChartsCore` with selective imports — can eliminate ~4 MB from bundle:
```ts
import ReactEChartsCore from "echarts-for-react/lib/core";
import { init, use } from "echarts/core";
import { BarChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
use([BarChart, GridComponent, TooltipComponent, CanvasRenderer]);

// Compose a strict type from only used components:
import type { ComposeOption } from "echarts/core";
import type { BarSeriesOption } from "echarts/charts";
import type { GridComponentOption } from "echarts/components";
type EChartsOption = ComposeOption<BarSeriesOption | GridComponentOption>;
```
Gotcha: animations may disappear without certain imports — watch console warnings for missing dependencies.

---

## This Project's Chart Components

All in [frontend/src/components/companies/](frontend/src/components/companies/):

| File | Chart type | Key prop |
|---|---|---|
| [PriceChart.tsx](frontend/src/components/companies/PriceChart.tsx) | Candlestick + dataZoom | `bars: PriceBar[]` |
| [SectorDistributionChart.tsx](frontend/src/components/companies/SectorDistributionChart.tsx) | Horizontal bar | `data: { name, count }[]` |
| [IndustriesBySectorChart.tsx](frontend/src/components/companies/IndustriesBySectorChart.tsx) | Vertical bar (rotated labels) | `data: { name, count }[]` |
| [SectorIndustrySunburst.tsx](frontend/src/components/companies/SectorIndustrySunburst.tsx) | Sunburst (2-level: sector → industry) | `data: ChartNode[]` |
| [SectorIndustryTreemap.tsx](frontend/src/components/companies/SectorIndustryTreemap.tsx) | Treemap (2-level: sector → industry) | `data: ChartNode[]` |

**Candlestick data order**: `[open, close, low, high]` — NOT the intuitive OHLC order.

**SECTOR_COLORS**: Tableau-10 palette (12 colors) defined in `SectorIndustrySunburst.tsx`, re-exported for Treemap.

---

## Established Patterns

**Option builder pattern**: every chart exports a pure `build*Option(data): EChartsOption` alongside its React component. Tests call the builder directly. Always do this for new charts.

**Event handling**: `onEvents={{ click: (params) => void }}`. For hierarchical charts, `params.treePathInfo.length - 1` gives the depth (0 = root, 1 = sector, 2 = industry).

**Sizing**: always pass explicit `style={{ height: N }}`. Dynamic bar chart height: `Math.max(200, data.length * 44)`.

**notMerge**: keep `false` (default) for incremental updates. Only use `true` when you need a clean slate on each render.

**Center label overlay**: for sunburst center text, use an absolutely-positioned React `<div>` with `pointerEvents: "none"` instead of ECharts `graphic` elements — avoids `setOption` calls that reset zoom/state.

**Tooltip HTML**: formatter must return an HTML string with inline styles. No Tailwind classes — ECharts renders outside React's DOM.

**formatter type casting**: ECharts types `params` as `unknown`. Cast with `const p = params as { data: ChartNode }` or `as { axisValue: string; data: number[] }[]`. No runtime validation needed.

---

## Performance

- **TypedArray**: pass `Float64Array` / `Int32Array` instead of plain arrays for large datasets — less memory, faster rendering
- **Incremental rendering**: ECharts v4+ can render millions of points; enable with `progressive` and `progressiveThreshold` on the series
- **Lazy loading**: for pages with many charts, only initialize charts when they scroll into view (IntersectionObserver)
- **Dataset sharing**: ECharts v6 shares dataset storage across series — memory scales well with many series on the same data
- **SVG renderer**: `opts={{ renderer: "svg" }}` — better for static/exported charts, worse for animation-heavy charts; Canvas is the default and generally faster

---

## Memory Leaks & Cleanup

`echarts-for-react` handles `dispose()` on unmount automatically. When using the raw ECharts API (no wrapper), always call `echarts.dispose(domElement)` in cleanup. Active issues exist in the community around resubscribing to `restore` event handlers — avoid adding raw `chart.on()` listeners inside React components without a corresponding `chart.off()` in useEffect cleanup.

---

## Rendering: SVG vs Canvas

| | Canvas (default) | SVG |
|---|---|---|
| Performance | Better for large data / animation | Better for small datasets / static |
| Export | `getDataURL()` → PNG | Native SVG DOM — selectable text |
| Accessibility | Needs aria overlays | Native SVG semantics |
| Usage | `opts={{ renderer: "canvas" }}` | `opts={{ renderer: "svg" }}` |

---

## Testing

**Always mock** `echarts-for-react` — canvas doesn't work in jsdom:

```ts
vi.mock("echarts-for-react", () => ({
  default: () => <div data-testid="echart" />,
}));
```

**To test click events**, have the mock invoke `onEvents`:
```ts
vi.mock("echarts-for-react", () => ({
  default: ({ onEvents }: { onEvents?: Record<string, (p: unknown) => void> }) => (
    <div
      data-testid="echart"
      onClick={() => onEvents?.["click"]?.({ data: { name: "Sector" }, treePathInfo: [null] })}
    />
  ),
}));
```

Test files: `frontend/src/components/companies/__tests__/` and `frontend/src/routes/__tests__/`.

**Test the option builder, not the chart render** — assert shapes like `series[0].type`, `xAxis.data`, `dataZoom[0].start`.

---

## Theming

- `theme` prop on `ReactECharts` applies a registered theme by name
- v6 ships `echarts/theme/v5` for backward-compatible v5 colors
- Custom themes: register once via `echarts.registerTheme("name", themeObj)` before init
- Dynamic theme switching (new in v6): update the `theme` prop without disposing the chart

---

## Useful ECharts Instance Methods (via `getEchartsInstance()`)

- `setOption(option, notMerge?)` — update chart config
- `resize(opts?)` — trigger manual resize
- `getDataURL({ type, pixelRatio, backgroundColor })` — export as image
- `on(eventName, handler)` / `off(eventName, handler)` — raw event binding
- `dispose()` — destroy instance and free memory
- `showLoading()` / `hideLoading()` — manual loading mask control
- `dispatchAction({ type, ... })` — programmatically trigger interactions (e.g., highlight, dataZoom)
