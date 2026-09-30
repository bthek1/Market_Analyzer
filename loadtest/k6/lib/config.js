// Every knob comes from __ENV. The `just lt*` recipes load the repo-root .env, so the
// values live there (LOADTEST_* keys in .env.example) and never in this directory.
//
// This module runs in the INIT context of every VU, which is what makes the prod guard
// below binding: it throws before a single request is sent, including under `k6 inspect`,
// and it is enforced here rather than only in the justfile so running `k6 run` by hand
// does not bypass it.

export const TARGETS = {
  local: 'http://localhost:8004',
  // nginx on the app container, i.e. the path real users take.
  prod: 'http://192.168.2.200',
};

// Hosts that ARE prod whatever LOADTEST_TARGET says, so pointing LOADTEST_BASE_URL at
// the app container under TARGET=local is still caught.
const PROD_HOSTS = ['192.168.2.200', 'stockmarket', 'stockmarket.local'];

export const PROFILE = __ENV.LOADTEST_PROFILE || 'smoke';
export const TARGET = __ENV.LOADTEST_TARGET || 'local';

if (!(TARGET in TARGETS)) {
  throw new Error(`LOADTEST_TARGET must be one of ${Object.keys(TARGETS).join(', ')}, got "${TARGET}"`);
}

export const BASE_URL = (__ENV.LOADTEST_BASE_URL || TARGETS[TARGET]).replace(/\/+$/, '');

function hostOf(url) {
  const match = /^[a-z]+:\/\/([^/:]+)/i.exec(url);
  return match ? match[1].toLowerCase() : '';
}

export const IS_PROD = TARGET === 'prod' || PROD_HOSTS.includes(hostOf(BASE_URL));

if (IS_PROD && __ENV.LOADTEST_ALLOW_PROD !== '1') {
  throw new Error(
    `refusing to load-test prod (${BASE_URL}) without LOADTEST_ALLOW_PROD=1 - ` +
      'set it for this one run, never leave it in .env',
  );
}

// A dedicated non-staff account (manage.py ensure_loadtest_user). The password is only
// required once setup() logs in, so `k6 inspect` works without one.
export const EMAIL = __ENV.LOADTEST_EMAIL || 'loadtest@stockmarket.local';
export const PASSWORD = __ENV.LOADTEST_PASSWORD || '';

// One value per run, attached to every sample as the `testid` tag, so runs can be told
// apart and compared in Grafana. The just recipe stamps profile-target-timestamp.
export const TESTID = __ENV.LOADTEST_TESTID || `${PROFILE}-${TARGET}-adhoc`;

export const RESULTS_DIR = __ENV.LOADTEST_RESULTS_DIR || 'loadtest/results';

// Access tokens live 15 minutes (SIMPLE_JWT.ACCESS_TOKEN_LIFETIME). Refreshing at 10
// leaves margin for clock skew and a slow refresh under load. Lower it to exercise the
// refresh path in a short run.
export const TOKEN_REFRESH_S = Number(__ENV.LOADTEST_TOKEN_REFRESH_S || 600);

// k6 tags every request with its full `url` by default, and every tag becomes a
// Prometheus label: /api/companies/123/prices/ would be one series PER COMPANY. So the
// system tags are an explicit allow-list with url/vu/iter left out, and every request
// carries a templated `name` tag instead (lib/api.js). Pinned by
// backend/core/tests/test_loadtest_contract.py.
export const SYSTEM_TAGS = [
  'status',
  'method',
  'name',
  'group',
  'check',
  'error',
  'error_code',
  'scenario',
  'expected_response',
];
