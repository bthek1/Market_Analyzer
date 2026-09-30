export type Relation = "has_subfield" | "prerequisite_for";

export interface Concept {
  id: string;
  name: string;
  slug: string;
  description: string;
  /** A one-line "what this concept is NOT" - the contrast signal shown as "Not to be confused with". */
  negative_description: string;
  times_expanded: number;
  connections: number;
  /**
   * Recursive structural reach: the number of distinct concepts reachable by following
   * `has_subfield` / `prerequisite_for` edges transitively (subfields + everything this concept
   * is a prerequisite for). The graph colours/scales nodes by this. Only the subgraph endpoint
   * populates it; the list/detail endpoints leave it null.
   */
  reach?: number | null;
  created_at: string;
}

export interface ConceptRef {
  id: string;
  name: string;
  slug: string;
}

export interface ConceptEdge {
  id: string;
  source: ConceptRef;
  target: ConceptRef;
  relation: Relation;
  weight: number;
  times_seen: number;
}

export interface ConceptDetail extends Concept {
  outgoing: ConceptEdge[];
  incoming: ConceptEdge[];
}

export interface GraphPayload {
  nodes: Concept[];
  edges: ConceptEdge[];
}

export interface StartExpansionPayload {
  max_depth?: number;
  force?: boolean;
}
