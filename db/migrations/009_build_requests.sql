-- ============================================================================
--  A BOM arriving as a document, rather than an event arriving as news.
--
--  Same destination: platform.shortages, which agents 4 and 5 already consume.
--  A shortage can now originate from either side, so shortages carries both
--  foreign keys and exactly one of them is set.
--
--  build_request_lines keeps the RAW parsed text next to the resolved
--  component. When a part number fails to match, the thing a buyer needs to see
--  is what the document actually said -- not a blank.
-- ============================================================================

CREATE TABLE IF NOT EXISTS platform.build_requests (
    id              INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_filename TEXT NOT NULL,
    product_sku     TEXT NOT NULL,
    product_name    TEXT NOT NULL,
    build_qty       INT  NOT NULL,
    need_by         DATE NOT NULL,

    -- Set once the board is registered into the ERP mirror as a real product.
    product_id      INT REFERENCES erp.products(id),

    status          TEXT NOT NULL DEFAULT 'PARSED',  -- PARSED | REGISTERED | BLOCKED
    lines_total     INT  NOT NULL DEFAULT 0,
    lines_resolved  INT  NOT NULL DEFAULT 0,
    lines_unknown   INT  NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS platform.build_request_lines (
    id                   INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id           INT NOT NULL REFERENCES platform.build_requests(id) ON DELETE CASCADE,
    line_number          INT NOT NULL,
    reference_designator TEXT NOT NULL DEFAULT '',
    mpn_raw              TEXT NOT NULL,          -- exactly what the document said
    description          TEXT NOT NULL DEFAULT '',
    quantity_per_board   INT  NOT NULL DEFAULT 1,

    component_id         INT REFERENCES erp.components(id),
    resolution           TEXT NOT NULL,          -- EXACT | NORMALISED | UNKNOWN
    note                 TEXT NOT NULL DEFAULT '',

    UNIQUE (request_id, line_number)
);

CREATE INDEX IF NOT EXISTS build_request_lines_req_idx
    ON platform.build_request_lines (request_id);

-- A shortage now has two possible origins.
ALTER TABLE platform.shortages
    ADD COLUMN IF NOT EXISTS build_request_id INT REFERENCES platform.build_requests(id) ON DELETE CASCADE;

-- The old UNIQUE (event_id, component_id) does not constrain build-request rows,
-- because NULLs are distinct in Postgres unique constraints. Add the matching
-- partial index so a rerun updates a row instead of duplicating it.
CREATE UNIQUE INDEX IF NOT EXISTS shortages_build_component_uidx
    ON platform.shortages (build_request_id, component_id)
    WHERE build_request_id IS NOT NULL;
