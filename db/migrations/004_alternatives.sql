-- ============================================================================
--  platform.alternatives -- the Component Intelligence Agent's output.
--
--  One row per candidate part considered, PASS and FAIL alike. The failures are
--  kept on purpose: "we checked the STM32F429ZIT6 and rejected it because the
--  footprint is LQFP-144" is a far stronger claim than silently returning one
--  answer, and it is what an engineer will ask about first.
-- ============================================================================

CREATE TABLE IF NOT EXISTS platform.alternatives (
    id                     INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id               INT REFERENCES platform.external_events(id) ON DELETE CASCADE,
    original_component_id  INT NOT NULL REFERENCES erp.components(id),
    candidate_component_id INT NOT NULL REFERENCES erp.components(id),

    verdict                TEXT NOT NULL,   -- PASS | FAIL
    compatibility_score    INT  NOT NULL,   -- share of checks satisfied, 0-100
    rank                   INT  NOT NULL,
    sourcing_note          TEXT,

    -- every check, per board, with required and actual values side by side
    checks                 JSONB NOT NULL DEFAULT '[]'::JSONB,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS alternatives_original_idx
    ON platform.alternatives (original_component_id, rank);
