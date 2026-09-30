import { describe, it, expect } from "vitest";
import {
  analyseRequestSchema,
  chatRequestSchema,
  llmSettingsSchema,
  messageSchema,
  summariseRequestSchema,
} from "@/schemas/llm";

const VALID_SETTINGS = {
  base_url: "http://localhost:11434",
  main_model: "qwen3:8b",
  classifier_model: "qwen3:1.7b",
  embed_model: "nomic-embed-text",
  timeout: 60,
  num_parallel: 4,
  route_mode: "llm" as const,
  route_threshold: 0.75,
  react_max_steps: 6,
  eval_max_iterations: 3,
  eval_threshold: 8,
  plan_max_steps: 20,
  plan_max_replans: 5,
  orch_max_workers: 4,
  multiagent_max_tools: 4,
  dag_max_nodes: 6,
  auto_max_cycles: 8,
  auto_max_subagents: 3,
  auto_subagent_steps: 3,
  auto_no_progress: 2,
  browser_enabled: false,
  browser_provider: "anthropic" as const,
  browser_model: "claude-sonnet-5",
  browser_max_steps: 15,
  browser_timeout_s: 300,
  browser_headless: true,
  browser_allowed_domains: "*.sec.gov",
};

describe("messageSchema", () => {
  it("parses valid user message", () => {
    const result = messageSchema.safeParse({ role: "user", content: "Hello" });
    expect(result.success).toBe(true);
  });

  it("parses assistant and system roles", () => {
    expect(messageSchema.safeParse({ role: "assistant", content: "Hi" }).success).toBe(true);
    expect(messageSchema.safeParse({ role: "system", content: "You are helpful" }).success).toBe(true);
  });

  it("rejects invalid role", () => {
    const result = messageSchema.safeParse({ role: "bot", content: "Hi" });
    expect(result.success).toBe(false);
  });

  it("rejects empty content", () => {
    const result = messageSchema.safeParse({ role: "user", content: "" });
    expect(result.success).toBe(false);
  });

  it("rejects missing role", () => {
    const result = messageSchema.safeParse({ content: "Hi" });
    expect(result.success).toBe(false);
  });

  it("rejects missing content", () => {
    const result = messageSchema.safeParse({ role: "user" });
    expect(result.success).toBe(false);
  });
});

describe("chatRequestSchema", () => {
  it("parses valid chat request", () => {
    const result = chatRequestSchema.safeParse({
      messages: [{ role: "user", content: "Hi" }],
    });
    expect(result.success).toBe(true);
  });

  it("parses with optional model", () => {
    const result = chatRequestSchema.safeParse({
      messages: [{ role: "user", content: "Hi" }],
      model: "llama3.2:latest",
    });
    expect(result.success).toBe(true);
    if (result.success) expect(result.data.model).toBe("llama3.2:latest");
  });

  it("parses without model (defaults to undefined)", () => {
    const result = chatRequestSchema.safeParse({
      messages: [{ role: "user", content: "Hi" }],
    });
    expect(result.success).toBe(true);
    if (result.success) expect(result.data.model).toBeUndefined();
  });

  it("rejects empty messages array", () => {
    const result = chatRequestSchema.safeParse({ messages: [] });
    expect(result.success).toBe(false);
  });

  it("rejects missing messages", () => {
    const result = chatRequestSchema.safeParse({});
    expect(result.success).toBe(false);
  });

  it("rejects invalid message in array", () => {
    const result = chatRequestSchema.safeParse({
      messages: [{ role: "bot", content: "Hi" }],
    });
    expect(result.success).toBe(false);
  });

  it("accepts multi-turn conversation history", () => {
    const result = chatRequestSchema.safeParse({
      messages: [
        { role: "user", content: "Hello" },
        { role: "assistant", content: "Hi there" },
        { role: "user", content: "How are you?" },
      ],
    });
    expect(result.success).toBe(true);
    if (result.success) expect(result.data.messages).toHaveLength(3);
  });
});

describe("summariseRequestSchema", () => {
  it("parses valid summarise request", () => {
    const result = summariseRequestSchema.safeParse({ text: "Long article..." });
    expect(result.success).toBe(true);
  });

  it("rejects empty text", () => {
    const result = summariseRequestSchema.safeParse({ text: "" });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues[0].message).toContain("required");
    }
  });

  it("rejects missing text", () => {
    const result = summariseRequestSchema.safeParse({});
    expect(result.success).toBe(false);
  });

  it("accepts optional model", () => {
    const result = summariseRequestSchema.safeParse({
      text: "Some text",
      model: "mistral:latest",
    });
    expect(result.success).toBe(true);
    if (result.success) expect(result.data.model).toBe("mistral:latest");
  });
});

describe("analyseRequestSchema", () => {
  it("parses valid analyse request", () => {
    const result = analyseRequestSchema.safeParse({ text: "Financial data..." });
    expect(result.success).toBe(true);
  });

  it("rejects empty text", () => {
    const result = analyseRequestSchema.safeParse({ text: "" });
    expect(result.success).toBe(false);
  });

  it("accepts optional context", () => {
    const result = analyseRequestSchema.safeParse({
      text: "data",
      context: "background info",
    });
    expect(result.success).toBe(true);
    if (result.success) expect(result.data.context).toBe("background info");
  });

  it("accepts optional model with context", () => {
    const result = analyseRequestSchema.safeParse({
      text: "data",
      context: "background",
      model: "llama3.2:latest",
    });
    expect(result.success).toBe(true);
  });

  it("context is optional — parses without it", () => {
    const result = analyseRequestSchema.safeParse({ text: "data" });
    expect(result.success).toBe(true);
    if (result.success) expect(result.data.context).toBeUndefined();
  });
});

describe("llmSettingsSchema", () => {
  it("parses a fully valid config", () => {
    const result = llmSettingsSchema.safeParse(VALID_SETTINGS);
    expect(result.success).toBe(true);
  });

  it("coerces numeric string inputs (form fields are strings)", () => {
    const result = llmSettingsSchema.safeParse({
      ...VALID_SETTINGS,
      timeout: "90",
      num_parallel: "8",
      route_threshold: "0.5",
      react_max_steps: "10",
    });
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.timeout).toBe(90);
      expect(result.data.num_parallel).toBe(8);
      expect(result.data.route_threshold).toBe(0.5);
      expect(result.data.react_max_steps).toBe(10);
    }
  });

  it("rejects a non-URL base_url", () => {
    const result = llmSettingsSchema.safeParse({ ...VALID_SETTINGS, base_url: "not a url" });
    expect(result.success).toBe(false);
    if (!result.success) expect(result.error.issues[0].path).toContain("base_url");
  });

  it("rejects an empty model name", () => {
    const result = llmSettingsSchema.safeParse({ ...VALID_SETTINGS, main_model: "" });
    expect(result.success).toBe(false);
  });

  it("rejects an unknown route_mode", () => {
    const result = llmSettingsSchema.safeParse({ ...VALID_SETTINGS, route_mode: "magic" });
    expect(result.success).toBe(false);
  });

  it("rejects route_threshold outside 0..1", () => {
    expect(llmSettingsSchema.safeParse({ ...VALID_SETTINGS, route_threshold: 1.5 }).success).toBe(
      false,
    );
    expect(llmSettingsSchema.safeParse({ ...VALID_SETTINGS, route_threshold: -0.1 }).success).toBe(
      false,
    );
  });

  it("rejects a non-integer step count", () => {
    const result = llmSettingsSchema.safeParse({ ...VALID_SETTINGS, react_max_steps: 2.5 });
    expect(result.success).toBe(false);
  });

  it("rejects out-of-range agent caps", () => {
    expect(llmSettingsSchema.safeParse({ ...VALID_SETTINGS, react_max_steps: 21 }).success).toBe(
      false,
    );
    expect(llmSettingsSchema.safeParse({ ...VALID_SETTINGS, plan_max_steps: 0 }).success).toBe(
      false,
    );
  });
});
