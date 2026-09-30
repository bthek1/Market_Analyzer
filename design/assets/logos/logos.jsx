/* global React */
// Six logo directions for Stock Market Analyser.
// Each is a pure SVG component sized by viewBox; callers control width.

// --- D1: Candle Ladder -------------------------------------------------------
// Three ascending OHLC candles. Financial-native, immediately readable.
function MarkCandleLadder({ size = 96, color = "#2563eb", up = "#16a34a", down = "#dc2626", inverse = false }) {
  const fg = inverse ? "#fff" : color;
  const u  = inverse ? "#34d399" : up;
  const d  = inverse ? "#f87171" : down;
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      {/* candle 1 */}
      <line x1="10" y1="38" x2="10" y2="54" stroke={d} strokeWidth="2"/>
      <rect x="6" y="42" width="8" height="10" rx="1.5" fill={d}/>
      {/* candle 2 */}
      <line x1="22" y1="22" x2="22" y2="50" stroke={u} strokeWidth="2"/>
      <rect x="18" y="28" width="8" height="18" rx="1.5" fill={u}/>
      {/* candle 3 */}
      <line x1="34" y1="14" x2="34" y2="42" stroke={u} strokeWidth="2"/>
      <rect x="30" y="18" width="8" height="20" rx="1.5" fill={u}/>
      {/* trend line connecting closes, brand color */}
      <path d="M10 42 L22 28 L34 18 L52 8" stroke={fg} strokeWidth="2.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
      <circle cx="52" cy="8" r="3" fill={fg}/>
    </svg>
  );
}

// --- D2: Arc Up --------------------------------------------------------------
// A clean upward parabola with a single dot anchor at apex.
function MarkArcUp({ size = 96, color = "#2563eb", inverse = false }) {
  const fg = inverse ? "#fff" : color;
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <path d="M8 52 Q 18 50 28 38 T 56 10" stroke={fg} strokeWidth="6" strokeLinecap="round" fill="none"/>
      <circle cx="56" cy="10" r="5" fill={fg}/>
      <circle cx="56" cy="10" r="2.2" fill={inverse ? "#0b1220" : "#fff"}/>
    </svg>
  );
}

// --- D3: SM Monogram ---------------------------------------------------------
// A blocky "S" set against a chart-tick "M" baseline.
function MarkMonogram({ size = 96, color = "#2563eb", inverse = false }) {
  const fg = inverse ? "#fff" : color;
  const sub = inverse ? "#94a3b8" : "#9ca3af";
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      {/* M baseline as tiny chart ticks */}
      <path d="M6 50 L18 38 L30 46 L42 30 L54 38 L58 34" stroke={sub} strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
      {/* Bold S */}
      <path d="M44 16 Q 28 16 28 24 Q 28 30 36 30 L42 30 Q 50 30 50 36 Q 50 44 34 44"
            stroke={fg} strokeWidth="6" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}

// --- D4: Pulse — rounded square card with a chart pulse -----------------
function MarkPulseTile({ size = 96, color = "#2563eb", inverse = false }) {
  const bg = inverse ? "#1d4ed8" : color;
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <rect width="64" height="64" rx="14" fill={bg}/>
      <path d="M10 40 L20 32 L26 36 L34 22 L42 28 L54 18"
            stroke="#fff" strokeWidth="3.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
      <circle cx="34" cy="22" r="3.2" fill="#fff"/>
    </svg>
  );
}

// --- D5: Aperture Lens -------------------------------------------------------
// A research / analyser glyph: a lens ring with a candle inside.
function MarkAperture({ size = 96, color = "#2563eb", inverse = false }) {
  const fg = inverse ? "#fff" : color;
  const accent = inverse ? "#34d399" : "#16a34a";
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <circle cx="28" cy="28" r="20" stroke={fg} strokeWidth="5" fill="none"/>
      {/* mini candle inside */}
      <line x1="28" y1="16" x2="28" y2="40" stroke={accent} strokeWidth="2"/>
      <rect x="24" y="22" width="8" height="14" rx="1.5" fill={accent}/>
      {/* handle */}
      <line x1="44" y1="44" x2="56" y2="56" stroke={fg} strokeWidth="6" strokeLinecap="round"/>
    </svg>
  );
}

// --- D6: Bracketed Pulse -----------------------------------------------------
// Code-like square brackets wrapping a chart line. Speaks "analyser" + dev DNA.
function MarkBrackets({ size = 96, color = "#2563eb", inverse = false }) {
  const fg = inverse ? "#fff" : color;
  const sub = inverse ? "#64748b" : "#9ca3af";
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      {/* left bracket */}
      <path d="M16 12 L8 12 L8 52 L16 52" stroke={sub} strokeWidth="4" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
      {/* right bracket */}
      <path d="M48 12 L56 12 L56 52 L48 52" stroke={sub} strokeWidth="4" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
      {/* line in the middle */}
      <path d="M14 42 L24 32 L32 36 L42 22 L50 26"
            stroke={fg} strokeWidth="4" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
      <circle cx="42" cy="22" r="3" fill={fg}/>
    </svg>
  );
}

const LOGOS = [
  {
    id: "candle-ladder",
    name: "01 · Candle Ladder",
    note: "Three OHLC candles + trend line. Reads instantly as 'stocks'.",
    Mark: MarkCandleLadder,
    tile: false,
  },
  {
    id: "arc-up",
    name: "02 · Arc Up",
    note: "Minimal upward parabola. Scales cleanly to favicon.",
    Mark: MarkArcUp,
    tile: false,
  },
  {
    id: "monogram",
    name: "03 · SM Monogram",
    note: "Blocky S over a faint chart baseline. Badge-friendly.",
    Mark: MarkMonogram,
    tile: false,
  },
  {
    id: "pulse-tile",
    name: "04 · Pulse Tile",
    note: "Filled rounded square — most app-icon-like of the set.",
    Mark: MarkPulseTile,
    tile: true,
  },
  {
    id: "aperture",
    name: "05 · Aperture",
    note: "Lens + candle. Leans into 'analyser' / research vibe.",
    Mark: MarkAperture,
    tile: false,
  },
  {
    id: "brackets",
    name: "06 · Bracketed Pulse",
    note: "[ chart ] — code-bracket frame nods to the engineering DNA.",
    Mark: MarkBrackets,
    tile: false,
  },
];

Object.assign(window, {
  LOGOS,
  MarkCandleLadder, MarkArcUp, MarkMonogram,
  MarkPulseTile, MarkAperture, MarkBrackets,
});
