import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  fetchBrowserRunDetail,
  readSSE,
  stopBrowserRun,
  streamBrowser,
} from "@/api/browser";
import { queryKeys } from "@/api/queryKeys";
import type {
  BrowserProvider,
  BrowserRunDetail,
  BrowserStepState,
  BrowserStopReason,
} from "@/types/browser";
import { BrowserBusyError, BrowserDisabledError } from "@/types/browser";

const SESSION_KEY = "browseSession";
const POLL_MS = 2000;

interface StartedEvent {
  event: "started";
  max_steps: number;
  provider: BrowserProvider;
  allowed_domains: string[];
  timeout_s: number;
}

// The step payload IS the row's detail representation (backend `_events.step_event`),
// so the live stream and a refresh-restore produce identical state. Only the `event`
// discriminator is extra.
type StepEvent = { event: "step" } & BrowserStepState;

interface ResultEvent {
  event: "result";
  output: string;
  sources: string[];
  stop_reason: BrowserStopReason;
  steps: number;
  run_id: string;
}

interface ErrorEvent {
  event: "error";
  error: string;
}

interface StoppedEvent {
  event: "stopped";
}

type BrowserEvent =
  | StartedEvent
  | StepEvent
  | ResultEvent
  | ErrorEvent
  | StoppedEvent;

export interface UseBrowserAgentReturn {
  steps: BrowserStepState[];
  maxSteps: number | null;
  output: string | null;
  sources: string[];
  stopReason: BrowserStopReason;
  isRunning: boolean;
  error: string | null;
  /** Set when the server has the feature switched off - the page shows an empty state. */
  disabled: { detail: string; hint: string } | null;
  runId: string | null;
  query: string;
  setQuery: (value: string) => void;
  run: (
    query: string,
    opts?: { provider?: BrowserProvider; maxSteps?: number },
  ) => void;
  stop: () => void;
  reset: () => void;
  loadFromDetail: (detail: BrowserRunDetail) => void;
}

function stepFromEvent({ event: _event, ...step }: StepEvent): BrowserStepState {
  return step;
}

interface StoredSession {
  query?: string;
  runId?: string | null;
}

function readSession(): StoredSession {
  try {
    return JSON.parse(localStorage.getItem(SESSION_KEY) ?? "{}") as StoredSession;
  } catch {
    return {};
  }
}

function writeSession(session: StoredSession) {
  try {
    localStorage.setItem(SESSION_KEY, JSON.stringify(session));
  } catch {
    // storage unavailable (private mode / quota) - the page still works
  }
}

/**
 * Drives one browser run: streams its steps, persists the workspace to localStorage, and
 * on reload reconnects by polling the detail endpoint until a still-`running` run settles.
 *
 * Its own hook and its own storage key: /browse shares no state with the Agents page.
 */
export function useBrowserAgent(): UseBrowserAgentReturn {
  const queryClient = useQueryClient();
  const [steps, setSteps] = useState<BrowserStepState[]>([]);
  const [maxSteps, setMaxSteps] = useState<number | null>(null);
  const [output, setOutput] = useState<string | null>(null);
  const [sources, setSources] = useState<string[]>([]);
  const [stopReason, setStopReason] = useState<BrowserStopReason>("");
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [disabled, setDisabled] = useState<{
    detail: string;
    hint: string;
  } | null>(null);
  // Restore the last visit's workspace (this page's own key, not agentsSession).
  const [runId, setRunId] = useState<string | null>(
    () => readSession().runId ?? null,
  );
  const [query, setQuery] = useState(() => readSession().query ?? "");
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    writeSession({ query, runId });
  }, [query, runId]);

  const loadFromDetail = useCallback((detail: BrowserRunDetail) => {
    abortRef.current?.abort();
    setSteps(detail.steps);
    setMaxSteps(detail.max_steps);
    setOutput(detail.output || null);
    setSources(detail.urls_visited ?? []);
    setStopReason(detail.stop_reason);
    setError(detail.error || null);
    setRunId(detail.id);
    setQuery(detail.query);
    setIsRunning(detail.status === "running");
  }, []);

  // Reconnect: a run left `running` by a refresh keeps going server-side (the workflow is
  // driven by a background thread), so poll its detail until it reaches a terminal status.
  useEffect(() => {
    if (!runId || !isRunning) return;
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const detail = await fetchBrowserRunDetail(runId);
        if (cancelled) return;
        if (detail.status !== "running") loadFromDetail(detail);
        else setSteps(detail.steps);
      } catch {
        // transient - try again on the next tick
      }
    }, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [runId, isRunning, loadFromDetail]);

  // On mount, rehydrate whatever run the last visit left behind (including one still
  // running: the workflow keeps going server-side after a refresh).
  useEffect(() => {
    const id = readSession().runId;
    if (!id) return;
    fetchBrowserRunDetail(id)
      .then(loadFromDetail)
      .catch(() => setRunId(null));
  }, [loadFromDetail]);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setSteps([]);
    setMaxSteps(null);
    setOutput(null);
    setSources([]);
    setStopReason("");
    setIsRunning(false);
    setError(null);
    setRunId(null);
  }, []);

  const run = useCallback(
    (nextQuery: string, opts?: { provider?: BrowserProvider; maxSteps?: number }) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setSteps([]);
      setOutput(null);
      setSources([]);
      setStopReason("");
      setError(null);
      setDisabled(null);
      setRunId(null);
      setQuery(nextQuery);
      setIsRunning(true);

      function handleEvent(event: BrowserEvent) {
        if (event.event === "started") {
          setMaxSteps(event.max_steps);
        } else if (event.event === "step") {
          setSteps((prev) => [...prev, stepFromEvent(event)]);
        } else if (event.event === "result") {
          setOutput(event.output);
          setSources(event.sources);
          setStopReason(event.stop_reason);
          setRunId(event.run_id);
          setIsRunning(false);
          queryClient.invalidateQueries({ queryKey: queryKeys.browser.runs() });
        } else if (event.event === "stopped") {
          setIsRunning(false);
          queryClient.invalidateQueries({ queryKey: queryKeys.browser.runs() });
        } else if (event.event === "error") {
          setError(event.error);
          setIsRunning(false);
          queryClient.invalidateQueries({ queryKey: queryKeys.browser.runs() });
        }
      }

      (async () => {
        try {
          const response = await streamBrowser(
            {
              query: nextQuery,
              provider: opts?.provider ?? null,
              max_steps: opts?.maxSteps ?? null,
            },
            controller.signal,
          );
          await readSSE<BrowserEvent>(response, handleEvent);
          setIsRunning(false);
        } catch (err: unknown) {
          if (err instanceof BrowserDisabledError) {
            setDisabled({ detail: err.message, hint: err.hint });
            setIsRunning(false);
          } else if (err instanceof BrowserBusyError) {
            setError(err.message);
            setIsRunning(false);
          } else if (err instanceof Error && err.name !== "AbortError") {
            setError(err.message);
            setIsRunning(false);
          }
        }
      })();
    },
    [queryClient],
  );

  const stop = useCallback(() => {
    if (!runId) {
      // No run id yet (the stream has not reported one): drop the connection locally.
      abortRef.current?.abort();
      setIsRunning(false);
      return;
    }
    stopBrowserRun(runId)
      .catch(() => undefined)
      .finally(() => {
        queryClient.invalidateQueries({ queryKey: queryKeys.browser.runs() });
      });
  }, [runId, queryClient]);

  return {
    steps,
    maxSteps,
    output,
    sources,
    stopReason,
    isRunning,
    error,
    disabled,
    runId,
    query,
    setQuery,
    run,
    stop,
    reset,
    loadFromDetail,
  };
}
