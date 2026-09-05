-- ============================================================================
--  platform.shortages -- the Supply Risk Agent's output.
--
--  One row per (event, component). Stores not just the answer but the whole
--  ledger that produced it, so a buyer can check the arithmetic line by line
--  instead of taking the number on trust. That is the point of doing this step
--  in plain code: it has to be reproducible and inspectable.
-- ============================================================================

CREATE TABLE IF NOT EXISTS platform.shortages (
    id                  INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id            INT REFERENCES platform.external_events(id) ON DELETE CASCADE,
    component_id        INT NOT NULL REFERENCES erp.components(id),

    horizon_start       DATE NOT NULL,
    horizon_end         DATE NOT NULL,

    -- the inputs, kept so the row explains itself
    demand_qty          INT NOT NULL,
    usable_stock        INT NOT NULL,
    incoming_on_time    INT NOT NULL,   -- POs the disruption does not touch
    incoming_delayed    INT NOT NULL,   -- POs pushed out, and whether they still land
    incoming_lost       INT NOT NULL,   -- delayed past the horizon: no longer counts
    expected_supply     INT NOT NULL,

    -- the answer
    shortage_qty        INT NOT NULL,   -- peak deficit: the quantity to go and buy
    first_shortfall_date DATE,          -- the day stock first goes negative
    severity            TEXT NOT NULL,  -- NONE | MEDIUM | HIGH | CRITICAL

    -- the same numbers with the disruption ignored, so the row shows what the
    -- event actually changed rather than just where we ended up
    baseline_shortage_qty INT NOT NULL,

    ledger              JSONB NOT NULL DEFAULT '[]'::JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (event_id, component_id)
);

CREATE INDEX IF NOT EXISTS shortages_component_idx ON platform.shortages (component_id);
CREATE INDEX IF NOT EXISTS shortages_severity_idx  ON platform.shortages (severity);
