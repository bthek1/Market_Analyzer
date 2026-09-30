// One workload, several SHAPES. A profile is only a k6 scenario block plus its threshold
// set; the endpoints are defined once in the scenario file, never per profile.
//
// Everything past smoke is an OPEN model (ramping-arrival-rate): new iterations start
// at the configured rate whether or not the server keeps up. A closed model (N VUs in a
// loop) slows its own arrival rate down as the server slows, which hides exactly the
// saturation these profiles exist to find. The give-away of an open model hitting its
// ceiling is `dropped_iterations` - k6 ran out of VUs to start iterations on time.
//
// Rates are PAGE VIEWS per second (one iteration = one page of the journey, 1-3
// requests), set by LOADTEST_RATE - the expected peak.

import { ENDPOINTS, AUTH_ENDPOINTS } from './endpoints.js';

export const RATE = Number(__ENV.LOADTEST_RATE || 5);
const MAX_VUS = Number(__ENV.LOADTEST_MAX_VUS || 200);

// p95 budgets in ms per endpoint kind. PLACEHOLDERS until issue #12 phase 4 measures the
// prod baseline; after that they are baseline p95 plus headroom and the contract test
// pins them to docs/project_docs/load-testing.md.
export const BUDGETS_MS = {
  list: 1000,
  detail: 500,
  aggregate: 2000,
  auth: 2000,
};

function arrival(startRate, stages) {
  return {
    executor: 'ramping-arrival-rate',
    startRate,
    timeUnit: '1s',
    preAllocatedVUs: Math.min(20, MAX_VUS),
    maxVUs: MAX_VUS,
    stages: stages.map(([duration, target]) => ({ duration, target: Math.max(0, Math.round(target)) })),
  };
}

// Step up by one RATE every 3 minutes (a 1 minute ramp, a 2 minute hold) to 10x peak.
// Nobody expects it to reach the top: the thresholds abort the run at the knee, which is
// the number this profile exists to produce.
function stressStages() {
  const stages = [];
  for (let step = 1; step <= 10; step += 1) {
    stages.push(['1m', RATE * step], ['2m', RATE * step]);
  }
  stages.push(['1m', 0]);
  return stages;
}

export const PROFILES = {
  // Closed model on purpose: it only proves the scripts work, and 1 VU with think time
  // is the gentlest thing that exercises every page.
  smoke: { executor: 'constant-vus', vus: 1, duration: '30s' },
  load: arrival(0, [
    ['2m', RATE],
    ['10m', RATE],
    ['1m', 0],
  ]),
  stress: arrival(0, stressStages()),
  // Zero to 5x peak in 10 s, then back - does the app RECOVER (connection pool, worker
  // backlog), and how long does the latency tail take to drain?
  spike: arrival(1, [
    ['30s', 1],
    ['10s', RATE * 5],
    ['1m', RATE * 5],
    ['10s', 1],
    ['3m', 1],
  ]),
  // Over an hour at half peak: memory growth in the gunicorn workers, connection leaks,
  // and several access-token expiries (15 min) - where lib/auth.js's refresh is proven.
  soak: arrival(0, [
    ['2m', RATE / 2],
    ['70m', RATE / 2],
    ['1m', 0],
  ]),
};

// Whether a profile's iterations should sleep. Only the closed model: under an arrival
// rate the RATE is the think time, and sleeping would only pin more VUs.
export function usesThinkTime(profile) {
  return PROFILES[profile].executor === 'constant-vus';
}

// abortOnFail everywhere, so a run against prod stops itself instead of relying on
// someone watching. delayAbortEval keeps the first few cold-cache samples from tripping
// it before the numbers mean anything.
function abort(threshold, delay) {
  return { threshold, abortOnFail: true, delayAbortEval: delay };
}

export function thresholds() {
  const out = {
    http_req_failed: [abort('rate<0.01', '30s')],
    checks: [abort('rate>0.99', '30s')],
  };
  for (const endpoint of [...Object.values(ENDPOINTS), ...Object.values(AUTH_ENDPOINTS)]) {
    out[`http_req_duration{name:${endpoint.path}}`] = [
      abort(`p(95)<${BUDGETS_MS[endpoint.kind]}`, '1m'),
    ];
  }
  return out;
}

export function scenarioFor(profile) {
  if (!(profile in PROFILES)) {
    throw new Error(`LOADTEST_PROFILE must be one of ${Object.keys(PROFILES).join(', ')}, got "${profile}"`);
  }
  return PROFILES[profile];
}
