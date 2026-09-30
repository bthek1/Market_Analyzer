import { Link, useRouterState } from "@tanstack/react-router";
import { PanelLeftClose, PanelLeftOpen, X } from "lucide-react";
import { LogoMark } from "@/components/layout/LogoMark";
import { NAV_LINKS, isNavActive } from "@/components/layout/nav";
import { cn } from "@/lib/utils";

interface SidebarProps {
  /** Icon-rail mode. Applies from `md` up; the mobile drawer is always full width. */
  collapsed: boolean;
  onToggle: () => void;
  /** Drawer visibility below `md`. */
  mobileOpen?: boolean;
  onMobileClose?: () => void;
}

export function Sidebar({
  collapsed,
  onToggle,
  mobileOpen = false,
  onMobileClose,
}: SidebarProps) {
  const { location } = useRouterState();

  return (
    <>
      {mobileOpen && (
        <div
          data-testid="sidebar-backdrop"
          aria-hidden="true"
          onClick={onMobileClose}
          className="fixed inset-0 z-40 bg-black/50 md:hidden"
        />
      )}
      <aside
        className={cn(
          "z-50 w-60 shrink-0 flex-col border-r bg-background transition-[width] duration-200",
          "fixed inset-y-0 left-0 md:sticky md:top-0 md:h-screen",
          mobileOpen ? "flex" : "hidden md:flex",
          collapsed ? "md:w-14" : "md:w-60"
        )}
      >
        <div
          className={cn(
            "flex h-14 shrink-0 items-center border-b",
            collapsed ? "md:justify-center md:px-0" : "px-3"
          )}
        >
          <Link
            to="/"
            onClick={onMobileClose}
            className="flex min-w-0 items-center gap-2 text-sm font-semibold tracking-tight"
          >
            <LogoMark size={22} />
            <span className={cn("truncate", collapsed && "md:sr-only")}>
              Stock Market
            </span>
          </Link>
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={!collapsed}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className={cn(
              "ml-auto hidden size-7 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground md:inline-flex",
              collapsed && "md:hidden"
            )}
          >
            {collapsed ? (
              <PanelLeftOpen className="size-4" />
            ) : (
              <PanelLeftClose className="size-4" />
            )}
          </button>
          <button
            type="button"
            onClick={onMobileClose}
            aria-label="Close navigation"
            className="ml-auto inline-flex size-7 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground md:hidden"
          >
            <X className="size-4" />
          </button>
        </div>

        {collapsed && (
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={false}
            aria-label="Expand sidebar"
            title="Expand sidebar"
            className="mx-auto mt-2 hidden size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground md:inline-flex"
          >
            <PanelLeftOpen className="size-4" />
          </button>
        )}

        <nav aria-label="Main" className="flex-1 space-y-1 overflow-y-auto p-2">
          {NAV_LINKS.map(({ to, label, icon: Icon }) => {
            const active = isNavActive(to, location.pathname);
            return (
              <Link
                key={to}
                to={to}
                onClick={onMobileClose}
                title={label}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex h-9 items-center gap-3 rounded-lg px-2.5 text-sm font-medium transition-colors hover:bg-muted hover:text-foreground",
                  collapsed && "md:justify-center md:px-0",
                  active ? "bg-muted text-foreground" : "text-muted-foreground"
                )}
              >
                <Icon className="size-4 shrink-0" />
                <span className={cn("truncate", collapsed && "md:sr-only")}>
                  {label}
                </span>
              </Link>
            );
          })}
        </nav>
      </aside>
    </>
  );
}
