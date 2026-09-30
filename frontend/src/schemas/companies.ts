import { z } from "zod";

export const companySearchSchema = z.object({
  q: z.string().optional(),
});

export type CompanySearchValues = z.infer<typeof companySearchSchema>;
