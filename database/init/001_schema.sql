CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS complaints (
    id BIGINT PRIMARY KEY,
    date_received DATE NOT NULL,
    product TEXT NOT NULL,
    sub_product TEXT,
    issue TEXT NOT NULL,
    sub_issue TEXT,
    narrative TEXT,
    company TEXT NOT NULL,
    company_public_response TEXT,
    company_response TEXT,
    state VARCHAR(2),
    zip_code VARCHAR(10),
    tags TEXT,
    consumer_consent_provided TEXT,
    submitted_via TEXT,
    date_sent_to_company DATE,
    timely_response BOOLEAN,
    consumer_disputed BOOLEAN,
    source_payload JSONB NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS complaints_date_received_idx ON complaints (date_received DESC);
CREATE INDEX IF NOT EXISTS complaints_product_idx ON complaints (product);
CREATE INDEX IF NOT EXISTS complaints_issue_idx ON complaints (issue);
CREATE INDEX IF NOT EXISTS complaints_company_idx ON complaints (company);
CREATE INDEX IF NOT EXISTS complaints_state_idx ON complaints (state);
CREATE INDEX IF NOT EXISTS complaints_narrative_fts_idx
    ON complaints USING GIN (to_tsvector('english', COALESCE(narrative, '')));

CREATE TABLE IF NOT EXISTS complaint_embeddings (
    complaint_id BIGINT PRIMARY KEY REFERENCES complaints(id) ON DELETE CASCADE,
    embedding_model TEXT NOT NULL,
    embedding VECTOR(1536) NOT NULL,
    embedded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS complaint_embeddings_hnsw_idx
    ON complaint_embeddings USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS policy_documents (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    version TEXT NOT NULL,
    source_path TEXT NOT NULL,
    checksum VARCHAR(64) NOT NULL UNIQUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS policy_chunks (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES policy_documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    heading TEXT,
    embedding_model TEXT,
    embedding VECTOR(1536),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS policy_chunks_fts_idx
    ON policy_chunks USING GIN (to_tsvector('english', content));
CREATE INDEX IF NOT EXISTS policy_chunks_hnsw_idx
    ON policy_chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS cases (
    id UUID PRIMARY KEY,
    source VARCHAR(20) NOT NULL DEFAULT 'manual',
    source_complaint_id BIGINT UNIQUE REFERENCES complaints(id),
    product TEXT NOT NULL,
    issue TEXT,
    narrative TEXT NOT NULL,
    company TEXT,
    state VARCHAR(2),
    status VARCHAR(30) NOT NULL DEFAULT 'new',
    assigned_team TEXT,
    priority VARCHAR(20),
    classification_confidence NUMERIC(5, 4),
    redaction_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS cases_status_idx ON cases (status);
CREATE INDEX IF NOT EXISTS cases_product_idx ON cases (product);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    provider VARCHAR(30) NOT NULL,
    model TEXT,
    classification JSONB,
    recommendation JSONB,
    citations JSONB NOT NULL DEFAULT '[]'::jsonb,
    tool_trace JSONB NOT NULL DEFAULT '[]'::jsonb,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    estimated_cost_usd NUMERIC(12, 6),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS review_actions (
    id BIGSERIAL PRIMARY KEY,
    analysis_run_id UUID NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    action TEXT NOT NULL CHECK (action IN ('approved', 'edited', 'rejected')),
    reviewer TEXT NOT NULL,
    edited_recommendation JSONB,
    notes TEXT,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
