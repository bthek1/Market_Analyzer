// handleSummary: a JSON file per run in loadtest/results/ (gitignored) so runs can be
// diffed, plus a compact per-endpoint table on stdout. Written here rather than imported
// from jslib.k6.io so a run needs nothing from the internet.

import { PROFILE, RESULTS_DIR, TARGET, TESTID } from './config.js';

function fmt(value, digits = 1) {
  return value === undefined || value === null ? '-' : Number(value).toFixed(digits);
}

function pad(text, width) {
  const s = String(text);
  return s.length >= width ? s : s + ' '.repeat(width - s.length);
}

export function summarise(data) {
  const m = data.metrics;
  const lines = [];
  lines.push('');
  lines.push(`testid ${TESTID}  profile ${PROFILE}  target ${TARGET}`);
  const reqs = m.http_reqs ? m.http_reqs.values : {};
  const failed = m.http_req_failed ? m.http_req_failed.values.rate : undefined;
  const checks = m.checks ? m.checks.values.rate : undefined;
  const dropped = m.dropped_iterations ? m.dropped_iterations.values.count : 0;
  lines.push(
    `requests ${reqs.count || 0} (${fmt(reqs.rate, 2)}/s)  failed ${fmt((failed || 0) * 100, 2)}%  ` +
      `checks ${fmt((checks || 0) * 100, 2)}%  dropped iterations ${dropped}`,
  );
  if (m.auth_refreshes) lines.push(`token refreshes ${m.auth_refreshes.values.count}`);
  lines.push('');
  lines.push(`${pad('endpoint', 40)} ${pad('count', 7)} ${pad('p50', 8)} ${pad('p95', 8)} ${pad('p99', 8)} ${pad('max', 8)} ok`);

  const rows = Object.keys(m)
    .filter((key) => key.startsWith('http_req_duration{name:'))
    .sort();
  for (const key of rows) {
    const v = m[key].values;
    const name = key.slice('http_req_duration{name:'.length, -1);
    const passed = Object.values(m[key].thresholds || {}).every((t) => t.ok);
    lines.push(
      `${pad(name, 40)} ${pad(v.count || 0, 7)} ${pad(fmt(v.med), 8)} ${pad(fmt(v['p(95)']), 8)} ` +
        `${pad(fmt(v['p(99)']), 8)} ${pad(fmt(v.max), 8)} ${passed ? 'yes' : 'NO'}`,
    );
  }

  const breached = [];
  for (const [key, metric] of Object.entries(m)) {
    for (const [expr, result] of Object.entries(metric.thresholds || {})) {
      if (!result.ok) breached.push(`${key}: ${expr}`);
    }
  }
  lines.push('');
  lines.push(breached.length ? `THRESHOLDS BREACHED:\n  ${breached.join('\n  ')}` : 'all thresholds passed');
  lines.push('');

  return {
    stdout: lines.join('\n'),
    [`${RESULTS_DIR}/${TESTID}.json`]: JSON.stringify(data, null, 2),
  };
}
