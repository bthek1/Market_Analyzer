# Web App — UI Kit

Pixel-faithful recreation of the React frontend in **bthek1/Market_Analyzer**
(`frontend/src/`). This kit mirrors the routes that actually ship today
plus a couple that are implied by the backend (auth → dashboard → stocks
→ stock detail → watchlist).

## What's here

- `index.html` — single-page interactive prototype that lets you sign in
  (any email + 8+ char password is accepted), browse stocks, view a
  detail page with a Recharts price line, add/remove from the watchlist,
  and log out. Routing is fake — driven by React state — so everything
  runs offline.
- `App.jsx` — top-level state machine (auth → route).
- `AppShell.jsx` — sticky-style top nav with wordmark + nav links + user
  email + logout. Copy mirrors `frontend/src/components/layout/AppShell.tsx`.
- `Auth.jsx` — sign-in and create-account cards. Copy mirrors
  `frontend/src/routes/login.tsx` and `register.tsx` including the same
  error messages, placeholder text, and field labels.
- `StocksList.jsx` — search bar + stocks table.
- `StockDetail.jsx` — symbol header, watchlist toggle, Recharts line.
- `Watchlist.jsx` — table with remove links and empty state.
- `data.js` — seed stocks + 90 days of fake OHLC so the chart renders
  without a backend.

## What's intentionally faked

- Auth has no real JWT — we just store an email in component state.
- Prices are deterministic noise around a seeded base, not real quotes.
- Search is local string-includes filtering, not the DRF endpoint.

## What it's faithful to

- Tailwind v4 utility patterns (the only styling layer the codebase
  uses).
- The exact color palette: blue-600 primary, gray-50 page bg, red-600
  destructive, gray-200 borders.
- Copy strings — empty state, errors, button labels — are lifted verbatim
  where they exist.
- The chart stroke is `#2563eb` (blue-600), hard-coded in the original
  `PriceChart.tsx`.

## Stack

- React 18 UMD + Babel standalone (no build step)
- Tailwind via Play CDN
- Recharts UMD
- All loaded from `unpkg`
