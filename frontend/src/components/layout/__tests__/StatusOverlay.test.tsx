import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderWithQuery } from "@/test/render";
import { StatusOverlay } from "@/components/layout/StatusOverlay";
import { MOCK_HEALTH } from "@/test/handlers";

const BASE = "http://localhost:8004";

describe("StatusOverlay", () => {
  it("renders all six indicator labels", async () => {
    server.use(
      http.get(`${BASE}/api/health/`, () => HttpResponse.json(MOCK_HEALTH))
    );
    renderWithQuery(<StatusOverlay />);
    await waitFor(() => expect(screen.getByText("API")).toBeTruthy());
    expect(screen.getByText("DB")).toBeTruthy();
    expect(screen.getByText("Redis")).toBeTruthy();
    expect(screen.getByText("Celery")).toBeTruthy();
    expect(screen.getByText("Beat")).toBeTruthy();
    expect(screen.getByText("Ollama")).toBeTruthy();
  });

  it("renders 'dev' version badge in test environment", async () => {
    server.use(
      http.get(`${BASE}/api/health/`, () => HttpResponse.json(MOCK_HEALTH))
    );
    renderWithQuery(<StatusOverlay />);
    await waitFor(() => expect(screen.getByText("dev")).toBeTruthy());
  });

  it("shows red dots when services are down", async () => {
    server.use(
      http.get(`${BASE}/api/health/`, () =>
        HttpResponse.json({ ...MOCK_HEALTH, db: false, redis: false })
      )
    );
    const { container } = renderWithQuery(<StatusOverlay />);
    await waitFor(() =>
      expect(container.querySelectorAll(".bg-red-500").length).toBeGreaterThan(0)
    );
  });

  it("shows red dot for Ollama when ollama is down", async () => {
    server.use(
      http.get(`${BASE}/api/health/`, () =>
        HttpResponse.json({ ...MOCK_HEALTH, ollama: false })
      )
    );
    const { container } = renderWithQuery(<StatusOverlay />);
    await waitFor(() => expect(screen.getByText("Ollama")).toBeTruthy());
    expect(container.querySelectorAll(".bg-red-500").length).toBeGreaterThan(0);
  });
});
