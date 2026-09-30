/* global React, Recharts */
// StockDetail.jsx — symbol header + watchlist toggle + Recharts price line.

const { useMemo } = React;

function WatchlistButton({ stock, watchlist, onAdd, onRemove }) {
  const item = watchlist.find((w) => w.stock.id === stock.id);
  const isWatched = !!item;
  const handleClick = () => {
    if (isWatched) onRemove(item.id);
    else onAdd(stock);
  };
  return (
    <button
      type="button"
      onClick={handleClick}
      className={
        "px-4 py-2 rounded text-sm font-medium transition-colors " +
        (isWatched
          ? "bg-red-50 text-red-600 border border-red-200 hover:bg-red-100"
          : "bg-blue-600 text-white hover:bg-blue-700")
      }
    >
      {isWatched ? "Remove from watchlist" : "Add to watchlist"}
    </button>
  );
}

function PriceChart({ prices }) {
  const {
    LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  } = Recharts;

  const data = useMemo(
    () =>
      [...prices]
        .sort((a, b) => a.date.localeCompare(b.date))
        .map((p) => ({ date: p.date, close: parseFloat(p.close) })),
    [prices]
  );

  if (data.length === 0) {
    return <p className="text-gray-500 text-sm">No price data available.</p>;
  }

  return (
    <ResponsiveContainer width="100%" height={300}>
      <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis
          dataKey="date"
          tick={{ fontSize: 12, fill: "#6b7280" }}
          tickFormatter={(d) => d.slice(5)}
          interval={Math.max(0, Math.floor(data.length / 8))}
          stroke="#e5e7eb"
        />
        <YAxis
          domain={["auto", "auto"]}
          tick={{ fontSize: 12, fill: "#6b7280" }}
          tickFormatter={(v) => `$${v.toFixed(0)}`}
          stroke="#e5e7eb"
          width={60}
        />
        <Tooltip
          contentStyle={{
            background: "#fff",
            border: "1px solid #e5e7eb",
            borderRadius: 4,
            fontSize: 12,
            fontFamily: "ui-sans-serif, system-ui",
          }}
          formatter={(v) => [`$${Number(v).toFixed(2)}`, "Close"]}
        />
        <Line type="monotone" dataKey="close" stroke="#2563eb" dot={false} strokeWidth={2} />
      </LineChart>
    </ResponsiveContainer>
  );
}

function StockDetailPage({ stock, watchlist, onAdd, onRemove }) {
  const { deltaFor } = window.__SM_DATA;
  const d = deltaFor(stock);
  const sign = d.pct > 0 ? "+" : "";
  const deltaColor =
    d.dir === "up" ? "text-green-600" : d.dir === "down" ? "text-red-600" : "text-gray-500";

  return (
    <div>
      <div className="flex justify-between items-start mb-6">
        <div>
          <h2 className="text-2xl font-bold font-mono text-gray-900">{stock.symbol}</h2>
          <p className="text-gray-600">{stock.name}</p>
          {(stock.exchange || stock.sector) && (
            <p className="text-sm text-gray-400">
              {[stock.exchange, stock.sector].filter(Boolean).join(" · ")}
            </p>
          )}
        </div>
        <WatchlistButton
          stock={stock}
          watchlist={watchlist}
          onAdd={onAdd}
          onRemove={onRemove}
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <Stat label="Last" value={`$${d.last.toFixed(2)}`} />
        <Stat
          label="Change (1d)"
          value={
            <span className={`${deltaColor} font-mono tabular-nums`}>
              {sign}{d.abs.toFixed(2)} ({sign}{d.pct.toFixed(2)}%)
            </span>
          }
        />
        <Stat label="Open" value={`$${parseFloat(stock._prices.at(-1).open).toFixed(2)}`} />
        <Stat
          label="Volume"
          value={(stock._prices.at(-1).volume / 1_000_000).toFixed(2) + "M"}
        />
      </div>

      <div className="bg-white rounded-lg border border-gray-200 p-4">
        <h3 className="font-medium mb-4 text-gray-900">Price History</h3>
        <PriceChart prices={stock._prices} />
      </div>
    </div>
  );
}

function Stat({ label, value }) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4">
      <div className="text-xs uppercase tracking-wide text-gray-500 font-medium">{label}</div>
      <div className="mt-1 text-lg font-semibold font-mono tabular-nums text-gray-900">
        {value}
      </div>
    </div>
  );
}

Object.assign(window, { StockDetailPage, WatchlistButton, PriceChart, Stat });
