import React from "react";
import { describe, it, expect } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithQuery } from "@/test/render";
import { RedisInfoCards } from "../RedisInfoCards";

describe("RedisInfoCards", () => {
  it("renders stat cards with server info", async () => {
    renderWithQuery(<RedisInfoCards />);
    await waitFor(() => expect(screen.getByText("7.2.4")).toBeTruthy());
    expect(screen.getByText("Redis Version")).toBeTruthy();
    expect(screen.getByText("2.41M")).toBeTruthy();
    expect(screen.getByText("3")).toBeTruthy();
  });

  it("displays total key count from keyspace", async () => {
    renderWithQuery(<RedisInfoCards />);
    await waitFor(() => expect(screen.getByText("142")).toBeTruthy());
  });

  it("displays cache hit rate", async () => {
    renderWithQuery(<RedisInfoCards />);
    await waitFor(() => {
      const rates = screen.getAllByText(/\d+\.\d+%/);
      expect(rates.length).toBeGreaterThan(0);
    });
  });

  it("shows auto-refresh note after data loads", async () => {
    renderWithQuery(<RedisInfoCards />);
    await waitFor(() =>
      expect(screen.getByText(/auto-refreshes every 10s/)).toBeTruthy(),
    );
  });
});
