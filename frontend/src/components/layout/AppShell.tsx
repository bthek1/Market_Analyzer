import { useEffect, useState } from "react";
import { Menu } from "lucide-react";
import { useMe, useLogout } from "@/hooks/useAuth";
import { Button, buttonVariants } from "@/components/ui/button";
import { Sidebar } from "@/components/layout/Sidebar";
import { StatusBar } from "@/components/layout/StatusOverlay";
import { useUIStore } from "@/store/ui";
import { cn, formatDateTime } from "@/lib/utils";

interface AppShellProps {
  children: React.ReactNode;
}

export { LogoMark } from "@/components/layout/LogoMark";

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <span className="text-xs tabular-nums text-muted-foreground">
      {formatDateTime(now)}
    </span>
  );
}

export function AppShell({ children }: AppShellProps) {
  const { data: user } = useMe();
  const logout = useLogout();
  const collapsed = useUIStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  // Sidebar links close the drawer themselves via onMobileClose.
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <div className="flex min-h-0 flex-1">
        <Sidebar
          collapsed={collapsed}
          onToggle={toggleSidebar}
          mobileOpen={mobileOpen}
          onMobileClose={() => setMobileOpen(false)}
        />
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-30 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
            <div className="flex h-14 items-center gap-3 px-6">
              <button
                type="button"
                onClick={() => setMobileOpen(true)}
                aria-label="Open navigation"
                className="-ml-2 inline-flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground md:hidden"
              >
                <Menu className="size-4" />
              </button>
              <div className="ml-auto flex items-center gap-3">
                <Clock />
                {user && (
                  <span className="text-xs text-muted-foreground">{user.email}</span>
                )}
                <a
                  href={`${import.meta.env.VITE_API_BASE_URL}/admin/`}
                  target="_blank"
                  rel="noreferrer"
                  className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
                >
                  Admin
                </a>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => logout.mutate()}
                  disabled={logout.isPending}
                >
                  Logout
                </Button>
              </div>
            </div>
          </header>
          <main className="mx-auto w-full max-w-7xl flex-1 px-6 py-8">{children}</main>
        </div>
      </div>
      <StatusBar />
    </div>
  );
}
