import http from 'k6/http';

import { BASE_URL } from './config.js';

// SETUP ONLY - never call this from an iteration. /api/health/ runs `celery inspect
// ping` (a broadcast to every worker with a 1 s timeout), `git describe` in a
// subprocess, and an HTTP probe to Ollama. Under load it would hammer the broker and
// Ollama rather than measure Django. The contract test pins that this module is the only
// place the path appears, and that it is only called inside setup().
const HEALTH = '/api/health/';

export function preflight() {
  const res = http.get(BASE_URL + HEALTH, { tags: { name: HEALTH } });
  if (res.status !== 200) {
    throw new Error(`${BASE_URL}${HEALTH} returned HTTP ${res.status} - is the app up?`);
  }
  const health = res.json();
  // Only what this workload needs. Celery, beat and Ollama are not on the read path, so
  // a load test must not refuse to run just because a worker is down locally.
  for (const dependency of ['db', 'redis']) {
    if (health[dependency] !== true) {
      throw new Error(`health reports ${dependency}=${health[dependency]}; not load-testing a broken app`);
    }
  }
  return health;
}
