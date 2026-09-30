import React from "react";
import { describe, it, expect } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import { renderWithQuery } from "@/test/render";
import { RedisKeysTable } from "../RedisKeysTable";

describe("RedisKeysTable", () => {
  it("renders key rows from the API", async () => {
    renderWithQuery(<RedisKeysTable />);
    await waitFor(() =>
      expect(screen.getByText("celery-task-meta-abc123")).toBeTruthy(),
    );
    expect(screen.getByText("_kombu.binding.celery")).toBeTruthy();
  });

  it("shows type badges", async () => {
    renderWithQuery(<RedisKeysTable />);
    await waitFor(() => {
      const badges = screen.getAllByText("string");
      expect(badges.length).toBeGreaterThan(0);
    });
  });

  it("shows persistent label for ttl -1", async () => {
    renderWithQuery(<RedisKeysTable />);
    await waitFor(() => expect(screen.getByText("persistent")).toBeTruthy());
  });

  it("renders namespace filter buttons", async () => {
    renderWithQuery(<RedisKeysTable />);
    await waitFor(() => expect(screen.getAllByText(/celery/).length).toBeGreaterThan(0));
  });

  it("filters rows by search input", async () => {
    renderWithQuery(<RedisKeysTable />);
    await waitFor(() =>
      expect(screen.getByText("celery-task-meta-abc123")).toBeTruthy(),
    );
    const input = screen.getByPlaceholderText("Search keys...");
    fireEvent.change(input, { target: { value: "kombu" } });
    await waitFor(() => {
      expect(screen.queryByText("celery-task-meta-abc123")).toBeNull();
      expect(screen.getByText("_kombu.binding.celery")).toBeTruthy();
    });
  });

  it("shows no keys found when search has no match", async () => {
    renderWithQuery(<RedisKeysTable />);
    await waitFor(() =>
      expect(screen.getByText("celery-task-meta-abc123")).toBeTruthy(),
    );
    const input = screen.getByPlaceholderText("Search keys...");
    fireEvent.change(input, { target: { value: "xyznonexistent" } });
    await waitFor(() => expect(screen.getByText("No keys found")).toBeTruthy());
  });

  it("clicking a row opens the value drawer", async () => {
    renderWithQuery(<RedisKeysTable />);
    await waitFor(() =>
      expect(screen.getByText("celery-task-meta-abc123")).toBeTruthy(),
    );
    fireEvent.click(screen.getByText("celery-task-meta-abc123"));
    await waitFor(() => expect(screen.getByText("✕")).toBeTruthy());
  });

  it("clicking the close button dismisses the drawer", async () => {
    renderWithQuery(<RedisKeysTable />);
    await waitFor(() =>
      expect(screen.getByText("celery-task-meta-abc123")).toBeTruthy(),
    );
    fireEvent.click(screen.getByText("celery-task-meta-abc123"));
    await waitFor(() => expect(screen.getAllByText("Key").length).toBeGreaterThan(0));
    fireEvent.click(screen.getByText("✕"));
    await waitFor(() => expect(screen.queryByText("✕")).toBeNull());
  });
});
