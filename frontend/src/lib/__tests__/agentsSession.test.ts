import { describe, it, expect, afterEach } from "vitest";
import {
  loadAgentsSession,
  saveAgentsSession,
  clearAgentsSession,
  type AgentsSession,
} from "@/lib/agentsSession";

const KEY = "agents.session.v1";

afterEach(() => {
  localStorage.clear();
});

const sample: AgentsSession = {
  selectedTypes: ["chain", "react"],
  query: "Analyse AAPL",
  runs: { chain: "run-1", react: "run-2" },
};

describe("agentsSession", () => {
  it("returns null when nothing is stored", () => {
    expect(loadAgentsSession()).toBeNull();
  });

  it("round-trips a saved session", () => {
    saveAgentsSession(sample);
    expect(loadAgentsSession()).toEqual(sample);
  });

  it("clear removes the stored session", () => {
    saveAgentsSession(sample);
    clearAgentsSession();
    expect(loadAgentsSession()).toBeNull();
  });

  it("drops unknown workflow types and non-string run ids", () => {
    localStorage.setItem(
      KEY,
      JSON.stringify({
        // A pre-issue-#8 payload: `mode` is stored but no longer read.
        mode: "workflows",
        selectedTypes: ["chain", "bogus"],
        query: "x",
        runs: { chain: "ok", bogus: "nope", react: 5 },
      }),
    );
    const loaded = loadAgentsSession();
    expect(loaded?.selectedTypes).toEqual(["chain"]);
    expect(loaded?.runs).toEqual({ chain: "ok" });
  });

  it("returns null for malformed JSON", () => {
    localStorage.setItem(KEY, "{not json");
    expect(loadAgentsSession()).toBeNull();
  });

  it("returns null when no known types survive filtering", () => {
    localStorage.setItem(
      KEY,
      JSON.stringify({
        mode: "chat",
        selectedTypes: ["bogus"],
        query: "",
        runs: {},
      }),
    );
    expect(loadAgentsSession()).toBeNull();
  });
});

describe("agentsSession - the removed `mode` field", () => {
  it("loads a payload written before chat moved to its own page", () => {
    // Chat was a MODE on /agents until issue #8. A stale `mode: "chat"` in a user's
    // localStorage must not wedge the page - the shape is parsed field by field, so an
    // unknown key is simply not read.
    localStorage.setItem(
      "agents.session.v1",
      JSON.stringify({
        mode: "chat",
        selectedTypes: ["chain"],
        query: "is AAPL cheap",
        runs: {},
      }),
    );

    const session = loadAgentsSession();

    expect(session).not.toBeNull();
    expect(session!.selectedTypes).toEqual(["chain"]);
    expect(session!.query).toBe("is AAPL cheap");
    expect(session).not.toHaveProperty("mode");
  });

  it("does not write `mode` back out", () => {
    saveAgentsSession({ selectedTypes: ["chain"], query: "q", runs: {} });

    expect(localStorage.getItem("agents.session.v1")).not.toContain("mode");
  });
});
