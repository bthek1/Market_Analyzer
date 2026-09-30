import React from "react";
import { describe, it, expect } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { renderWithQuery } from "@/test/render";
import { OptionsTab } from "@/components/companies/OptionsTab";
import {
  MOCK_OPTIONS_CHAIN,
  MOCK_PAGINATED_OPTIONS_EXPIRIES,
} from "@/test/handlers";

const BASE = "http://localhost:8004";

describe("OptionsTab", () => {
  it("shows no data message when no expiries available", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/options/`, () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
    );
    renderWithQuery(<OptionsTab companyId={1} />);
    await waitFor(() =>
      expect(screen.getByText(/No options data available/)).toBeTruthy(),
    );
  });

  it("renders expiry date buttons", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/options/`, () =>
        HttpResponse.json(MOCK_PAGINATED_OPTIONS_EXPIRIES),
      ),
      http.get(`${BASE}/api/companies/:id/options/:expiryDate/`, () =>
        HttpResponse.json(MOCK_OPTIONS_CHAIN),
      ),
    );
    renderWithQuery(<OptionsTab companyId={1} />);
    await waitFor(() => expect(screen.getByText("2026-06-20")).toBeTruthy());
  });

  it("renders Calls and Puts tab toggles", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/options/`, () =>
        HttpResponse.json(MOCK_PAGINATED_OPTIONS_EXPIRIES),
      ),
      http.get(`${BASE}/api/companies/:id/options/:expiryDate/`, () =>
        HttpResponse.json(MOCK_OPTIONS_CHAIN),
      ),
    );
    renderWithQuery(<OptionsTab companyId={1} />);
    await waitFor(() => expect(screen.getByText("calls")).toBeTruthy());
    expect(screen.getByText("puts")).toBeTruthy();
  });

  it("renders calls chain table with Strike column", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/options/`, () =>
        HttpResponse.json(MOCK_PAGINATED_OPTIONS_EXPIRIES),
      ),
      http.get(`${BASE}/api/companies/:id/options/:expiryDate/`, () =>
        HttpResponse.json(MOCK_OPTIONS_CHAIN),
      ),
    );
    renderWithQuery(<OptionsTab companyId={1} />);
    await waitFor(() => expect(screen.getByText("Strike")).toBeTruthy());
  });

  it("renders call contract strike value", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/options/`, () =>
        HttpResponse.json(MOCK_PAGINATED_OPTIONS_EXPIRIES),
      ),
      http.get(`${BASE}/api/companies/:id/options/:expiryDate/`, () =>
        HttpResponse.json(MOCK_OPTIONS_CHAIN),
      ),
    );
    renderWithQuery(<OptionsTab companyId={1} />);
    // strike "190.00" → formatted as 190.00
    await waitFor(() => expect(screen.getByText("190.00")).toBeTruthy());
  });

  it("switches to puts tab when clicked", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/options/`, () =>
        HttpResponse.json(MOCK_PAGINATED_OPTIONS_EXPIRIES),
      ),
      http.get(`${BASE}/api/companies/:id/options/:expiryDate/`, () =>
        HttpResponse.json(MOCK_OPTIONS_CHAIN),
      ),
    );
    renderWithQuery(<OptionsTab companyId={1} />);
    await waitFor(() => expect(screen.getByText("puts")).toBeTruthy());
    fireEvent.click(screen.getByText("puts"));
    // put contract strike: 185.00
    await waitFor(() => expect(screen.getByText("185.00")).toBeTruthy());
  });

  it("renders IV column", async () => {
    server.use(
      http.get(`${BASE}/api/companies/:id/options/`, () =>
        HttpResponse.json(MOCK_PAGINATED_OPTIONS_EXPIRIES),
      ),
      http.get(`${BASE}/api/companies/:id/options/:expiryDate/`, () =>
        HttpResponse.json(MOCK_OPTIONS_CHAIN),
      ),
    );
    renderWithQuery(<OptionsTab companyId={1} />);
    await waitFor(() => expect(screen.getByText("IV")).toBeTruthy());
    // call IV: 0.28 → 28.0%
    expect(screen.getByText("28.0%")).toBeTruthy();
  });
});
