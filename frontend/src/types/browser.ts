/**
 * Browser agent (browser-use). Kept in its own module rather than `types/llm.ts`:
 * /browse is a standalone page, not part of the Agents workspace.
 */

export type BrowserRunStatus = "running" | "done" | "error" | "stopped";
/** Which LLM drives the browser. Ollama is the default: free and local. */
export type BrowserProvider = "ollama" | "anthropic";
export type BrowserStopReason = "complete" | "budget" | "timeout" | "error" | "";

export interface BrowserStepState {
  id: string;
  order: number;
  /** browser-use action name, e.g. "go_to_url" / "click_element" / "extract_content". */
  action: string;
  action_args: Record<string, unknown> | null;
  url: string;
  title: string;
  /** The agent's own assessment of what the previous action achieved. */
  evaluation: string;
  memory: string;
  /** Relative key ("<run_id>/<order>.png"); "" when the step has no capture. */
  screenshot: string;
  /** The goal the agent set itself for this step. */
  output: string | null;
  status: "pending" | "running" | "done" | "error";
  error: string | null;
}

export interface BrowserRunSummary {
  id: string;
  query: string;
  provider: BrowserProvider | "";
  max_steps: number | null;
  status: BrowserRunStatus;
  stop_reason: BrowserStopReason;
  created_at: string;
  completed_at: string | null;
}

export interface BrowserRunDetail extends BrowserRunSummary {
  model: string;
  allowed_domains: string[];
  urls_visited: string[];
  duration_s: number | null;
  output: string;
  error: string;
  steps: BrowserStepState[];
}

export interface BrowserRunRequest {
  query: string;
  provider?: BrowserProvider | null;
  max_steps?: number | null;
}

/** The page is disabled server-side (browser_enabled = false). */
export class BrowserDisabledError extends Error {
  hint: string;

  constructor(message: string, hint: string) {
    super(message);
    this.name = "BrowserDisabledError";
    this.hint = hint;
  }
}

/** Another browser run holds the single slot. */
export class BrowserBusyError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "BrowserBusyError";
  }
}
