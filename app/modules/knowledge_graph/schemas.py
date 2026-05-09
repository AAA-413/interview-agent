from typing import Any

from pydantic import BaseModel, Field


class EntityDTO(BaseModel):
    id: int
    name: str
    entity_type: str
    description: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    mention_count: int = 1


class TripleDTO(BaseModel):
    id: int
    subject: EntityDTO
    predicate: str
    object: EntityDTO
    confidence: float = 1.0
    source_kb_id: int | None = None


class GraphNodeDTO(BaseModel):
    id: str
    label: str
    type: str
    size: int = 1
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdgeDTO(BaseModel):
    source: str
    target: str
    relation: str
    confidence: float = 1.0


class GraphStatsDTO(BaseModel):
    entity_count: int = 0
    triple_count: int = 0
    type_distribution: dict[str, int] = Field(default_factory=dict)


class GraphDataDTO(BaseModel):
    nodes: list[GraphNodeDTO] = Field(default_factory=list)
    edges: list[GraphEdgeDTO] = Field(default_factory=list)
    stats: GraphStatsDTO = Field(default_factory=GraphStatsDTO)


class CreateTripleRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=200)
    predicate: str = Field(..., min_length=1, max_length=100)
    object: str = Field(..., min_length=1, max_length=200)
    subject_type: str = Field(default="技术", max_length=50)
    object_type: str = Field(default="技术", max_length=50)
    source_kb_id: int | None = None


class ExtractResultDTO(BaseModel):
    kb_id: int
    entity_count: int
    triple_count: int
    duration_ms: int


class EntityDetailDTO(BaseModel):
    entity: EntityDTO
    related_triples: list[TripleDTO] = Field(default_factory=list)
