/* global React, ReactDOM */
// App.jsx — top-level state machine + dashboard.

const { useState } = React;

function Dashboard({ userEmail, onGoStocks, onGoWatchlist, watchlistCount }) {
  const stocks = window.__SM_DATA.STOCKS;
  const { deltaFor } = window.__SM_DATA;
  const gainers = [...stocks].sort((a, b) => deltaFor(b).pct - deltaFor(a).pct).slice(0, 3);
  const losers  = [...stocks].sort((a, b) => deltaFor(a).pct - deltaFor(b).pct).slice(0, 3);

  return (
    <div>
      <h2 className="text-xl font-semibold mb-1 text-gray-900">Dashboard</h2>
      <p className="text-gray-600 mb-6">Welcome, {userEmail}.</p>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="text-xs uppercase tracking-wide text-gray-500 font-medium">
            On your watchlist
          </div>
          <div className="mt-1 text-2xl font-bold font-mono tabular-nums text-gray-900">
            {watchlistCount}
          </div>
          <button
            type="button"
            onClick={onGoWatchlist}
            className="text-sm text-blue-600 hover:underline mt-2"
          >
            View watchlist
          </button>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="text-xs uppercase tracking-wide text-gray-500 font-medium">
            Tracked symbols
          </div>
          <div className="mt-1 text-2xl font-bold font-mono tabular-nums text-gray-900">
            {stocks.length}
          </div>
          <button
            type="button"
            onClick={onGoStocks}
            className="text-sm text-blue-600 hover:underline mt-2"
          >
            Browse stocks
          </button>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="text-xs uppercase tracking-wide text-gray-500 font-medium">
            Data freshness
          </div>
          <div className="mt-1 text-2xl font-bold text-gray-900">
            Just now
          </div>
          <div className="text-xs text-gray-500 mt-2">
            Prototype data — no live feed.
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <MoverPanel title="Top gainers" stocks={gainers} dir="up" onPick={(s) => window.__appNav?.(s)} />
        <MoverPanel title="Top losers"  stocks={losers}  dir="down" onPick={(s) => window.__appNav?.(s)} />
      </div>
    </div>
  );
}

function MoverPanel({ title, stocks, dir, onPick }) {
  const { deltaFor } = window.__SM_DATA;
  const color = dir === "up" ? "text-green-600" : "text-red-600";
  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
        <h3 className="font-medium text-gray-900">{title}</h3>
        <span className="text-xs text-gray-500">last 1d</span>
      </div>
      <ul>
        {stocks.map((s) => {
          const d = deltaFor(s);
          const sign = d.pct > 0 ? "+" : "";
          return (
            <li
              key={s.id}
              className="px-4 py-2 flex items-center justify-between hover:bg-gray-50 cursor-pointer border-b last:border-b-0 border-gray-200"
              onClick={() => onPick(s)}
            >
              <div>
                <span className="font-mono font-semibold text-blue-600">{s.symbol}</span>
                <span className="ml-3 text-sm text-gray-600">{s.name}</span>
              </div>
              <div className="text-right">
                <div className="font-mono tabular-nums text-sm text-gray-900">
                  ${d.last.toFixed(2)}
                </div>
                <div className={`font-mono tabular-nums text-xs ${color}`}>
                  {sign}{d.pct.toFixed(2)}%
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function App() {
  const [user, setUser] = useState(null);
  const [authView, setAuthView] = useState("login");
  const [route, setRoute] = useState({ name: "dashboard" });
  const [watchlist, setWatchlist] = useState([]);

  // Expose a quick pick handler for the dashboard movers.
  window.__appNav = (stock) => setRoute({ name: "stockDetail", stock });

  const navigate = (r) => setRoute(r);
  const logout = () => {
    setUser(null);
    setRoute({ name: "dashboard" });
    setWatchlist([]);
    setAuthView("login");
  };

  const addToWatchlist = (stock) => {
    setWatchlist((wl) =>
      wl.some((w) => w.stock.id === stock.id)
        ? wl
        : [
            ...wl,
            {
              id: "w-" + stock.id + "-" + Date.now(),
              stock,
              added_at: new Date().toISOString(),
            },
          ]
    );
  };
  const removeFromWatchlist = (itemId) => {
    setWatchlist((wl) => wl.filter((w) => w.id !== itemId));
  };

  if (!user) {
    return authView === "login" ? (
      <LoginPage
        onLogin={(u) => setUser(u)}
        onGoRegister={() => setAuthView("register")}
      />
    ) : (
      <RegisterPage
        onRegister={(u) => setUser(u)}
        onGoLogin={() => setAuthView("login")}
      />
    );
  }

  let body;
  if (route.name === "dashboard") {
    body = (
      <Dashboard
        userEmail={user.email}
        watchlistCount={watchlist.length}
        onGoStocks={() => navigate({ name: "stocks" })}
        onGoWatchlist={() => navigate({ name: "watchlist" })}
      />
    );
  } else if (route.name === "stocks") {
    body = <StocksPage onPick={(s) => navigate({ name: "stockDetail", stock: s })} />;
  } else if (route.name === "stockDetail") {
    body = (
      <StockDetailPage
        stock={route.stock}
        watchlist={watchlist}
        onAdd={addToWatchlist}
        onRemove={removeFromWatchlist}
      />
    );
  } else if (route.name === "watchlist") {
    body = (
      <WatchlistPage
        watchlist={watchlist}
        onRemove={removeFromWatchlist}
        onPick={(s) => navigate({ name: "stockDetail", stock: s })}
        onGoStocks={() => navigate({ name: "stocks" })}
      />
    );
  }

  return (
    <AppShell
      route={route}
      onNavigate={navigate}
      userEmail={user.email}
      onLogout={logout}
    >
      {body}
    </AppShell>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
