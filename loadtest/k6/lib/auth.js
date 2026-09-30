import http from 'k6/http';
import { Counter } from 'k6/metrics';

import { BASE_URL, EMAIL, PASSWORD, TOKEN_REFRESH_S } from './config.js';
import { AUTH_ENDPOINTS } from './endpoints.js';

// How often a VU had to refresh. A soak run (> 15 min) that shows zero here never
// exercised the path it exists to prove.
const refreshes = new Counter('auth_refreshes');

const JSON_HEADERS = { 'Content-Type': 'application/json' };

// dj-rest-auth with JWT_AUTH_HTTPONLY=True returns the ACCESS token in the body but
// blanks `refresh` there ("") and sets it only as the HttpOnly `refresh-token` cookie.
// So the refresh token is read from the response cookie. The refresh endpoint accepts
// it back in the body ("Will override cookie").
function tokensFrom(res) {
  const body = res.json();
  const cookie = (res.cookies['refresh-token'] || [])[0];
  return { access: body.access, refresh: body.refresh || (cookie && cookie.value) || '' };
}

// Called from setup(): one login for the whole run, handed to every VU via setup data.
// A login per VU would make "logins/s" part of every profile's load, which it is not in
// real use.
export function login() {
  if (!PASSWORD) {
    throw new Error('LOADTEST_PASSWORD is not set - see manage.py ensure_loadtest_user');
  }
  const res = http.post(
    BASE_URL + AUTH_ENDPOINTS.login.path,
    JSON.stringify({ email: EMAIL, password: PASSWORD }),
    { headers: JSON_HEADERS, tags: { name: AUTH_ENDPOINTS.login.path } },
  );
  if (res.status !== 200) {
    throw new Error(`login as ${EMAIL} failed: HTTP ${res.status} ${String(res.body).slice(0, 200)}`);
  }
  const tokens = tokensFrom(res);
  if (!tokens.access || !tokens.refresh) {
    throw new Error('login returned no access token or no refresh-token cookie');
  }
  return { ...tokens, issuedAt: Date.now() };
}

// Per-VU state. Module scope is per VU in k6, and VUs are reused across iterations, so
// this is each VU's own copy of the token, refreshed independently.
let access = null;
let issuedAt = 0;

function refresh(session) {
  const res = http.post(
    BASE_URL + AUTH_ENDPOINTS.refresh.path,
    JSON.stringify({ refresh: session.refresh }),
    { headers: JSON_HEADERS, tags: { name: AUTH_ENDPOINTS.refresh.path } },
  );
  if (res.status === 200 && res.json('access')) {
    access = res.json('access');
    issuedAt = Date.now();
    refreshes.add(1);
    return;
  }
  // ROTATE_REFRESH_TOKENS is on but BLACKLIST_AFTER_ROTATION is off, so the setup
  // token stays valid for its 7 days and every VU can share it. If that ever changes,
  // fall back to a fresh login rather than failing every request from here on.
  const fresh = login();
  access = fresh.access;
  issuedAt = fresh.issuedAt;
  refreshes.add(1);
}

export function authHeaders(session) {
  if (access === null) {
    access = session.access;
    issuedAt = session.issuedAt;
  }
  if ((Date.now() - issuedAt) / 1000 > TOKEN_REFRESH_S) {
    refresh(session);
  }
  return { Authorization: `Bearer ${access}` };
}

// A 401 mid-run means the token died early (server restart with a new SECRET_KEY, a
// clock jump). Refresh once; the 401 itself still counts in http_req_failed.
export function forceRefresh(session) {
  refresh(session);
}
