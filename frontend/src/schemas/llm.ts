import { z } from "zod";

export const messageSchema = z.object({
  role: z.enum(["user", "assistant", "system"]),
  content: z.string().min(1),
});

export const chatRequestSchema = z.object({
  messages: z.array(messageSchema).min(1),
  model: z.string().optional().nullable(),
});

export const summariseRequestSchema = z.object({
  text: z.string().min(1, "Text is required"),
  model: z.string().optional().nullable(),
});

export const analyseRequestSchema = z.object({
  text: z.string().min(1, "Text is required"),
  context: z.string().optional().nullable(),
  model: z.string().optional().nullable(),
});

export const llmSettingsSchema = z.object({
  base_url: z.string().url("Must be a valid URL"),
  main_model: z.string().min(1, "Required"),
  classifier_model: z.string().min(1, "Required"),
  embed_model: z.string().min(1, "Required"),
  timeout: z.coerce.number().int().min(1).max(600),
  num_parallel: z.coerce.number().int().min(1).max(32),
  route_mode: z.enum(["llm", "semantic"]),
  route_threshold: z.coerce.number().min(0).max(1),
  react_max_steps: z.coerce.number().int().min(1).max(20),
  eval_max_iterations: z.coerce.number().int().min(1).max(10),
  eval_threshold: z.coerce.number().int().min(1).max(10),
  plan_max_steps: z.coerce.number().int().min(1).max(20),
  plan_max_replans: z.coerce.number().int().min(0).max(10),
  orch_max_workers: z.coerce.number().int().min(2).max(8),
  multiagent_max_tools: z.coerce.number().int().min(1).max(10),
  dag_max_nodes: z.coerce.number().int().min(2).max(12),
  auto_max_cycles: z.coerce.number().int().min(1).max(20),
  auto_max_subagents: z.coerce.number().int().min(0).max(6),
  auto_subagent_steps: z.coerce.number().int().min(1).max(6),
  auto_no_progress: z.coerce.number().int().min(1).max(10),
  // Browser agent (/browse). Mirrors the server-side bounds in LLMSettingsSerializer.
  browser_enabled: z.boolean(),
  browser_provider: z.enum(["anthropic", "ollama"]),
  browser_model: z.string().min(1, "Required"),
  browser_max_steps: z.coerce.number().int().min(1).max(40),
  browser_timeout_s: z.coerce.number().int().min(30).max(1800),
  browser_headless: z.boolean(),
  browser_allowed_domains: z.string(),
});

export type LLMSettingsFormValues = z.infer<typeof llmSettingsSchema>;
