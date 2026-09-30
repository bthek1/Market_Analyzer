/** Shapes returned by /api/codegraph/ - the graphify code-knowledge graph.
 *
 * These mirror the NORMALISED backend shape (apps/codegraph/services.py), not graphify's own
 * raw dump. If graphify renames a field, the fix belongs in the backend normaliser. */

/** How graphify derived an edge: EXTRACTED = from the tree-sitter AST (a fact),
 * INFERRED = a heuristic guess. The UI defaults to EXTRACTED only. */
export type EdgeConfidence = "EXTRACTED" | "INFERRED" | "AMBIGUOUS";

/** Top-level slice of the repo, and the graph's colour encoding. */
export type CodeLayer = "backend" | "frontend" | "infra" | "other";

export interface CodeNode {
  id: string;
  label: string;
  file: string;
  /** Graphify's line marker, e.g. "L363". */
  line: string;
  /** Node kind: code / rationale / concept. */
  kind: string;
  layer: CodeLayer;
  module: string;
  community: number | null;
  community_name: string;
  degree: number;
}

export interface CodeEdge {
  source: string;
  target: string;
  relation: string;
  confidence: EdgeConfidence;
  context: string;
  file: string;
  line: string;
  weight: number;
}

export interface CodeGraphStats {
  total_nodes: number;
  total_edges: number;
  matched_nodes: number;
  returned_nodes: number;
  returned_edges: number;
  truncated: boolean;
  limit: number;
}

/** [value, count] pairs, computed over the WHOLE graph so dropdowns stay stable. */
export type Facet = [string, number][];

export interface CodeGraphFacets {
  kinds: Facet;
  layers: Facet;
  modules: Facet;
  relations: Facet;
  confidences: Facet;
}

export interface CodeGraphPayload {
  nodes: CodeNode[];
  edges: CodeEdge[];
  stats: CodeGraphStats;
  facets: CodeGraphFacets;
  built_at_commit: string;
  generated_at: number;
}

export interface CodeGraphNeighbour extends CodeEdge {
  node: Omit<CodeNode, "degree">;
}

export interface CodeNodeDetail extends Omit<CodeNode, "degree"> {
  degree: number;
  incoming: CodeGraphNeighbour[];
  outgoing: CodeGraphNeighbour[];
}

export interface CodeGraphParams {
  kind?: string;
  layer?: string;
  module?: string;
  confidence?: string;
  relation?: string;
  community?: number;
  search?: string;
  path?: string;
  limit?: number;
}
