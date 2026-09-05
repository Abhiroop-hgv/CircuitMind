-- ============================================================================
--  The Procurement Agent's output: a RECOMMENDATION, never an order.
--
--  Nothing in this system places a purchase order. The recommendation sits at
--  PENDING_APPROVAL until a person changes it, and the person who changed it is
--  recorded. Accountability for a five-figure commitment stays with a human,
--  and the schema is built so it cannot quietly not.
-- ============================================================================

CREATE TABLE IF NOT EXISTS platform.purchase_recommendations (
    id                    INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id              INT REFERENCES platform.external_events(id) ON DELETE CASCADE,
    original_component_id INT NOT NULL REFERENCES erp.components(id),

    qty_required          INT  NOT NULL,
    need_by               DATE NOT NULL,

    strategy              TEXT NOT NULL,   -- which plan was recommended, and why
    rationale             TEXT NOT NULL,
    requires_bom_change   BOOLEAN NOT NULL DEFAULT FALSE,

    total_cost            NUMERIC(14,2) NOT NULL,
    latest_arrival        DATE NOT NULL,
    considered            JSONB NOT NULL DEFAULT '[]'::JSONB,  -- the plans not taken

    status                TEXT NOT NULL DEFAULT 'PENDING_APPROVAL',
    approved_by           TEXT,
    approved_at           TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS platform.purchase_recommendation_lines (
    id                 INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recommendation_id  INT NOT NULL REFERENCES platform.purchase_recommendations(id)
                           ON DELETE CASCADE,
    supplier_id        INT NOT NULL REFERENCES erp.suppliers(id),
    component_id       INT NOT NULL REFERENCES erp.components(id),
    quantity           INT NOT NULL,
    unit_price         NUMERIC(12,4) NOT NULL,
    line_total         NUMERIC(14,2) NOT NULL,
    lead_time_days     INT NOT NULL,
    expected_arrival   DATE NOT NULL,
    supplier_reliability NUMERIC(4,3)
);

CREATE INDEX IF NOT EXISTS reco_status_idx ON platform.purchase_recommendations (status);
CREATE INDEX IF NOT EXISTS reco_lines_idx  ON platform.purchase_recommendation_lines (recommendation_id);
