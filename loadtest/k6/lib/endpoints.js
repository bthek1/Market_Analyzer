// Every endpoint the load test may call, as a TEMPLATE. The template is both the request
// path (with {id} substituted, lib/api.js) and the `name` tag, so the two cannot drift -
// and it is the key the per-endpoint thresholds are generated from (lib/profiles.js).
//
// `kind` groups endpoints for the latency budgets. Read-only traffic ONLY: no /api/llm/
// (GPU-bound), no /sync/ or /yf/ (they call Yahoo), no /api/health/ inside the iteration
// (it broadcasts a Celery ping and probes Ollama). The contract test resolves every path
// here against Django's URL conf and rejects those prefixes.

export const ENDPOINTS = {
  companies: { path: '/api/companies/', kind: 'list' },
  company: { path: '/api/companies/{id}/', kind: 'detail' },
  prices: { path: '/api/companies/{id}/prices/', kind: 'list' },
  snapshots: { path: '/api/companies/{id}/snapshots/', kind: 'list' },
  financials: { path: '/api/companies/{id}/financials/', kind: 'list' },
  dividends: { path: '/api/companies/{id}/dividends/', kind: 'list' },
  sectors: { path: '/api/companies/sectors/', kind: 'list' },
  hierarchy: { path: '/api/companies/market-hierarchy/', kind: 'aggregate' },
  freshness: { path: '/api/companies/sync-freshness/', kind: 'aggregate' },
  me: { path: '/api/accounts/me/', kind: 'detail' },
};

// Auth calls are made by lib/auth.js, not the journey, but are measured the same way.
export const AUTH_ENDPOINTS = {
  login: { path: '/api/auth/login/', kind: 'auth' },
  refresh: { path: '/api/auth/token/refresh/', kind: 'auth' },
};
