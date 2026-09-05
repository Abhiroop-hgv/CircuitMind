-- ============================================================================
--  Why an event reached a component.
--
--  There are two entirely different ways a disruption touches a part, and
--  collapsing them loses the distinction that matters:
--
--    SUPPLIER_LANE  our supplier sits in the affected place, so shipments FROM
--                   THEM are at risk. Goods in transit are the exposure.
--
--    PART_ORIGIN    the part is MADE there, whoever sells it to us. A fab fire
--                   in Japan reaches a Murata capacitor bought through a US
--                   distributor, because buying through Mouser does not move
--                   the fab. Stock on the shelf is fine; REPLENISHMENT is the
--                   exposure.
--
--  They need different arithmetic downstream, so the basis is recorded.
-- ============================================================================

ALTER TABLE platform.event_impacts
    ADD COLUMN IF NOT EXISTS match_basis TEXT NOT NULL DEFAULT 'SUPPLIER_LANE';

ALTER TABLE platform.event_impacts
    ADD COLUMN IF NOT EXISTS origin_country TEXT;
