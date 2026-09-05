-- ============================================================================
--  platform.event_impacts -- the Intelligence Agent's output, and the contract
--  with the Supply Risk Agent.
--
--  One row per (event, component). Everything the next agent needs to do its
--  arithmetic is here: which of our POs to treat as at risk, how many units
--  that is, and how long the delay is expected to be. The Supply Risk Agent
--  never re-reads the news article.
-- ============================================================================

CREATE TABLE IF NOT EXISTS platform.event_impacts (
    id                   INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id             INT NOT NULL REFERENCES platform.external_events(id) ON DELETE CASCADE,
    component_id         INT NOT NULL REFERENCES erp.components(id),

    -- who and what the event reaches
    affected_supplier_ids INT[] NOT NULL DEFAULT '{}',
    affected_product_ids  INT[] NOT NULL DEFAULT '{}',
    at_risk_po_ids        INT[] NOT NULL DEFAULT '{}',
    at_risk_qty           INT   NOT NULL DEFAULT 0,
    expected_delay_days   INT,

    -- the verdict, and every number the rule used to reach it
    risk_level           TEXT NOT NULL,       -- HIGH | MEDIUM | LOW
    rule_inputs          JSONB NOT NULL DEFAULT '{}'::JSONB,
    explanation          TEXT,

    -- provenance: which extractor produced the reading behind this row
    extractor            TEXT NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (event_id, component_id)
);

CREATE INDEX IF NOT EXISTS event_impacts_event_idx ON platform.event_impacts (event_id);
CREATE INDEX IF NOT EXISTS event_impacts_risk_idx  ON platform.event_impacts (risk_level);
