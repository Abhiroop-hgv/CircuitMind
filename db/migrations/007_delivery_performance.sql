-- ============================================================================
--  Supplier delivery performance.
--
--  A quoted lead time is a promise. What matters is what a supplier actually
--  did, over and over. This adds the one ERP field that lets us measure that
--  -- when the goods really turned up -- and a place to keep the score we
--  derive from it.
--
--  The raw fact lives in the ERP zone (a real ERP records goods receipt).
--  The SCORE lives in the platform zone, because it is our interpretation.
-- ============================================================================

ALTER TABLE erp.purchase_orders
    ADD COLUMN IF NOT EXISTS actual_receipt_date DATE;

CREATE INDEX IF NOT EXISTS po_receipt_idx
    ON erp.purchase_orders (supplier_id, actual_receipt_date);

CREATE TABLE IF NOT EXISTS platform.supplier_scores (
    supplier_id       INT PRIMARY KEY REFERENCES erp.suppliers(id),

    deliveries        INT     NOT NULL,   -- how many closed POs the score rests on
    on_time           INT     NOT NULL,
    late              INT     NOT NULL,

    on_time_rate      NUMERIC(4,3) NOT NULL,  -- plain count, all deliveries equal
    score             NUMERIC(4,3) NOT NULL,  -- recency-weighted: what we rank on
    avg_days_late     NUMERIC(6,2) NOT NULL,  -- across late deliveries only
    worst_days_late   INT     NOT NULL,
    lead_time_padding INT     NOT NULL,       -- days added to a quoted lead time

    history           JSONB   NOT NULL DEFAULT '[]'::JSONB,
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
