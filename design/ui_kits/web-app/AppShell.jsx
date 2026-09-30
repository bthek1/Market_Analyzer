/* global React */
// AppShell.jsx — top nav mirroring frontend/src/components/layout/AppShell.tsx

function LogoMark({ size = 22 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <rect width="64" height="64" rx="14" fill="#2563eb" />
      <path
        d="M10 40 L20 32 L26 36 L34 22 L42 28 L54 18"
        stroke="#fff"
        strokeWidth="3.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <circle cx="34" cy="22" r="3.2" fill="#fff" />
    </svg>
  );
}

function NavLink({ active, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "text-sm transition-colors " +
        (active
          ? "text-gray-900 font-medium"
          : "text-gray-600 hover:text-gray-900")
      }
    >
      {children}
    </button>
  );
}

function AppShell({ route, onNavigate, userEmail, onLogout, children }) {
  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white border-b border-gray-200 px-6 py-4 flex justify-between items-center">
        <div className="flex items-center gap-6">
          <button
            type="button"
            onClick={() => onNavigate({ name: "dashboard" })}
            className="font-bold text-lg flex items-center gap-2 text-gray-900"
          >
            <LogoMark />
            Stock Market
          </button>
          <NavLink
            active={route.name === "stocks" || route.name === "stockDetail"}
            onClick={() => onNavigate({ name: "stocks" })}
          >
            Stocks
          </NavLink>
          <NavLink
            active={route.name === "watchlist"}
            onClick={() => onNavigate({ name: "watchlist" })}
          >
            Watchlist
          </NavLink>
        </div>
        <div className="flex items-center gap-4">
          {userEmail && (
            <span className="text-sm text-gray-600">{userEmail}</span>
          )}
          <button
            type="button"
            onClick={onLogout}
            className="text-sm text-red-600 hover:underline"
          >
            Logout
          </button>
        </div>
      </nav>
      <main className="p-8">{children}</main>
    </div>
  );
}

Object.assign(window, { AppShell, LogoMark, NavLink });
