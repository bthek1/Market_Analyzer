import { check } from 'k6';

// Check names are FIXED strings: each one becomes a value of the `check` tag, i.e. a
// Prometheus label, so interpolating an id or a path into one would be unbounded.

function parses(res) {
  try {
    res.json();
    return true;
  } catch (_err) {
    return false;
  }
}

export function ok(res) {
  return check(res, {
    'status is 200': (r) => r.status === 200,
    'body is JSON': (r) => parses(r),
  });
}

// DRF's PageNumberPagination envelope. A list endpoint that silently loses pagination
// returns a bare array - which "passes" a status check while shipping the whole table.
export function okPage(res) {
  return check(res, {
    'status is 200': (r) => r.status === 200,
    'body is JSON': (r) => parses(r),
    'paginated (count + results)': (r) => {
      if (!parses(r)) return false;
      const body = r.json();
      return typeof body.count === 'number' && Array.isArray(body.results);
    },
  });
}
