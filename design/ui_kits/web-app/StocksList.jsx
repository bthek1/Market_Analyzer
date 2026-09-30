/* global React */
// StocksList.jsx — search bar + stocks table.
// Mirrors frontend/src/routes/stocks.tsx + components/stocks/StockSearchBar + StockTable.

const { useState, useMemo } = React;

function StockSearchBar({ onSearch }) {
  const [value, setValue] = useState("");
  const submit = (e) => {
    e.preventDefault();
    onSearch(value.trim());
  };
  return (
    <form onSubmit={submit} className="flex gap-2 mb-6">
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Search by symbol or name (e.g. AAPL)"
        className="flex-1 border border-gray-200 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-blue-600"
      />
      <button
        type="submit"
        className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700"
      >
        Search
      </button>
    </form>
  );
}

function DeltaCell({ delta }) {
  if (!delta || delta.dir === "flat") {
    return <span className="text-gray-500 font-mono tabular-nums">0.00%</span>;
  }
  const sign = delta.pct > 0 ? "+" : "";
  const color = delta.dir === "up" ? "text-green-600" : "text-red-600";
  return (
    <span className={`${color} font-mono tabular-nums`}>
      {sign}{delta.pct.toFixed(2)}%
    </span>
  );
}

function StockTable({ stocks, onPick }) {
  if (stocks.length === 0) {
    return <p className="text-gray-500 text-sm">No stocks found.</p>;
  }
  const { deltaFor } = window.__SM_DATA;
  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="border-b border-gray-200 bg-gray-50">
            <th className="text-left py-2 px-3 font-medium">Symbol</th>
            <th className="text-left py-2 px-3 font-medium">Name</th>
            <th className="text-left py-2 px-3 font-medium">Exchange</th>
            <th className="text-left py-2 px-3 font-medium">Sector</th>
            <th className="text-right py-2 px-3 font-medium">Last</th>
            <th className="text-right py-2 px-3 font-medium">Δ 1d</th>
          </tr>
        </thead>
        <tbody>
          {stocks.map((stock) => {
            const d = deltaFor(stock);
            return (
              <tr
                key={stock.id}
                className="border-b last:border-b-0 border-gray-200 hover:bg-gray-50 cursor-pointer"
                onClick={() => onPick(stock)}
              >
                <td className="py-2 px-3">
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); onPick(stock); }}
                    className="text-blue-600 hover:underline font-medium font-mono"
                  >
                    {stock.symbol}
                  </button>
                </td>
                <td className="py-2 px-3 text-gray-900">{stock.name}</td>
                <td className="py-2 px-3 text-gray-500">{stock.exchange || "—"}</td>
                <td className="py-2 px-3 text-gray-500">{stock.sector || "—"}</td>
                <td className="py-2 px-3 text-right font-mono tabular-nums text-gray-900">
                  ${d.last.toFixed(2)}
                </td>
                <td className="py-2 px-3 text-right">
                  <DeltaCell delta={d} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function StocksPage({ onPick }) {
  const [query, setQuery] = useState("");
  const stocks = window.__SM_DATA.STOCKS;
  const filtered = useMemo(() => {
    if (!query) return stocks;
    const q = query.toLowerCase();
    return stocks.filter(
      (s) =>
        s.symbol.toLowerCase().includes(q) ||
        s.name.toLowerCase().includes(q)
    );
  }, [query, stocks]);

  return (
    <div>
      <h2 className="text-xl font-semibold mb-4 text-gray-900">Stocks</h2>
      <StockSearchBar onSearch={setQuery} />
      <StockTable stocks={filtered} onPick={onPick} />
    </div>
  );
}

Object.assign(window, { StocksPage, StockTable, StockSearchBar, DeltaCell });
