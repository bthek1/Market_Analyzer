import { Link } from "@tanstack/react-router";
import { cn } from "@/lib/utils";

const OPTIONS = [
  { to: "/agents", label: "Workflows" },
  { to: "/chat", label: "Chat" },
] as const;

export type Workspace = (typeof OPTIONS)[number]["to"];

/**
 * Switches between the two LLM workspaces: `/agents` (compare one-shot workflows over one
 * query) and `/chat` (one continuous conversation).
 *
 * Links, not a mode. Chat was a mode on /agents until issue #8 and the pages have genuinely
 * different shapes - a session sidebar against a workflow grid, a transcript against run
 * panels - so they are separate routes. This is the affordance that keeps them one step
 * apart anyway.
 *
 * Deliberately never disabled while something is running: a run keeps going server-side
 * (`stream_in_background` drives it on a daemon thread) and both pages reconnect to an
 * unfinished one on arrival, so navigating away costs nothing.
 *
 * `active` is passed in rather than read from the router: each page knows which one it is,
 * and it keeps this testable without mounting a router.
 */
export function WorkspaceSwitch({ active }: { active: Workspace }) {
  return (
    <nav aria-label="Workspace" className="flex w-fit overflow-hidden rounded-md border">
      {OPTIONS.map(({ to, label }, i) => (
        <Link
          key={to}
          to={to}
          aria-current={to === active ? "page" : undefined}
          className={cn(
            "px-3 py-1 text-sm font-medium transition-colors",
            to === active
              ? "bg-primary text-primary-foreground"
              : "bg-background text-muted-foreground hover:bg-muted hover:text-foreground",
            i < OPTIONS.length - 1 && "border-r",
          )}
        >
          {label}
        </Link>
      ))}
    </nav>
  );
}
