import type { CodeGraphParams, CodeGraphPayload, CodeNodeDetail } from "@/types/codegraph";
import { apiClient } from "./client";

/** Raised when the graph artefact has not been built yet (backend 404 with a hint).
 * This is a NORMAL state - graphify-out/ is gitignored, so a fresh clone always hits it. */
export class CodeGraphNotBuiltError extends Error {
  hint: string;
  constructor(detail: string, hint: string) {
    super(detail);
    this.name = "CodeGraphNotBuiltError";
    this.hint = hint;
  }
}

interface NotBuiltBody {
  detail?: string;
  hint?: string;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function rethrow(error: any): never {
  const status = error?.response?.status;
  if (status === 404) {
    const body: NotBuiltBody = error.response?.data ?? {};
    if (body.hint) {
      throw new CodeGraphNotBuiltError(
        body.detail ?? "The code graph has not been built yet.",
        body.hint
      );
    }
  }
  throw error;
}

export async function getCodeGraph(params?: CodeGraphParams): Promise<CodeGraphPayload> {
  try {
    const { data } = await apiClient.get<CodeGraphPayload>("/api/codegraph/graph/", { params });
    return data;
  } catch (error) {
    rethrow(error);
  }
}

export async function getCodeGraphNode(id: string): Promise<CodeNodeDetail> {
  try {
    const { data } = await apiClient.get<CodeNodeDetail>(
      `/api/codegraph/nodes/${encodeURIComponent(id)}/`
    );
    return data;
  } catch (error) {
    rethrow(error);
  }
}
