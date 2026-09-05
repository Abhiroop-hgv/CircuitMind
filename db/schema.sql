-- ============================================================================
--  Supply-Chain Intelligence Layer  --  Database Schema
-- ============================================================================
--
--  This database contains TWO logically separate zones, kept in two schemas so
--  the product boundary is visible in the code itself:
--
--    schema "erp"       -> a DUMMY MIRROR of what a real SAP / Oracle / Dynamics
--                          instance would expose to us. Our platform only READS
--                          from here. In production these tables are replaced by
--                          an ERP connector; nothing else in the system changes.
--
--    schema "platform"  -> data that is OURS and does not exist in any ERP:
--                          external world events and (later) agent outputs.
--
--  We are not building an ERP. There is deliberately no order entry, no goods
--  receipt, no invoicing, no accounting, no warehouse execution.
-- ============================================================================

-- pgvector is NOT required to build or run this schema. The embedding column is
-- added separately by db/pgvector.sql, and only when we actually start doing
-- similarity retrieval in the Component Intelligence Agent. Everything up to
-- and including the Supply Risk Agent runs on plain Postgres.

DROP SCHEMA IF EXISTS erp CASCADE;
DROP SCHEMA IF EXISTS platform CASCADE;

CREATE SCHEMA erp;
CREATE SCHEMA platform;

-- ----------------------------------------------------------------------------
-- ERP ZONE (read-only mirror)
-- ----------------------------------------------------------------------------

CREATE TABLE erp.warehouses (
    id       INT PRIMARY KEY,
    code     TEXT UNIQUE NOT NULL,
    name     TEXT NOT NULL,
    country  TEXT NOT NULL
);

CREATE TABLE erp.products (
    id           INT PRIMARY KEY,
    sku          TEXT UNIQUE NOT NULL,
    name         TEXT NOT NULL,
    family       TEXT,
    description  TEXT,
    active       BOOLEAN NOT NULL DEFAULT TRUE
);

-- specs is the deterministic, normalised spec sheet. The Component Intelligence
-- agent uses vector search to RETRIEVE candidates and then checks THESE fields
-- with plain code to DECIDE. Embeddings never decide compatibility.
CREATE TABLE erp.components (
    id                INT PRIMARY KEY,
    mpn               TEXT UNIQUE NOT NULL,
    manufacturer      TEXT NOT NULL,
    category          TEXT NOT NULL,          -- MCU | GATE_DRIVER | MOSFET | REGULATOR | ...
    description       TEXT,
    lifecycle         TEXT NOT NULL DEFAULT 'ACTIVE',   -- ACTIVE | NRND | EOL
    standard_cost     NUMERIC(12,4),
    currency          TEXT NOT NULL DEFAULT 'USD',
    country_of_origin TEXT,                   -- primary fab / assembly country
    specs             JSONB NOT NULL DEFAULT '{}'::JSONB
    -- spec_embedding vector(384) is added later by db/pgvector.sql
);
CREATE INDEX components_specs_idx    ON erp.components USING GIN (specs);
CREATE INDEX components_category_idx ON erp.components (category);

-- design_constraints is what the BOARD requires, which is NOT the same as what
-- the currently fitted part happens to offer. A replacement is judged against
-- the board requirement, not against the incumbent part datasheet.
CREATE TABLE erp.bom (
    id                    INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id            INT NOT NULL REFERENCES erp.products(id),
    component_id          INT NOT NULL REFERENCES erp.components(id),
    qty_per_unit          NUMERIC(12,4) NOT NULL,
    reference_designators TEXT,
    is_critical           BOOLEAN NOT NULL DEFAULT FALSE,
    design_constraints    JSONB NOT NULL DEFAULT '{}'::JSONB,
    UNIQUE (product_id, component_id)
);

CREATE TABLE erp.suppliers (
    id                 INT PRIMARY KEY,
    code               TEXT UNIQUE NOT NULL,
    name               TEXT NOT NULL,
    supplier_type      TEXT NOT NULL,         -- MANUFACTURER | DISTRIBUTOR | CM
    country            TEXT NOT NULL,
    region             TEXT,
    city               TEXT,
    reliability_score  NUMERIC(4,3) NOT NULL DEFAULT 0.900,  -- 0..1 on-time-in-full
    avg_lead_time_days INT NOT NULL DEFAULT 14,
    is_approved        BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX suppliers_country_idx ON erp.suppliers (country);

-- Who can sell us what, at what price, with how much on the shelf.
-- This is the sourcing table the Procurement agent optimises over.
CREATE TABLE erp.supplier_components (
    id               INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    supplier_id      INT NOT NULL REFERENCES erp.suppliers(id),
    component_id     INT NOT NULL REFERENCES erp.components(id),
    supplier_part_no TEXT,
    unit_price       NUMERIC(12,4) NOT NULL,
    currency         TEXT NOT NULL DEFAULT 'USD',
    lead_time_days   INT NOT NULL,
    moq              INT NOT NULL DEFAULT 1,
    stock_available  INT NOT NULL DEFAULT 0,
    is_authorized    BOOLEAN NOT NULL DEFAULT TRUE,
    last_updated     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (supplier_id, component_id)
);

CREATE TABLE erp.inventory (
    id                INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    component_id      INT NOT NULL REFERENCES erp.components(id),
    warehouse_id      INT NOT NULL REFERENCES erp.warehouses(id),
    quantity          INT NOT NULL DEFAULT 0,
    reserved_quantity INT NOT NULL DEFAULT 0,
    safety_stock      INT NOT NULL DEFAULT 0,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (component_id, warehouse_id)
);

CREATE TABLE erp.customer_orders (
    id                      INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_no                TEXT UNIQUE NOT NULL,
    customer_name           TEXT NOT NULL,
    product_id              INT NOT NULL REFERENCES erp.products(id),
    quantity                INT NOT NULL,
    unit_price              NUMERIC(12,2),
    order_date              DATE NOT NULL,
    requested_delivery_date DATE NOT NULL,
    status                  TEXT NOT NULL   -- SHIPPED | CONFIRMED | OPEN
);
CREATE INDEX customer_orders_product_date_idx ON erp.customer_orders (product_id, order_date);
CREATE INDEX customer_orders_delivery_idx     ON erp.customer_orders (requested_delivery_date);

CREATE TABLE erp.production_plans (
    id           INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id   INT NOT NULL REFERENCES erp.products(id),
    planned_qty  INT NOT NULL,
    period_start DATE NOT NULL,
    period_end   DATE NOT NULL,
    status       TEXT NOT NULL DEFAULT 'PLANNED'
);

CREATE TABLE erp.purchase_orders (
    id                INT PRIMARY KEY,
    po_number         TEXT UNIQUE NOT NULL,
    supplier_id       INT NOT NULL REFERENCES erp.suppliers(id),
    status            TEXT NOT NULL,          -- OPEN | PARTIAL | RECEIVED | CANCELLED
    order_date        DATE NOT NULL,
    expected_date     DATE NOT NULL,
    incoterm          TEXT,
    ship_from_country TEXT
);

CREATE TABLE erp.purchase_order_items (
    id           INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    po_id        INT NOT NULL REFERENCES erp.purchase_orders(id) ON DELETE CASCADE,
    component_id INT NOT NULL REFERENCES erp.components(id),
    quantity     INT NOT NULL,
    received_qty INT NOT NULL DEFAULT 0,
    unit_price   NUMERIC(12,4) NOT NULL
);

-- ----------------------------------------------------------------------------
-- PLATFORM ZONE (ours -- does not exist in any ERP)
-- ----------------------------------------------------------------------------

-- Raw external signal, stored exactly as ingested. "extracted" is deliberately
-- left EMPTY by the seed: filling it is the Intelligence Agent job, and we do
-- not want the demo to secretly pre-compute the answer.
CREATE TABLE platform.external_events (
    id           INT PRIMARY KEY,
    external_id  TEXT UNIQUE,
    source       TEXT NOT NULL,
    source_type  TEXT NOT NULL,               -- NEWS | GOVERNMENT | REGULATORY | RSS
    is_synthetic BOOLEAN NOT NULL DEFAULT FALSE,
    headline     TEXT NOT NULL,
    body         TEXT,
    url          TEXT,
    published_at TIMESTAMPTZ NOT NULL,
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status       TEXT NOT NULL DEFAULT 'NEW', -- NEW | ANALYZED | IGNORED
    extracted    JSONB NOT NULL DEFAULT '{}'::JSONB
);
CREATE INDEX external_events_published_idx ON platform.external_events (published_at DESC);

-- ----------------------------------------------------------------------------
-- Helper view: net available stock. Used by the Supply Risk agent so the
-- "what do we actually have" arithmetic lives in ONE place.
-- ----------------------------------------------------------------------------
CREATE VIEW platform.v_stock_position AS
SELECT c.id AS component_id,
       c.mpn,
       COALESCE(SUM(i.quantity), 0)          AS on_hand,
       COALESCE(SUM(i.reserved_quantity), 0) AS reserved,
       COALESCE(SUM(i.safety_stock), 0)      AS safety_stock,
       COALESCE(SUM(i.quantity - i.reserved_quantity - i.safety_stock), 0) AS available
FROM erp.components c
LEFT JOIN erp.inventory i ON i.component_id = c.id
GROUP BY c.id, c.mpn;
