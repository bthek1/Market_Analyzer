---
name: frontend-stack
description: "Frontend dependency stack and versions after the 2026-06-15 upgrade to latest (React 19, Vite 8, Vitest 4, Zod 4, TS 6, ESLint 10)"
metadata:
  type: project
---

## Frontend Stack (upgraded to latest 2026-06-15)

The whole `frontend/` dependency set was bumped to current latest. Source of truth is
`frontend/package.json`; this records the major versions and the one migration gotcha so
future sessions don't assume the old React 18 / Vite 6 baseline.

### Major versions

| Area | Package | Version |
|---|---|---|
| Core | react / react-dom | **19.2** |
| Core | typescript | **6.0** |
| Build | vite | **8.0** (`@vitejs/plugin-react` 6) |
| Test | vitest | **4.1** (Testing Library, MSW 2, happy-dom / jsdom) |
| Routing | @tanstack/react-router | 1.170 (+ router-plugin / devtools) |
| Data | @tanstack/react-query | 5.101 |
| HTTP | axios | 1.18 |
| State | zustand 5 + immer 11 | |
| Forms | react-hook-form 7.79 + zod **4.4** (`@hookform/resolvers` 5) |
| Styling | tailwindcss 4 + tailwind-merge 3; shadcn (base-nova) on `@base-ui/react` 1.5 |
| Charts | echarts 6 + recharts **3** (two libs still present) |
| Lint | eslint **10** + typescript-eslint 8 + `eslint-plugin-react-hooks` **7** |

### Migration notes

- Zod 4, Recharts 3, and React 19 needed **zero source changes** in our usage (typecheck +
  all 668 tests green).
- `eslint-plugin-react-hooks` v7 ships the React-Compiler rule `react-hooks/set-state-in-effect`.
  It flagged 4 pre-existing, correct effect patterns; each is suppressed with a targeted
  `eslint-disable-next-line ... -- <reason>` comment (no behaviour change):
  `hooks/useElapsed.ts`, `components/companies/SyncPanel.tsx`, `routes/market-map.tsx`,
  `routes/agents.tsx`.
- The `react-refresh/only-export-components` warnings on route files are pre-existing and
  expected (TanStack Router files export both a component and a `Route`); lint still exits 0.
- Build emits a chunk-size warning (main JS ~2 MB / 636 kB gzip) — code-splitting / dropping
  one chart lib is an open follow-up. See [[echarts]].

### Verification baseline after upgrade

`tsc --noEmit` clean, `npm run build` clean, `npm run lint` 0 errors, `npm run test` 668 passing.
