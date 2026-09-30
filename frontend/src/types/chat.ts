/**
 * Chat agent types (issue #8).
 *
 * The shapes mirror the backend serializers exactly, because `_events.step_event` makes the
 * SSE step payload the serializer's own output - so a live stream and a `loadFromDetail`
 * restore produce identical state. Seven of ten workflows diverged on that before issue #6
 * and it cost a silent data loss on refresh; do not let these drift.
 */

export type RunStatus = "running" | "done" | "error" | "stopped";
export type StepStatus = "pending" | "running" | "done" | "error";

/** One tool call inside a turn. Mirrors `ChatStepSerializer`. */
export interface ChatStepState {
  id: string;
  order: number;
  thought: string;
  tool: string;
  tool_args: Record<string, unknown> | null;
  observation: string;
  is_answer: boolean;
  status: StepStatus;
  error: string;
  created_at: string;
}

/** One turn. `query` is the user message, `output` the assistant reply. */
export interface ChatTurn {
  id: string;
  query: string;
  model: string;
  max_steps: number | null;
  turn: number;
  tools_used: string[] | null;
  compacted: number;
  status: RunStatus;
  output: string;
  error: string;
  created_at: string;
  completed_at: string | null;
  steps: ChatStepState[];
}

/** A row in the conversation sidebar. */
export interface ChatSessionSummary {
  id: string;
  title: string;
  archived: boolean;
  turn_count: number;
  last_message_at: string | null;
  created_at: string;
  updated_at: string;
}

/** One conversation with its transcript, oldest turn first. */
export interface ChatSessionDetail extends ChatSessionSummary {
  summary: string;
  summarised_upto: number;
  turns: ChatTurn[];
}

export interface ChatTurnRequest {
  message: string;
  session?: string | null;
  model?: string | null;
  max_steps?: number | null;
}

export interface ChatStartedEvent {
  event: "started";
  run_id: string;
  session_id: string | null;
  max_steps: number;
  tools: string[];
  /** Turns replayed into the prompt verbatim. */
  history: number;
  /** Turns folded into the session summary by THIS turn. */
  compacted: number;
}

// The step payload IS the row's detail representation, so only `event` is extra.
export type ChatStepEvent = { event: "step" } & ChatStepState;

/**
 * One incremental slice of the reply being written. Corresponds to no persisted row: the
 * finished text lands on the turn's `output` like any other, and the concatenation of these
 * must equal it exactly - otherwise a reload changes a reply the user already read.
 */
export interface ChatDeltaEvent {
  event: "delta";
  text: string;
}

export interface ChatResultEvent {
  event: "result";
  output: string;
  run_id: string;
}

export interface ChatErrorEvent {
  event: "error";
  error: string;
}

export interface ChatStoppedEvent {
  event: "stopped";
}

export type ChatEvent =
  | ChatStartedEvent
  | ChatStepEvent
  | ChatDeltaEvent
  | ChatResultEvent
  | ChatErrorEvent
  | ChatStoppedEvent;

/** A turn is already in flight in this conversation - two would fork the transcript. */
export class ChatBusyError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ChatBusyError";
  }
}
