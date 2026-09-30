import type {
  BrowserRunDetail,
  BrowserRunRequest,
  BrowserRunSummary,
} from "@/types/browser";
import { BrowserBusyError, BrowserDisabledError } from "@/types/browser";
import { apiClient, refreshAccessToken } from "./client";

const BASE = "/api/llm/browser";

/**
 * POST the query and return the raw SSE response. Uses `fetch` rather than the axios
 * client because axios cannot stream a response body; the JWT is attached by hand, the
 * same way the Agents page's stream helpers do it.
 */
export async function streamBrowser(
  payload: BrowserRunRequest,
  signal?: AbortSignal,
): Promise<Response> {
  const send = (token: string | null) =>
    fetch(`${import.meta.env.VITE_API_BASE_URL}${BASE}/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(payload),
      signal,
    });

  let response = await send(localStorage.getItem("access_token"));

  // Retry once with a fresh token, mirroring the axios interceptor this path cannot reach.
  // Chat had the same gap and it showed up as every reply coming back blank (issue #8).
  if (response.status === 401) {
    const refreshed = await refreshAccessToken();
    if (refreshed) response = await send(refreshed);
  }

  // 503/429 are normal states with their own UI, not generic failures.
  if (response.status === 503) {
    const body = await response.json().catch(() => ({}));
    throw new BrowserDisabledError(
      body.detail ?? "The browser agent is disabled.",
      body.hint ?? "",
    );
  }
  if (response.status === 429) {
    const body = await response.json().catch(() => ({}));
    throw new BrowserBusyError(
      body.detail ?? "A browser run is already in progress.",
    );
  }

  // Any other failure has to become an exception: `readSSE` finds no `data:` lines in a
  // JSON error body, so it yields nothing and returns normally, leaving the run looking
  // finished-but-empty with nothing explaining why.
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      body.detail ?? `The server rejected the request (HTTP ${response.status}).`,
    );
  }
  return response;
}

/** Drive an SSE response, invoking `onEvent` per `data:` line. Malformed lines are skipped. */
export async function readSSE<T>(
  response: Response,
  onEvent: (event: T) => void,
): Promise<void> {
  if (!response.body) return;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const raw = line.slice("data: ".length).trim();
      if (!raw) continue;
      try {
        onEvent(JSON.parse(raw) as T);
      } catch {
        // malformed line - skip
      }
    }
  }
}

export async function fetchBrowserRuns(): Promise<BrowserRunSummary[]> {
  const { data } = await apiClient.get<{ results: BrowserRunSummary[] }>(
    `${BASE}/history/`,
  );
  return data.results;
}

export async function fetchBrowserRunDetail(
  id: string,
): Promise<BrowserRunDetail> {
  const { data } = await apiClient.get<BrowserRunDetail>(`${BASE}/${id}/`);
  return data;
}

/**
 * Screenshots are owner-checked on every request, so they cannot be dropped straight
 * into an `<img src>` (that request would carry no JWT). Fetch the bytes through the
 * authenticated client and hand back an object URL for the caller to revoke.
 */
export async function fetchScreenshot(
  runId: string,
  order: number,
): Promise<string> {
  const { data } = await apiClient.get<Blob>(
    `${BASE}/${runId}/screenshot/${order}/`,
    { responseType: "blob" },
  );
  return URL.createObjectURL(data);
}

export async function stopBrowserRun(id: string): Promise<{ stopped: boolean }> {
  const { data } = await apiClient.post<{ stopped: boolean }>(
    "/api/llm/runs/stop/",
    { type: "browser", id },
  );
  return data;
}
