import { z } from "zod";

export const createNodeSchema = z.object({
  name: z.string().min(1, "Name is required").max(200),
  // Optional "what this concept is NOT" seed; the LLM fills it on the first expansion.
  negative_description: z.string().max(2000).optional(),
});

export type CreateNodeForm = z.infer<typeof createNodeSchema>;

export const startExpansionSchema = z.object({
  max_depth: z.coerce.number().int().min(1).max(5),
  force: z.boolean().optional(),
});

export type StartExpansionForm = z.infer<typeof startExpansionSchema>;
