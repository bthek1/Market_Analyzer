import type {
  ChatSessionDetail,
  ChatSessionSummary,
  ChatTurn,
  ChatTurnRequest,
} from "@/types/chat";
import { ChatBusyError } from "@/types/chat";
import { apiClient, refreshAccessToken } from "./client";

const TURNS = "/api/llm/chat-agent";
const SESSIONS = "/api/llm/chat/sessions";

/**
 * POST one turn and return the raw SSE response.
 *
 * `fetch` rather than the axios client because axios cannot stream a response body. That
 * also means this request never reaches the client's response interceptor, so the two things
 * the interceptor does have to be done by hand here: refresh an expired access token, and
 * turn a failed response into a thrown error.
 *
 * The second one is not cosmetic. `readSSE` finds no `data:` lines in a JSON error body, so
 * it yields NO events and returns normally - the hook then marks the turn finished with an
 * empty reply, and the transcript renders "No reply." with nothing explaining why. Every
 * failure has to become an exception here or it is invisible.
 */
export async function streamChatTurn(
  payload: ChatTurnRequest,
  signal?: AbortSignal,
): Promise<Response> {
  const send = (token: string | null) =>
    fetch(`${import.meta.env.VITE_API_BASE_URL}${TURNS}/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(payload),
      signal,
    });

  let response = await send(localStorage.getItem("access_token"));

  // Retry once with a fresh token, mirroring the axios interceptor. Without this an expired
  // access token breaks chat alone while every other page silently recovers.
  if (response.status === 401) {
    const refreshed = await refreshAccessToken();
    if (refreshed) response = await send(refreshed);
  }

  // 409 is a normal state with its own message, not a generic failure: the conversation
  // already has a turn in flight, and running a second would fork the transcript.
  if (response.status === 409) {
    const body = await response.json().catch(() => ({}));
    throw new ChatBusyError(
      body.detail ?? "This conversation already has a turn in progress.",
    );
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      body.detail ?? `The server rejected the message (HTTP ${response.status}).`,
    );
  }
  return response;
}

export async function fetchChatTurn(id: string): Promise<ChatTurn> {
  const { data } = await apiClient.get<ChatTurn>(`${TURNS}/${id}/`);
  return data;
}

export async function fetchChatSessions(): Promise<ChatSessionSummary[]> {
  const { data } = await apiClient.get<{ results: ChatSessionSummary[] }>(
    `${SESSIONS}/`,
  );
  return data.results;
}

export async function fetchChatSession(id: string): Promise<ChatSessionDetail> {
  const { data } = await apiClient.get<ChatSessionDetail>(`${SESSIONS}/${id}/`);
  return data;
}

export async function createChatSession(): Promise<ChatSessionSummary> {
  const { data } = await apiClient.post<ChatSessionSummary>(`${SESSIONS}/`, {});
  return data;
}

export async function renameChatSession(
  id: string,
  title: string,
): Promise<ChatSessionSummary> {
  const { data } = await apiClient.patch<ChatSessionSummary>(`${SESSIONS}/${id}/`, {
    title,
  });
  return data;
}

export async function deleteChatSession(id: string): Promise<void> {
  await apiClient.delete(`${SESSIONS}/${id}/`);
}

/** Cooperative cancel: flips the run's DB status, which the worker sees at a step boundary. */
export async function stopChatTurn(id: string): Promise<void> {
  // "chat-agent" is the registry SLUG, which is what STOPPABLE_RUN_MODELS keys on.
  await apiClient.post("/api/llm/runs/stop/", { type: "chat-agent", id });
}
