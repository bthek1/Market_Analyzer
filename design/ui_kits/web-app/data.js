/* global window */
// Deterministic seed data so the prototype renders without a backend.

const SECTORS = ["Technology", "Semiconductors", "Automotive", "Financials", "Consumer", "Energy", "Health Care"];

const SEED_STOCKS = [
  { symbol: "AAPL", name: "Apple Inc.",              exchange: "NASDAQ", sector: "Technology",     base: 187.42 },
  { symbol: "NVDA", name: "NVIDIA Corporation",      exchange: "NASDAQ", sector: "Semiconductors", base: 842.16 },
  { symbol: "TSLA", name: "Tesla, Inc.",             exchange: "NASDAQ", sector: "Automotive",     base: 218.04 },
  { symbol: "MSFT", name: "Microsoft Corporation",   exchange: "NASDAQ", sector: "Technology",     base: 421.50 },
  { symbol: "GOOGL",name: "Alphabet Inc. Class A",   exchange: "NASDAQ", sector: "Technology",     base: 167.92 },
  { symbol: "AMZN", name: "Amazon.com, Inc.",        exchange: "NASDAQ", sector: "Consumer",       base: 184.30 },
  { symbol: "META", name: "Meta Platforms, Inc.",    exchange: "NASDAQ", sector: "Technology",     base: 502.18 },
  { symbol: "SPY",  name: "SPDR S&P 500 ETF Trust",  exchange: "NYSE",   sector: "",               base: 542.00 },
  { symbol: "JPM",  name: "JPMorgan Chase & Co.",    exchange: "NYSE",   sector: "Financials",     base: 198.74 },
  { symbol: "XOM",  name: "Exxon Mobil Corporation", exchange: "NYSE",   sector: "Energy",         base: 114.22 },
  { symbol: "BRK.B",name: "Berkshire Hathaway B",    exchange: "NYSE",   sector: "Financials",     base: 408.55 },
  { symbol: "JNJ",  name: "Johnson & Johnson",       exchange: "NYSE",   sector: "Health Care",    base: 152.10 },
];

// Tiny seedable PRNG so prices are stable across renders.
function mulberry32(seed) {
  return function () {
    let t = (seed += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function generatePrices(symbol, base, days = 90) {
  const seed = [...symbol].reduce((a, c) => a + c.charCodeAt(0), 0);
  const rnd = mulberry32(seed);
  const out = [];
  let price = base * 0.9;
  const end = new Date();
  end.setHours(0, 0, 0, 0);
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(end);
    d.setDate(end.getDate() - i);
    const drift = (base - price) * 0.04;
    const noise = (rnd() - 0.5) * base * 0.025;
    price = Math.max(1, price + drift + noise);
    const open  = price + (rnd() - 0.5) * base * 0.01;
    const high  = Math.max(open, price) + rnd() * base * 0.012;
    const low   = Math.min(open, price) - rnd() * base * 0.012;
    out.push({
      id: `${symbol}-${i}`,
      date: d.toISOString().slice(0, 10),
      open:  open.toFixed(2),
      high:  high.toFixed(2),
      low:   low.toFixed(2),
      close: price.toFixed(2),
      adj_close: price.toFixed(2),
      volume: Math.round(500000 + rnd() * 4_500_000),
    });
  }
  return out;
}

const STOCKS = SEED_STOCKS.map((s, i) => ({
  ...s,
  id: `stock-${i}`,
  created_at: new Date().toISOString(),
  _prices: generatePrices(s.symbol, s.base, 90),
}));

// Latest two closes -> delta for the table.
function deltaFor(stock) {
  const p = stock._prices;
  if (!p || p.length < 2) return { abs: 0, pct: 0, dir: "flat" };
  const last = parseFloat(p[p.length - 1].close);
  const prev = parseFloat(p[p.length - 2].close);
  const abs = last - prev;
  const pct = (abs / prev) * 100;
  return { last, abs, pct, dir: abs > 0.005 ? "up" : abs < -0.005 ? "down" : "flat" };
}

window.__SM_DATA = { STOCKS, SECTORS, deltaFor };
