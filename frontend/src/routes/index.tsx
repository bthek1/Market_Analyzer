import { createFileRoute, Link } from "@tanstack/react-router";
import { useMe } from "@/hooks/useAuth";
import { useCompanySearch, useSectors } from "@/hooks/useCompanies";
import { AppShell } from "@/components/layout/AppShell";
import { buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  CardDescription,
} from "@/components/ui/card";

export const Route = createFileRoute("/")({
  component: Dashboard,
});

function StatCard({
  label,
  value,
  sub,
  linkTo,
  linkLabel,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  linkTo: string;
  linkLabel: string;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-xs uppercase tracking-wide text-muted-foreground font-medium">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <div className="text-3xl font-bold font-mono tabular-nums">{value}</div>
        {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
        <Link
          to={linkTo}
          className={buttonVariants({ variant: "link", size: "sm", className: "px-0 h-auto self-start" })}
        >
          {linkLabel} →
        </Link>
      </CardContent>
    </Card>
  );
}

function QuickNavCard({
  title,
  description,
  to,
  label,
}: {
  title: string;
  description: string;
  to: string;
  label: string;
}) {
  return (
    <Card className="hover:bg-accent/40 transition-colors">
      <CardHeader className="pb-1">
        <CardTitle className="text-sm font-semibold">{title}</CardTitle>
        <CardDescription className="text-xs">{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <Link
          to={to}
          className={buttonVariants({ variant: "outline", size: "sm" })}
        >
          {label}
        </Link>
      </CardContent>
    </Card>
  );
}

function BootstrapProgress({ total, bootstrapped }: { total: number; bootstrapped: number }) {
  const pct = total > 0 ? Math.round((bootstrapped / total) * 100) : 0;
  return (
    <div className="flex flex-col gap-1">
      <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
        <div
          className="h-full rounded-full bg-primary transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-muted-foreground">
        {bootstrapped.toLocaleString()} of {total.toLocaleString()} bootstrapped ({pct}%)
      </span>
    </div>
  );
}

function Dashboard() {
  const { data: user } = useMe();
  const { data: allCompanies } = useCompanySearch({ page_size: 1 });
  const { data: bootstrappedCompanies } = useCompanySearch({ is_bootstrapped: true, page_size: 1 });
  const { data: sectors } = useSectors();

  const totalCount = allCompanies?.count ?? 0;
  const bootstrappedCount = bootstrappedCompanies?.count ?? 0;
  const sectorCount = sectors?.count ?? 0;

  return (
    <AppShell>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Welcome back{user ? `, ${user.email}` : ""}
        </p>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <Card className="col-span-2 lg:col-span-1">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs uppercase tracking-wide text-muted-foreground font-medium">
              Companies Tracked
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="text-3xl font-bold font-mono tabular-nums">
              {totalCount > 0 ? totalCount.toLocaleString() : "—"}
            </div>
            {totalCount > 0 && (
              <BootstrapProgress total={totalCount} bootstrapped={bootstrappedCount} />
            )}
            <Link
              to="/companies"
              className={buttonVariants({ variant: "link", size: "sm", className: "px-0 h-auto self-start" })}
            >
              Browse companies →
            </Link>
          </CardContent>
        </Card>

        <StatCard
          label="Sectors"
          value={sectorCount > 0 ? sectorCount : "—"}
          sub={sectorCount > 0 ? "GICS tier-1 classifications" : undefined}
          linkTo="/market-map"
          linkLabel="View market map"
        />

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs uppercase tracking-wide text-muted-foreground font-medium">
              Market Map
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <p className="text-xs text-muted-foreground leading-relaxed">
              Visualise market capitalisation across sectors and industries as an interactive treemap.
            </p>
            <Link
              to="/market-map"
              className={buttonVariants({ variant: "link", size: "sm", className: "px-0 h-auto self-start" })}
            >
              Open market map →
            </Link>
          </CardContent>
        </Card>
      </div>

      {/* Quick nav */}
      <div className="mb-3">
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
          Quick Access
        </h2>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        <QuickNavCard
          title="Company Search"
          description="Filter and sort by sector, exchange, bootstrap status. Click a row to dive into fundamentals, charts, and data."
          to="/companies"
          label="Browse companies"
        />
        <QuickNavCard
          title="Market Map"
          description="Interactive treemap of market capitalisation. Spot concentration and relative size at a glance."
          to="/market-map"
          label="Open map"
        />
        <QuickNavCard
          title="Task Monitor"
          description="Track Celery periodic tasks and recent task results — bootstrap progress, sync schedules, and failures."
          to="/tasks"
          label="View tasks"
        />
        <QuickNavCard
          title="Redis Monitor"
          description="Inspect Redis key counts, memory usage, and browse individual keys. Useful for debugging sync queues."
          to="/redis"
          label="Open Redis"
        />
      </div>
    </AppShell>
  );
}
