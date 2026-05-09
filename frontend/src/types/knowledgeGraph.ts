export interface GraphNodeDTO {
  id: string;
  label: string;
  type: string;
  size: number;
  properties: Record<string, unknown>;
}

export interface GraphEdgeDTO {
  source: string;
  target: string;
  relation: string;
  confidence: number;
}

export interface GraphStatsDTO {
  entity_count: number;
  triple_count: number;
  type_distribution: Record<string, number>;
}

export interface GraphDataDTO {
  nodes: GraphNodeDTO[];
  edges: GraphEdgeDTO[];
  stats: GraphStatsDTO;
}

export interface EntityDTO {
  id: number;
  name: string;
  entity_type: string;
  description: string | null;
  properties: Record<string, unknown>;
  mention_count: number;
}

export interface TripleDTO {
  id: number;
  subject: EntityDTO;
  predicate: string;
  object: EntityDTO;
  confidence: number;
  source_kb_id: number | null;
}

export interface EntityDetailDTO {
  entity: EntityDTO;
  related_triples: TripleDTO[];
}

export interface CreateTripleRequest {
  subject: string;
  predicate: string;
  object: string;
  subject_type?: string;
  object_type?: string;
  source_kb_id?: number;
}
