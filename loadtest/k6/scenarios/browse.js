// The read-only "analyst browsing" workload (issue #12).
//
//   just lt-smoke                 1 VU, 30 s, local
//   just lt load local            LOADTEST_PROFILE / LOADTEST_TARGET, see lib/profiles.js
//
// One iteration is ONE page view, picked by weight, making the requests that page makes.
// Company ids come from the list endpoint in setup(), never hard-coded, so the same
// script works against dev and prod.

import { sleep } from 'k6';
import exec from 'k6/execution';

import { get } from '../lib/api.js';
import { login } from '../lib/auth.js';
import { ok, okPage } from '../lib/checks.js';
import { PROFILE, SYSTEM_TAGS, TESTID } from '../lib/config.js';
import { ENDPOINTS as E } from '../lib/endpoints.js';
import { preflight } from '../lib/preflight.js';
import { scenarioFor, thresholds, usesThinkTime } from '../lib/profiles.js';
import { summarise } from '../lib/summary.js';

export const options = {
  scenarios: { [PROFILE]: { ...scenarioFor(PROFILE), exec: 'browse' } },
  thresholds: thresholds(),
  systemTags: SYSTEM_TAGS,
  tags: { testid: TESTID },
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)', 'count'],
};

const MAX_SETUP_PAGES = 5;

export function setup() {
  preflight();
  const session = login();

  // Bootstrapped companies are the ones with prices/financials behind them - the pages
  // a user actually opens. A stub would measure an empty query.
  const companies = [];
  for (let page = 1; page <= MAX_SETUP_PAGES; page += 1) {
    const res = get(E.companies, session, { query: { is_bootstrapped: 'true', page } });
    if (res.status !== 200) break;
    const body = res.json();
    for (const row of body.results) companies.push({ id: row.id, symbol: row.symbol });
    if (!body.next) break;
  }
  if (!companies.length) {
    exec.test.abort('no bootstrapped companies to browse - ingest some first');
  }
  const listPages = Math.max(1, Math.ceil(companies.length / 20));
  return { ...session, companies, listPages };
}

function pick(list) {
  return list[Math.floor(Math.random() * list.length)];
}

function randint(lo, hi) {
  return lo + Math.floor(Math.random() * (hi - lo + 1));
}

// Pages of the SPA and the API calls each one makes. Weights are a guess at an analyst's
// session (mostly company pages), not a measurement - there is no production traffic log
// of the read mix to derive them from.
const PAGES = [
  {
    weight: 20,
    name: 'companies list',
    run: (s) => {
      const ordering = pick(['symbol', '-market_cap', '-dividend_yield']);
      okPage(get(E.companies, s, { query: { page: randint(1, s.listPages), ordering } }));
    },
  },
  {
    weight: 10,
    name: 'company search',
    run: (s) => {
      const symbol = pick(s.companies).symbol;
      okPage(get(E.companies, s, { query: { search: symbol.slice(0, randint(1, 2)) } }));
    },
  },
  {
    weight: 25,
    name: 'company overview',
    run: (s) => {
      const id = pick(s.companies).id;
      ok(get(E.company, s, { id }));
      okPage(get(E.prices, s, { id, query: { ordering: '-date' } }));
      okPage(get(E.snapshots, s, { id }));
    },
  },
  {
    weight: 10,
    name: 'financials tab',
    run: (s) => okPage(get(E.financials, s, { id: pick(s.companies).id, query: { period: 'annual' } })),
  },
  {
    weight: 5,
    name: 'dividends tab',
    run: (s) => okPage(get(E.dividends, s, { id: pick(s.companies).id })),
  },
  { weight: 10, name: 'sectors', run: (s) => okPage(get(E.sectors, s)) },
  {
    weight: 8,
    name: 'market map',
    run: (s) => ok(get(E.hierarchy, s, { query: { metric: pick(['count', 'market_cap']) } })),
  },
  { weight: 5, name: 'sync freshness', run: (s) => ok(get(E.freshness, s)) },
  { weight: 7, name: 'account', run: (s) => ok(get(E.me, s)) },
];

const TOTAL_WEIGHT = PAGES.reduce((sum, p) => sum + p.weight, 0);
const THINK = usesThinkTime(PROFILE);

function choosePage() {
  let roll = Math.random() * TOTAL_WEIGHT;
  for (const page of PAGES) {
    roll -= page.weight;
    if (roll < 0) return page;
  }
  return PAGES[PAGES.length - 1];
}

export function browse(session) {
  // Smoke visits the pages in turn, so its ~15 iterations are guaranteed to touch every
  // endpoint; a random draw that skips one would "pass" without testing it. The load
  // profiles draw by weight.
  const page = THINK ? PAGES[exec.scenario.iterationInTest % PAGES.length] : choosePage();
  page.run(session);
  if (THINK) sleep(1 + Math.random() * 2);
}

export function handleSummary(data) {
  return summarise(data);
}
