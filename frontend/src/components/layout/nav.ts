import {
  Bot,
  Building2,
  MessagesSquare,
  GitBranch,
  Globe,
  LayoutDashboard,
  ListChecks,
  Map,
  Network,
  Server,
  type LucideIcon,
} from "lucide-react";

export interface NavLink {
  to:
    | "/"
    | "/companies"
    | "/market-map"
    | "/tasks"
    | "/redis"
    | "/agents"
    | "/chat"
    | "/browse"
    | "/knowledge"
    | "/code-graph";
  label: string;
  icon: LucideIcon;
}

export const NAV_LINKS: NavLink[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/companies", label: "Companies", icon: Building2 },
  { to: "/market-map", label: "Market Map", icon: Map },
  { to: "/tasks", label: "Tasks", icon: ListChecks },
  { to: "/redis", label: "Redis", icon: Server },
  { to: "/agents", label: "Agents", icon: Bot },
  // Siblings of Agents, not children: a conversation and a browser run are each their own
  // page, because /agents compares one-shot workflows over a single query side by side.
  { to: "/chat", label: "Chat", icon: MessagesSquare },
  { to: "/browse", label: "Browse", icon: Globe },
  { to: "/knowledge", label: "Knowledge", icon: Network },
  { to: "/code-graph", label: "Code Graph", icon: GitBranch },
];

/**
 * Whether `to` is the active nav entry for the current pathname. Sub-routes count as
 * active (so /companies/$id highlights "Companies"); "/" only matches exactly.
 */
export function isNavActive(to: NavLink["to"], pathname: string): boolean {
  if (to === "/") return pathname === "/";
  return pathname === to || pathname.startsWith(`${to}/`);
}
