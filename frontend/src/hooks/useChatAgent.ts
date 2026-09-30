import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { readSSE } from "@/api/browser";
import {
  fetchChatSession,
  fetchChatTurn,
  stopChatTurn,
  streamChatTurn,
} from "@/api/chat";
import { queryKeys } from "@/api/queryKeys";
import type {
  ChatEvent,
  ChatSessionDetail,
  ChatStepEvent,
  ChatStepState,
  ChatTurn,
} from "@/types/chat";
import { ChatBusyError } from "@/types/chat";

const SESSION_KEY = "chatSession";
const POLL_MS = 2000;

/**
 * One line of the transcript. A turn in flight has no `output` yet, so the UI needs a shape
 * that carries the user's message, the tool calls so far, and the reply once it lands.
 */
export interface TranscriptTurn {
  id: string | null;
  query: string;
  output: string;
  error: string;
  status: ChatTurn["status"];
  steps: ChatStepState[];
  toolsUsed: string[];
  compacted: number;
}

export interface UseChatAgentReturn {
  sessionId: string | null;
  title: string;
  summary: string;
  turns: TranscriptTurn[];
  isRunning: boolean;
  error: string | null;
  tools: string[];
  send: (message: string) => void;
  stop: () => void;
  openSession: (id: string) => void;
  newSession: () => void;
  loadFromDetail: (detail: ChatSessionDetail) => void;
}

function stepFromEvent({ event: _event, ...step }: ChatStepEvent): ChatStepState {
  return step;
}

/** A persisted turn as the transcript renders it. The two must agree - see `turnFromRun`. */
export function turnFromRun(run: ChatTurn): TranscriptTurn {
  return {
    id: run.id,
    query: run.query,
    output: run.output,
    error: run.error,
    status: run.status,
    steps: run.steps,
    toolsUsed: run.tools_used ?? [],
    compacted: run.compacted,
  };
}

function readSessionId(): string | null {
  try {
    return localStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
}

function writeSessionId(id: string | null) {
  try {
    if (id) localStorage.setItem(SESSION_KEY, id);
    else localStorage.removeItem(SESSION_KEY);
  } catch {
    // storage unavailable (private mode / quota) - the page still works
  }
}

/**
 * Drives one conversation: streams each turn, and restores the transcript from the server.
 *
 * Only the SESSION ID is persisted locally. The transcript itself is always re-fetched,
 * because the server owns it - `AgentRun.query`/`output` ARE the messages. Keeping a copy in
 * localStorage would be a second source of truth that silently drifts from the one the model
 * is actually being sent.
 */
export function useChatAgent(): UseChatAgentReturn {
  const queryClient = useQueryClient();
  const [sessionId, setSessionId] = useState<string | null>(() => readSessionId());
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [turns, setTurns] = useState<TranscriptTurn[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tools, setTools] = useState<string[]>([]);
  const [liveRunId, setLiveRunId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    writeSessionId(sessionId);
  }, [sessionId]);

  const loadFromDetail = useCallback((detail: ChatSessionDetail) => {
    abortRef.current?.abort();
    setSessionId(detail.id);
    setTitle(detail.title);
    setSummary(detail.summary);
    setTurns(detail.turns.map(turnFromRun));
    setError(null);
    const last = detail.turns[detail.turns.length - 1];
    const running = last?.status === "running";
    setIsRunning(running);
    setLiveRunId(running ? last.id : null);
  }, []);

  // Restore the conversation the last visit left open. The transcript comes from the
  // server, never from storage.
  useEffect(() => {
    const id = readSessionId();
    if (!id) return;
    fetchChatSession(id)
      .then(loadFromDetail)
      .catch(() => setSessionId(null));
  }, [loadFromDetail]);

  // Reconnect: a turn left `running` by a refresh keeps going server-side
  // (`stream_in_background` drives it on a daemon thread), so poll until it settles.
  useEffect(() => {
    if (!liveRunId || !isRunning) return;
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const run = await fetchChatTurn(liveRunId);
        if (cancelled) return;
        setTurns((prev) =>
          prev.map((t) => (t.id === run.id ? turnFromRun(run) : t)),
        );
        if (run.status !== "running") {
          setIsRunning(false);
          setLiveRunId(null);
          queryClient.invalidateQueries({ queryKey: queryKeys.chat.sessions() });
        }
      } catch {
        // transient - try again on the next tick
      }
    }, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [liveRunId, isRunning, queryClient]);

  const openSession = useCallback(
    (id: string) => {
      abortRef.current?.abort();
      setIsRunning(false);
      setLiveRunId(null);
      setTurns([]);
      setError(null);
      setSessionId(id);
      fetchChatSession(id)
        .then(loadFromDetail)
        .catch(() => setError("Could not open that conversation."));
    },
    [loadFromDetail],
  );

  const newSession = useCallback(() => {
    // No POST: the turn endpoint creates the session when none is given, so an abandoned
    // "New chat" click leaves no empty row behind.
    abortRef.current?.abort();
    setSessionId(null);
    setTitle("");
    setSummary("");
    setTurns([]);
    setError(null);
    setIsRunning(false);
    setLiveRunId(null);
  }, []);

  const send = useCallback(
    (message: string) => {
      if (!message.trim() || isRunning) return;

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setError(null);
      setIsRunning(true);
      // The pending turn renders immediately; the reply fills in as the stream arrives.
      setTurns((prev) => [
        ...prev,
        {
          id: null,
          query: message,
          output: "",
          error: "",
          status: "running",
          steps: [],
          toolsUsed: [],
          compacted: 0,
        },
      ]);

      const patchLast = (patch: Partial<TranscriptTurn>) =>
        setTurns((prev) =>
          prev.map((t, i) => (i === prev.length - 1 ? { ...t, ...patch } : t)),
        );

      // Whether the stream ever finished the turn. A connection that opens and then yields
      // nothing terminal used to leave the turn `running` with an empty reply, which the
      // transcript renders as a bare "No reply." - a dead end with nothing to act on.
      let settled = false;

      function handleEvent(event: ChatEvent) {
        if (event.event === "started") {
          setTools(event.tools);
          setLiveRunId(event.run_id);
          if (event.session_id) setSessionId(event.session_id);
          patchLast({ id: event.run_id, compacted: event.compacted });
        } else if (event.event === "step") {
          const step = stepFromEvent(event);
          setTurns((prev) =>
            prev.map((t, i) =>
              i === prev.length - 1
                ? {
                    ...t,
                    steps: [...t.steps, step],
                    toolsUsed: step.tool && !t.toolsUsed.includes(step.tool)
                      ? [...t.toolsUsed, step.tool]
                      : t.toolsUsed,
                  }
                : t,
            ),
          );
        } else if (event.event === "delta") {
          // Appended, not replaced: the reply renders as it is written. `result` then sets
          // the authoritative text, which must equal the deltas concatenated - the backend
          // persists exactly what it streamed.
          setTurns((prev) =>
            prev.map((t, i) =>
              i === prev.length - 1 ? { ...t, output: t.output + event.text } : t,
            ),
          );
        } else if (event.event === "result") {
          settled = true;
          patchLast({ output: event.output, status: "done", id: event.run_id });
          setIsRunning(false);
          setLiveRunId(null);
          queryClient.invalidateQueries({ queryKey: queryKeys.chat.sessions() });
        } else if (event.event === "stopped") {
          settled = true;
          patchLast({ status: "stopped" });
          setIsRunning(false);
          setLiveRunId(null);
          queryClient.invalidateQueries({ queryKey: queryKeys.chat.sessions() });
        } else if (event.event === "error") {
          settled = true;
          patchLast({ status: "error", error: event.error });
          setError(event.error);
          setIsRunning(false);
          setLiveRunId(null);
          queryClient.invalidateQueries({ queryKey: queryKeys.chat.sessions() });
        }
      }

      (async () => {
        try {
          const response = await streamChatTurn(
            { message, session: sessionId },
            controller.signal,
          );
          await readSSE<ChatEvent>(response, handleEvent);
          if (!settled) {
            // The stream ended without a result/stopped/error. Say so rather than leaving a
            // blank bubble: the turn may still be running server-side, and either way the
            // user needs something other than silence.
            const detail = "The connection ended before the reply finished.";
            setError(detail);
            patchLast({ status: "error", error: detail });
          }
          setIsRunning(false);
        } catch (err: unknown) {
          if (err instanceof ChatBusyError) {
            setError(err.message);
            // Drop the optimistic turn: the server refused it, so it is not in the
            // transcript and leaving it would show a message that was never sent.
            setTurns((prev) => prev.slice(0, -1));
            setIsRunning(false);
          } else if (err instanceof Error && err.name !== "AbortError") {
            setError(err.message);
            patchLast({ status: "error", error: err.message });
            setIsRunning(false);
          }
        }
      })();
    },
    [sessionId, isRunning, queryClient],
  );

  const stop = useCallback(() => {
    if (!liveRunId) {
      abortRef.current?.abort();
      setIsRunning(false);
      return;
    }
    stopChatTurn(liveRunId)
      .catch(() => undefined)
      .finally(() => {
        queryClient.invalidateQueries({ queryKey: queryKeys.chat.sessions() });
      });
  }, [liveRunId, queryClient]);

  return {
    sessionId,
    title,
    summary,
    turns,
    isRunning,
    error,
    tools,
    send,
    stop,
    openSession,
    newSession,
    loadFromDetail,
  };
}
