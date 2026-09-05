"""
The tools the assistant is allowed to use.

Every one of these is a SELECT. The assistant can read the company's position
and run analysis that already exists; it cannot write, approve, or order. That
is deliberate and it is the reason the whole idea is safe to demo: the model
chooses WHICH question to ask, and this module answers it from the database.

The division of labour, stated once because it is the point:

    the model decides    "they want stock for the STM32, call stock_position"
    this module answers  6,000, read from v_stock_position

So the model never has to know a number, and therefore never has to guess one.
If a tool has no answer it says so, and the assistant is told to repeat that
rather than fill the gap.

Tools take a part as free text -- "STM32F407", "the controller chip" -- and
resolve it here rather than making the model chain two calls. Ambiguity comes
back as a list of candidates, which the model can put to the user.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

# --------------------------------------------------------------- resolving --

# The everyday words people use for these parts. The dashboard already turns a
# category into plain English for the reader; this turns plain English back
# into a category, so "how much of the controller chip is left" resolves. Kept
# in step with BY_CATEGORY in web/src/components/ui.tsx.
CATEGORY_WORDS = {
    "controller chip": "MCU", "controller": "MCU", "microcontroller": "MCU",
    "mcu": "MCU",
    "motor gate driver": "GATE_DRIVER", "gate driver": "GATE_DRIVER",
    "power switching transistor": "MOSFET", "mosfet": "MOSFET",
    "step-down power converter": "REGULATOR_BUCK", "buck": "REGULATOR_BUCK",
    "voltage regulator": "REGULATOR_LDO", "ldo": "REGULATOR_LDO",
    "can bus transceiver": "CAN_TRANSCEIVER", "can transceiver": "CAN_TRANSCEIVER",
    "memory chip": "FLASH_SPI", "flash": "FLASH_SPI",
    "wi-fi module": "MODULE_WIFI", "wifi module": "MODULE_WIFI",
    "ethernet controller": "ETHERNET_PHY",
    "timing crystal": "CRYSTAL", "crystal": "CRYSTAL",
    "surge protection diode": "ESD_PROTECTION",
    "ceramic capacitor": "CAPACITOR_MLCC", "capacitor": "CAPACITOR_MLCC",
    "resistor": "RESISTOR",
    "power inductor": "INDUCTOR", "inductor": "INDUCTOR",
}



def _resolve(conn, part: str) -> Dict:
    """
    Free text to one component.

    Exact MPN first, then a prefix, then a word search over description and
    category. Returns either {"id": ...} or {"error": ..., "candidates": [...]}
    so every caller can handle a miss the same way.
    """
    text = (part or "").strip()
    if not text:
        return {"error": "no part given"}

    with conn.cursor() as cur:
        cur.execute("""SELECT id, mpn, description, category, country_of_origin
                         FROM erp.components
                        WHERE UPPER(mpn) = UPPER(%s)""", (text,))
        hit = cur.fetchone()
        if hit:
            return _component(hit)

        # An everyday phrase rather than a part number.
        category = CATEGORY_WORDS.get(text.lower().strip())
        if category:
            cur.execute("""SELECT id, mpn, description, category, country_of_origin
                             FROM erp.components
                            WHERE category = %s
                            ORDER BY mpn
                            LIMIT 10""", (category,))
            rows = cur.fetchall()
            if len(rows) == 1:
                return _component(rows[0])
            if rows:
                return {"error": f"{text!r} means category {category}, which covers "
                                 f"{len(rows)} parts -- ask which one",
                        "candidates": [_component(r) for r in rows]}

        # Prefix, then any word of the query against the free-text columns.
        cur.execute("""SELECT id, mpn, description, category, country_of_origin
                         FROM erp.components
                        WHERE UPPER(mpn) LIKE UPPER(%s) || '%%'
                        ORDER BY mpn
                        LIMIT 10""", (text,))
        rows = cur.fetchall()

        if not rows:
            cur.execute("""SELECT id, mpn, description, category, country_of_origin
                             FROM erp.components
                            WHERE to_tsvector('english',
                                    mpn || ' ' || COALESCE(description, '') || ' ' || category)
                                  @@ plainto_tsquery('english', %s)
                            ORDER BY mpn
                            LIMIT 10""", (text,))
            rows = cur.fetchall()

    if not rows:
        return {"error": f"no part matches {text!r}"}
    if len(rows) == 1:
        return _component(rows[0])
    return {
        "error": f"{text!r} matches {len(rows)} parts -- ask which one",
        "candidates": [_component(r) for r in rows],
    }


def _component(row) -> Dict:
    return {"id": row[0], "mpn": row[1], "description": row[2],
            "category": row[3], "country_of_origin": row[4]}


# ------------------------------------------------------------------ tools --


def find_component(conn, part: str) -> Dict:
    """Look a part up by number, description or category."""
    return _resolve(conn, part)


def stock_position(conn, part: str) -> Dict:
    """How much of a part is left, and how much of that is genuinely spendable."""
    c = _resolve(conn, part)
    if "id" not in c:
        return c

    with conn.cursor() as cur:
        cur.execute("""SELECT on_hand, reserved, safety_stock, available
                         FROM platform.v_stock_position
                        WHERE component_id = %s""", (c["id"],))
        row = cur.fetchone()

    if not row:
        return {"part": c["mpn"], "error": "no inventory record for this part"}

    on_hand, reserved, safety, usable = (int(v) for v in row)
    return {
        "part": c["mpn"],
        "description": c["description"],
        "on_hand": on_hand,
        "reserved_for_other_jobs": reserved,
        "safety_stock": safety,
        "usable_now": usable,
        "how_usable_is_derived": (
            f"{on_hand} on hand - {reserved} reserved - {safety} safety = {usable}"
        ),
    }


def demand_forecast(conn, part: str, month: Optional[str] = None) -> Dict:
    """
    What we expect to need, month by month.

    Each month carries two numbers that overlap: orders customers have placed,
    and what the statistical forecast expects. The planner uses whichever is
    larger, because adding them would count the same customer twice.
    """
    c = _resolve(conn, part)
    if "id" not in c:
        return c

    with conn.cursor() as cur:
        cur.execute("""SELECT period_month, committed_qty, forecast_qty,
                              net_demand_qty, method
                         FROM platform.demand_forecasts
                        WHERE component_id = %s
                        ORDER BY period_month""", (c["id"],))
        rows = cur.fetchall()

    if not rows:
        return {"part": c["mpn"], "error": "no forecast has been run for this part"}

    # People say "September"; the model sometimes passes it through verbatim
    # rather than as 2026-09. Filtering here rather than in SQL means both
    # spellings work, and an unmatched month can say which months DO exist
    # instead of implying no forecast was ever run.
    if month:
        want = month.strip().lower()
        matched = [r for r in rows
                   if want in (r[0].strftime("%Y-%m"),
                               r[0].strftime("%B").lower(),
                               r[0].strftime("%b").lower(),
                               r[0].strftime("%B %Y").lower())]
        if not matched:
            return {"part": c["mpn"],
                    "error": f"no forecast covers {month!r}",
                    "months_available": [r[0].strftime("%Y-%m") for r in rows]}
        rows = matched

    months = []
    for period, committed, forecast, net, method in rows:
        committed, forecast, net = int(committed), int(forecast), int(net)
        months.append({
            "month": period.strftime("%Y-%m"),
            "already_ordered": committed,
            "forecast": forecast,
            "planned_for": max(committed, forecast),
            "which_led": "order book" if committed >= forecast else "forecast",
            "extra_reserved_beyond_orders": net,
        })

    return {
        "part": c["mpn"],
        "method": rows[0][4],
        "months": months,
        "total_planned": sum(m["planned_for"] for m in months),
        "rule": "the larger of committed and forecast is used, never the sum",
    }


def events_affecting_inventory(conn, risk: Optional[str] = None) -> Dict:
    """
    Which news we have analysed actually touches parts this company holds.

    Not a search over headlines -- these are events already matched to our own
    components, with the quantity exposed. An event that matched nothing we buy
    does not appear, which is the point.
    """
    sql = """SELECT e.headline, e.published_at::date, c.mpn, c.description,
                    i.risk_level, i.at_risk_qty, i.expected_delay_days,
                    i.match_basis, i.origin_country, i.explanation
               FROM platform.event_impacts i
               JOIN erp.components c        ON c.id = i.component_id
               JOIN platform.external_events e ON e.id = i.event_id"""
    args: List = []
    if risk:
        sql += " WHERE i.risk_level = UPPER(%s)"
        args.append(risk.strip())
    sql += """ ORDER BY CASE i.risk_level WHEN 'HIGH' THEN 1
                                          WHEN 'MEDIUM' THEN 2 ELSE 3 END,
                        i.at_risk_qty DESC"""

    with conn.cursor() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()

    if not rows:
        # These are different facts and must not share a message. "No HIGH-risk
        # event" while three MEDIUM ones exist is not "nothing touches us", and
        # a model relaying the second would tell the user the opposite of the
        # truth.
        if risk:
            return {"note": f"no analysed event at risk level {risk.strip().upper()}",
                    "filter_applied": risk.strip().upper(),
                    "hint": "ask without a risk filter to see every matched event"}
        return {"note": "no analysed event currently touches a part we hold"}

    return {
        "matches": [{
            "headline": r[0],
            "published": str(r[1]),
            "part": r[2],
            "part_description": r[3],
            "risk": r[4],
            "quantity_exposed": int(r[5]) if r[5] is not None else None,
            "expected_delay_days": r[6],
            "matched_because": r[7],
            "origin_country": r[8],
            "reasoning": r[9],
        } for r in rows],
        "note": "only events matched to parts this company actually buys are listed",
    }


def stock_ledger(conn, part: str) -> Dict:
    """
    The running balance for a part: when it runs dry, and by how much.

    Read back from the stored analysis rather than recomputed, so the assistant
    and the dashboard can never disagree about the same number.
    """
    c = _resolve(conn, part)
    if "id" not in c:
        return c

    with conn.cursor() as cur:
        cur.execute("""SELECT s.demand_qty, s.usable_stock, s.expected_supply,
                              s.shortage_qty, s.first_shortfall_date, s.severity, s.ledger
                         FROM platform.shortages s
                        WHERE s.component_id = %s
                        ORDER BY s.id DESC
                        LIMIT 1""", (c["id"],))
        row = cur.fetchone()

    if not row:
        return {"part": c["mpn"],
                "error": "no shortage analysis has been run for this part"}

    demand, usable, supply, short, first_date, severity, ledger = row
    late = [m for m in (ledger or []) if m.get("kind") == "OUTSIDE_HORIZON"]

    return {
        "part": c["mpn"],
        "total_needed": int(demand),
        "usable_stock": int(usable),
        "arriving_in_time": int(supply),
        "short_by": int(short),
        "runs_out_on": str(first_date) if first_date else None,
        "severity": severity,
        "deliveries_that_arrive_too_late": [
            {"reference": m.get("ref"), "quantity": m.get("qty"), "arrives": m.get("date")}
            for m in late
        ],
        "movements": ledger,
    }


def list_suppliers(conn, country: Optional[str] = None,
                   supplier_type: Optional[str] = None) -> Dict:
    """Who this company buys from."""
    sql = """SELECT s.name, s.country, s.supplier_type, sc.score, sc.deliveries
               FROM erp.suppliers s
               LEFT JOIN platform.supplier_scores sc ON sc.supplier_id = s.id"""
    where, args = [], []
    if country:
        where.append("UPPER(s.country) = UPPER(%s)")
        args.append(country.strip())
    if supplier_type:
        where.append("UPPER(s.supplier_type) = UPPER(%s)")
        args.append(supplier_type.strip())
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY s.name"

    with conn.cursor() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()

    if not rows:
        return {"error": "no supplier matches that filter"}

    return {
        "count": len(rows),
        "suppliers": [{
            "name": r[0],
            "country": r[1],
            "type": r[2].lower(),
            "on_time_score": float(r[3]) if r[3] is not None else None,
            "deliveries_on_record": int(r[4]) if r[4] is not None else 0,
        } for r in rows],
    }


def supplier_reliability(conn, supplier: Optional[str] = None) -> Dict:
    """
    How well suppliers actually deliver, from their own closed orders.

    Reads the stored scores rather than recomputing them. The dashboard's
    endpoint recalculates on each call, which is a write; this must not write,
    so it reads what the last run left behind and says when that was.

    A supplier with fewer than four closed orders is returned unscored rather
    than given a flattering default -- the same rule the dashboard follows.
    """
    sql = """SELECT s.name, s.country, sc.deliveries, sc.on_time, sc.late,
                    sc.score, sc.avg_days_late, sc.lead_time_padding, sc.computed_at
               FROM erp.suppliers s
               LEFT JOIN platform.supplier_scores sc ON sc.supplier_id = s.id"""
    args: List = []
    if supplier:
        sql += " WHERE s.name ILIKE '%%' || %s || '%%'"
        args.append(supplier.strip())
    sql += " ORDER BY sc.score DESC NULLS LAST, s.name"

    with conn.cursor() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()

    if not rows:
        return {"error": f"no supplier matches {supplier!r}"}

    scored = [{
        "supplier": r[0],
        "country": r[1],
        "deliveries_on_record": int(r[2]) if r[2] is not None else 0,
        "arrived_on_time": int(r[3]) if r[3] is not None else None,
        "arrived_late": int(r[4]) if r[4] is not None else None,
        "on_time_score": float(r[5]) if r[5] is not None else None,
        "average_days_late": float(r[6]) if r[6] is not None else None,
        "lead_time_padding_days": int(r[7]) if r[7] is not None else None,
        "note": None if r[5] is not None else "too few closed orders to score",
    } for r in rows]

    return {
        "suppliers": scored,
        "scored_at": str(rows[0][8]) if rows[0][8] else None,
        "how_the_score_works": (
            "the recency-weighted share of past orders that arrived by the promised "
            "date; padding is added to a supplier's quoted lead time before asking "
            "whether an order can land in time"
        ),
    }


def inventory_overview(conn, country: Optional[str] = None,
                       category: Optional[str] = None) -> Dict:
    """
    Everything held, thinnest first.

    Answers the whole-inventory questions that the per-part tools cannot:
    "what stock do I have", "which parts come from China".

    Two kinds of zero exist here and conflating them makes the answer look
    broken. A part we stock and have run down to nothing is news; a part we
    have never stocked -- the substitution candidates the component agent
    proposes -- is not, and there are nine of those. They are reported
    separately as names only, so "what stock do I have" opens with the parts
    actually held, thinnest first, rather than with a column of zeroes.
    """
    sql = """SELECT c.mpn, c.description, c.category, c.country_of_origin,
                    v.on_hand, v.reserved, v.safety_stock, v.available,
                    EXISTS (SELECT 1 FROM erp.inventory i
                             WHERE i.component_id = c.id) AS stocked
               FROM erp.components c
               JOIN platform.v_stock_position v ON v.component_id = c.id"""
    where, args = [], []
    if country:
        where.append("UPPER(c.country_of_origin) = UPPER(%s)")
        args.append(country.strip())
    if category:
        where.append("UPPER(c.category) = UPPER(%s)")
        args.append(category.strip())
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY v.available ASC, c.mpn"

    with conn.cursor() as cur:
        cur.execute(sql, args)
        rows = cur.fetchall()

    if not rows:
        return {"error": "no part matches that filter"}

    held = [r for r in rows if r[8]]
    not_held = [r for r in rows if not r[8]]

    out: Dict = {
        "parts_in_stock": len(held),
        "parts": [{
            "part": r[0], "description": r[1], "category": r[2],
            "country_of_origin": r[3],
            "on_hand": int(r[4]), "reserved": int(r[5]),
            "safety_stock": int(r[6]), "usable_now": int(r[7]),
        } for r in held],
        "ordered_by": "usable stock, lowest first",
    }
    if not_held:
        out["not_stocked"] = {
            "count": len(not_held),
            "parts": [r[0] for r in not_held],
            "note": "approved alternatives we could buy but do not hold; "
                    "not a shortage",
        }
    return out


def current_shortages(conn) -> Dict:
    """
    Everything short right now, worst first.

    Only rows with a real shortfall are returned; a part that was analysed and
    found to be covered is not a shortage and listing it would pad the answer.
    """
    with conn.cursor() as cur:
        cur.execute("""SELECT c.mpn, c.description, s.demand_qty, s.usable_stock,
                              s.shortage_qty, s.first_shortfall_date, s.severity,
                              s.build_request_id
                         FROM platform.shortages s
                         JOIN erp.components c ON c.id = s.component_id
                        WHERE s.shortage_qty > 0
                        ORDER BY CASE s.severity WHEN 'CRITICAL' THEN 1
                                                 WHEN 'HIGH' THEN 2
                                                 WHEN 'MEDIUM' THEN 3 ELSE 4 END,
                                 s.shortage_qty DESC""")
        rows = cur.fetchall()

    if not rows:
        return {"note": "nothing is short -- every committed order is covered"}

    return {
        "count": len(rows),
        "shortages": [{
            "part": r[0], "description": r[1],
            "total_needed": int(r[2]), "usable_stock": int(r[3]),
            "short_by": int(r[4]),
            "runs_out_on": str(r[5]) if r[5] else None,
            "severity": r[6],
            "raised_by": "a new board" if r[7] else "an external event",
        } for r in rows],
    }


def pending_recommendations(conn) -> Dict:
    """What is waiting on a human decision."""
    with conn.cursor() as cur:
        cur.execute("""SELECT r.id, c.mpn, r.qty_required, r.need_by, r.strategy,
                              r.total_cost, r.latest_arrival, r.requires_bom_change,
                              e.headline
                         FROM platform.purchase_recommendations r
                         JOIN erp.components c ON c.id = r.original_component_id
                         LEFT JOIN platform.external_events e ON e.id = r.event_id
                        WHERE r.status = 'PENDING_APPROVAL'
                        ORDER BY r.need_by""")
        rows = cur.fetchall()

    if not rows:
        return {"note": "nothing is waiting for approval"}

    return {
        "count": len(rows),
        "recommendations": [{
            "id": r[0], "part": r[1], "quantity": int(r[2]),
            "needed_by": str(r[3]), "plan": r[4],
            "cost": float(r[5]), "everything_lands_by": str(r[6]),
            "needs_bom_change": r[7],
            "caused_by": r[8],
        } for r in rows],
        "note": "approval is a human decision made in the dashboard",
    }


# --------------------------------------------------------------- registry --

REGISTRY: Dict[str, Callable] = {
    "find_component": find_component,
    "stock_position": stock_position,
    "demand_forecast": demand_forecast,
    "events_affecting_inventory": events_affecting_inventory,
    "stock_ledger": stock_ledger,
    "list_suppliers": list_suppliers,
    "supplier_reliability": supplier_reliability,
    "inventory_overview": inventory_overview,
    "current_shortages": current_shortages,
    "pending_recommendations": pending_recommendations,
}

_PART = {"type": "string",
         "description": "Part number or description, e.g. 'STM32F407VGT6' or "
                        "'the controller chip'."}

SCHEMAS: List[Dict] = [
    {"type": "function", "function": {
        "name": "find_component",
        "description": "Look up a part by number, description or category. Use this "
                       "when the user names a part vaguely and you need to confirm "
                       "which one they mean.",
        "parameters": {"type": "object",
                       "properties": {"part": _PART},
                       "required": ["part"]}}},

    {"type": "function", "function": {
        "name": "stock_position",
        "description": "How many units of a part are left: on hand, reserved for "
                       "other jobs, safety stock, and how many are genuinely usable "
                       "now. Use for any 'how much is left / do we have' question.",
        "parameters": {"type": "object",
                       "properties": {"part": _PART},
                       "required": ["part"]}}},

    {"type": "function", "function": {
        "name": "demand_forecast",
        "description": "Expected demand for a part by month, showing orders already "
                       "placed, the statistical forecast, and which of the two the "
                       "planner used. Use for any question about a future month.",
        "parameters": {"type": "object",
                       "properties": {
                           "part": _PART,
                           "month": {"type": ["string", "null"],
                                     "description": "Optional month as YYYY-MM, e.g. "
                                                    "'2026-09'. Omit or null for every "
                                                    "month."}},
                       "required": ["part"]}}},

    {"type": "function", "function": {
        "name": "events_affecting_inventory",
        "description": "External events already analysed and matched to parts this "
                       "company actually buys, with the quantity exposed. Use for "
                       "'what news affects my inventory / what should I worry about'.",
        "parameters": {"type": "object",
                       "properties": {
                           "risk": {"type": ["string", "null"],
                                    "description": "Optional risk filter: HIGH, MEDIUM "
                                                   "or LOW. Omit or null for all."}},
                       "required": []}}},

    {"type": "function", "function": {
        "name": "stock_ledger",
        "description": "The running stock balance for a part: the date it runs out, "
                       "how short it ends up, and any delivery that arrives too late "
                       "to help. Use for 'why are we short / when do we run out'.",
        "parameters": {"type": "object",
                       "properties": {"part": _PART},
                       "required": ["part"]}}},
    {"type": "function", "function": {
        "name": "list_suppliers",
        "description": "The suppliers this company buys from, with country and "
                       "whether each is a distributor or a manufacturer. Use for "
                       "'which suppliers do I have / who do we buy from'.",
        "parameters": {"type": "object",
                       "properties": {
                           "country": {"type": ["string", "null"],
                                       "description": "Optional country filter."},
                           "supplier_type": {"type": ["string", "null"],
                                             "description": "Optional: DISTRIBUTOR or "
                                                            "MANUFACTURER."}},
                       "required": []}}},

    {"type": "function", "function": {
        "name": "supplier_reliability",
        "description": "How reliably suppliers deliver, scored from their own closed "
                       "purchase orders: deliveries on record, how many arrived on "
                       "time, average days late, and the padding added to their quoted "
                       "lead time. Use for 'who is reliable / who delivers late'.",
        "parameters": {"type": "object",
                       "properties": {
                           "supplier": {"type": ["string", "null"],
                                        "description": "Optional supplier name or part "
                                                       "of one, e.g. 'Mouser'. Omit for "
                                                       "all suppliers."}},
                       "required": []}}},
    {"type": "function", "function": {
        "name": "inventory_overview",
        "description": "Every part held, with usable stock, lowest first. Optionally "
                       "filtered by country of origin or category. Use for 'what stock "
                       "do I have' or 'which parts come from China'.",
        "parameters": {"type": "object",
                       "properties": {
                           "country": {"type": ["string", "null"],
                                       "description": "Optional country of origin."},
                           "category": {"type": ["string", "null"],
                                        "description": "Optional category, e.g. MCU."}},
                       "required": []}}},

    {"type": "function", "function": {
        "name": "current_shortages",
        "description": "Every part that is short right now, worst first, with the date "
                       "each runs out. Use for 'what am I short of / what is at risk'.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},

    {"type": "function", "function": {
        "name": "pending_recommendations",
        "description": "Purchase recommendations waiting on a human decision. Use for "
                       "'what needs my approval / what is pending'.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
]
