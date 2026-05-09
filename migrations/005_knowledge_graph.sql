-- 知识图谱：实体表
CREATE TABLE IF NOT EXISTS kg_entities (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    description TEXT,
    properties_json TEXT,
    mention_count INTEGER DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(name, entity_type)
);

CREATE INDEX IF NOT EXISTS idx_kg_entity_name ON kg_entities(name);
CREATE INDEX IF NOT EXISTS idx_kg_entity_type ON kg_entities(entity_type);

-- 知识图谱：三元组关系表
CREATE TABLE IF NOT EXISTS kg_triples (
    id BIGSERIAL PRIMARY KEY,
    subject_id BIGINT NOT NULL REFERENCES kg_entities(id) ON DELETE CASCADE,
    predicate VARCHAR(100) NOT NULL,
    object_id BIGINT NOT NULL REFERENCES kg_entities(id) ON DELETE CASCADE,
    source_kb_id BIGINT REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    source_chunk_id BIGINT REFERENCES knowledge_chunks(id) ON DELETE SET NULL,
    confidence REAL DEFAULT 1.0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(subject_id, predicate, object_id)
);

CREATE INDEX IF NOT EXISTS idx_kg_triple_subject ON kg_triples(subject_id);
CREATE INDEX IF NOT EXISTS idx_kg_triple_object ON kg_triples(object_id);
CREATE INDEX IF NOT EXISTS idx_kg_triple_predicate ON kg_triples(predicate);
CREATE INDEX IF NOT EXISTS idx_kg_triple_source_kb ON kg_triples(source_kb_id);
