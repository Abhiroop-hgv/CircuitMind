-- ============================================================================
--  platform.demand_forecasts -- the Demand Forecasting Agent's output.
--
--  Committed and forecast are stored SEPARATELY alongside the net figure, so a
--  planner can see which of the two is driving a month. "10,000" means something
--  different when it is a signed order book than when it is a model's opinion,
--  and collapsing them into one column loses that.
-- ============================================================================

CREATE TABLE IF NOT EXISTS platform.demand_forecasts (
    id              INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    component_id    INT  NOT NULL REFERENCES erp.components(id),
    period_month    DATE NOT NULL,          -- first day of the month
    horizon_start   DATE NOT NULL,          -- which run this belongs to

    committed_qty   INT NOT NULL,           -- real orders, exploded through the BOM
    forecast_qty    INT NOT NULL,           -- Holt-Winters, exploded through the BOM
    net_demand_qty  INT NOT NULL,           -- max of the two: forecast consumption

    method          TEXT NOT NULL,
    drivers         JSONB NOT NULL DEFAULT '{}'::JSONB,   -- which products drive it
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (component_id, period_month, horizon_start)
);

CREATE INDEX IF NOT EXISTS demand_component_idx
    ON platform.demand_forecasts (component_id, horizon_start);
