import { describe, it, expect } from "vitest";
import { waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderHookWithQuery } from "@/test/render";
import { useSystemStatus } from "@/hooks/useSystemStatus";
import { MOCK_HEALTH } from "@/test/handlers";

const BASE = "http://localhost:8004";

describe("useSystemStatus", () => {
  it("returns all ok when health endpoint succeeds", async () => {
    server.use(
      http.get(`${BASE}/api/health/`, () => HttpResponse.json(MOCK_HEALTH))
    );
    const { result } = renderHookWithQuery(() => useSystemStatus());
    await waitFor(() => expect(result.current.backendOk).toBe(true));
    expect(result.current.dbOk).toBe(true);
    expect(result.current.redisOk).toBe(true);
    expect(result.current.celeryOk).toBe(true);
    expect(result.current.beatOk).toBe(true);
  });

  it("returns all false when health endpoint fails", async () => {
    server.use(
      http.get(`${BASE}/api/health/`, () =>
        HttpResponse.json(null, { status: 503 })
      )
    );
    const { result } = renderHookWithQuery(() => useSystemStatus());
    await waitFor(() => expect(result.current.isError ?? !result.current.backendOk).toBe(true), {
      timeout: 2000,
    });
    expect(result.current.backendOk).toBe(false);
    expect(result.current.dbOk).toBe(false);
    expect(result.current.redisOk).toBe(false);
    expect(result.current.celeryOk).toBe(false);
    expect(result.current.beatOk).toBe(false);
  });

  it("reflects individual service failures from response", async () => {
    server.use(
      http.get(`${BASE}/api/health/`, () =>
        HttpResponse.json({ ...MOCK_HEALTH, db: false, celery: false, beat: false })
      )
    );
    const { result } = renderHookWithQuery(() => useSystemStatus());
    await waitFor(() => expect(result.current.backendOk).toBe(true));
    expect(result.current.dbOk).toBe(false);
    expect(result.current.redisOk).toBe(true);
    expect(result.current.celeryOk).toBe(false);
    expect(result.current.beatOk).toBe(false);
  });

  it("returns 'dev' for version in test environment", async () => {
    server.use(
      http.get(`${BASE}/api/health/`, () => HttpResponse.json(MOCK_HEALTH))
    );
    const { result } = renderHookWithQuery(() => useSystemStatus());
    await waitFor(() => expect(result.current.backendOk).toBe(true));
    // import.meta.env.DEV is true in vitest, so version is always "dev"
    expect(result.current.version).toBe("dev");
  });
});
