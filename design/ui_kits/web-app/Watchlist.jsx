/* global React */
// Watchlist.jsx — table with remove links + empty state.
// Mirrors frontend/src/routes/watchlist.tsx.

function WatchlistPage({ watchlist, onRemove, onPick, onGoStocks }) {
  if (watchlist.length === 0) {
    return (
      <div>
        <h2 className="text-xl font-semibold mb-4 text-gray-900">Watchlist</h2>
        <p className="text-gray-500 text-sm">
          Your watchlist is empty.{" "}
          <button
            type="button"
            onClick={onGoStocks}
            className="text-blue-600 hover:underline"
          >
            Browse stocks
          </button>
        </p>
      </div>
    );
  }

  const { deltaFor } = window.__SM_DATA;

  return (
    <div>
      <h2 className="text-xl font-semibold mb-4 text-gray-900">Watchlist</h2>
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-gray-200 bg-gray-50">
              <th className="text-left py-2 px-3 font-medium">Symbol</th>
              <th className="text-left py-2 px-3 font-medium">Name</th>
              <th className="text-right py-2 px-3 font-medium">Last</th>
              <th className="text-right py-2 px-3 font-medium">Δ 1d</th>
              <th className="text-left py-2 px-3 font-medium">Added</th>
              <th className="py-2 px-3" />
            </tr>
          </thead>
          <tbody>
            {watchlist.map((item) => {
              const d = deltaFor(item.stock);
              const sign = d.pct > 0 ? "+" : "";
              const dColor = d.dir === "up" ? "text-green-600" : d.dir === "down" ? "text-red-600" : "text-gray-500";
              return (
                <tr key={item.id} className="border-b last:border-b-0 border-gray-200 hover:bg-gray-50">
                  <td className="py-2 px-3">
                    <button
                      type="button"
                      onClick={() => onPick(item.stock)}
                      className="text-blue-600 hover:underline font-medium font-mono"
                    >
                      {item.stock.symbol}
                    </button>
                  </td>
                  <td className="py-2 px-3 text-gray-900">{item.stock.name}</td>
                  <td className="py-2 px-3 text-right font-mono tabular-nums text-gray-900">
                    ${d.last.toFixed(2)}
                  </td>
                  <td className={`py-2 px-3 text-right font-mono tabular-nums ${dColor}`}>
                    {sign}{d.pct.toFixed(2)}%
                  </td>
                  <td className="py-2 px-3 text-gray-500">
                    {new Date(item.added_at).toLocaleDateString()}
                  </td>
                  <td className="py-2 px-3 text-right">
                    <button
                      type="button"
                      onClick={() => onRemove(item.id)}
                      className="text-red-500 hover:text-red-700 text-xs"
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

Object.assign(window, { WatchlistPage });
