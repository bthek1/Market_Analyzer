import type { ComparableAgentType } from "@/types/llm";

// Persists the Agents workspace across page reloads so a refresh does not lose
// the running workflows: we remember which workflows were selected, the active
// query, and the in-flight run id per workflow type. On the
// next load the page reconnects to any still-running runs by polling their
// persisted detail (the backend keeps executing them after the client drops).

const KEY = "agents.session.v1";

const KNOWN_TYPES: ComparableAgentType[] = [
  "single",
  "chain",
  "route",
  "parallel",
  "react",
  "evaluate",
  "plan",
  "orchestrate",
  "multiagent",
  "dag",
  "autonomous",
];

export interface AgentsSession {
  selectedTypes: ComparableAgentType[];
  query: string;
  // Workflow type -> persisted run id for the most recent run in that panel.
  runs: Partial<Record<ComparableAgentType, string>>;
}

export function loadAgentsSession(): AgentsSession | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<AgentsSession>;
    if (!parsed || !Array.isArray(parsed.selectedTypes)) return null;

    const selectedTypes = parsed.selectedTypes.filter(
      (t): t is ComparableAgentType =>
        KNOWN_TYPES.includes(t as ComparableAgentType),
    );
    if (selectedTypes.length === 0) return null;

    const runs: Partial<Record<ComparableAgentType, string>> = {};
    for (const [type, id] of Object.entries(parsed.runs ?? {})) {
      if (
        KNOWN_TYPES.includes(type as ComparableAgentType) &&
        typeof id === "string"
      ) {
        runs[type as ComparableAgentType] = id;
      }
    }

    // A `mode` field written before chat moved to its own page (issue #8) is simply not
    // read: the shape is parsed field by field, so a stale key cannot wedge the page.
    return {
      selectedTypes,
      query: typeof parsed.query === "string" ? parsed.query : "",
      runs,
    };
  } catch {
    return null;
  }
}

export function saveAgentsSession(session: AgentsSession): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(session));
  } catch {
    // Storage unavailable or over quota — non-fatal.
  }
}

export function clearAgentsSession(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    // Non-fatal.
  }
}
