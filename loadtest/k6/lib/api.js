import http from 'k6/http';

import { authHeaders, forceRefresh } from './auth.js';
import { BASE_URL } from './config.js';

function queryString(query) {
  const pairs = Object.entries(query || {}).filter(([, value]) => value !== undefined);
  if (!pairs.length) return '';
  return '?' + pairs.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&');
}

// GET an endpoint from lib/endpoints.js. The `name` tag is always the TEMPLATE, never the
// concrete path, and the query string is left out of it too - that is what keeps
// Prometheus at one series per endpoint rather than one per company or search term.
export function get(endpoint, session, { id, query } = {}) {
  const path = id === undefined ? endpoint.path : endpoint.path.replace('{id}', String(id));
  const url = BASE_URL + path + queryString(query);
  const tags = { name: endpoint.path };
  // Far past any healthy response. A request slower than this counts as a failure
  // instead of pinning a VU for k6's 60 s default - past the knee, that is what
  // exhausts maxVUs and turns a latency finding into dropped iterations.
  const timeout = '10s';

  let res = http.get(url, { headers: authHeaders(session), tags, timeout });
  if (res.status === 401) {
    forceRefresh(session);
    res = http.get(url, { headers: authHeaders(session), tags, timeout });
  }
  return res;
}
