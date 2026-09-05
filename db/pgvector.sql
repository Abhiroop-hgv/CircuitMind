-- ============================================================================
--  OPTIONAL -- apply only when building the Component Intelligence Agent.
--
--  Kept out of schema.sql on purpose: pgvector is an extra install on Windows,
--  and nothing before the component-substitution step needs it. Retrieval is
--  a convenience for finding CANDIDATES; the pass/fail decision is made by
--  deterministic rules against erp.bom.design_constraints either way.
--
--  Prerequisite: pgvector installed for this Postgres, or use the
--  pgvector/pgvector:pg16 Docker image (see docker-compose.yml).
--
--    psql -d scip -f db/pgvector.sql
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE erp.components
    ADD COLUMN IF NOT EXISTS spec_embedding vector(384);

-- Build the ANN index only after the column is populated; an index over an
-- empty table is useless and slows the backfill down.
-- CREATE INDEX components_embedding_idx ON erp.components
--     USING hnsw (spec_embedding vector_cosine_ops);
