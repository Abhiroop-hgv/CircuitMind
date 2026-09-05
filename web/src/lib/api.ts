/**
 * Client for the Python API.
 *
 * The pipeline endpoints stream Server-Sent Events, but they are POSTs with a
 * body, and the browser's EventSource only does GET. So the stream is read off
 * fetch's ReadableStream and the frames parsed here. It is about thirty lines
 * and it means the UI can show each agent finishing rather than freezing for
 * six seconds and then dumping an answer.
 */

export const API = process.env.NEXT_PUBLIC_API ?? "http://127.0.0.1:8000";

export type StageName =
  | "read" | "demand" | "risk" | "component" | "procurement"
  | "parse" | "build";

export interface Frame {
  event: string;
  data: Record<string, unknown>;
}

/** Read an SSE response body, yielding one frame at a time. */
export async function* streamFrames(
  path: string,
  body: BodyInit,
  signal?: AbortSignal,
): AsyncGenerator<Frame> {
  const res = await fetch(`${API}${path}`, { method: "POST", body, signal });
  if (!res.ok || !res.body) {
    throw new Error(`${res.status} ${res.statusText}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // Frames are separated by a blank line.
    let split: number;
    while ((split = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);

      let event = "message";
      const dataLines: string[] = [];
      for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) continue;
      // A finished run rewrites impacts, shortages and recommendations, so
      // nothing cached before it is still true.
      if (event === 'complete') invalidate();
      try {
        yield { event, data: JSON.parse(dataLines.join("\n")) };
      } catch {
        // A malformed frame should not kill the run.
        yield { event: "error", data: { message: "unreadable frame from the server" } };
      }
    }
  }
}

export interface AskCall {
  tool: string;
  arguments: Record<string, unknown>;
  result: unknown;
}

export interface AskAnswer {
  answer: string;
  calls: AskCall[];
  /** Figures in the answer that appear in no tool result. Usually empty. */
  unverified: string[];
}

/**
 * Ask the assistant a question.
 *
 * Deliberately not postJSON: this writes nothing, so it must not clear the
 * read cache, and it is slow enough that it must not be de-duplicated either
 * -- asking the same question twice is a thing a person may legitimately do.
 */
export async function ask(question: string): Promise<AskAnswer> {
  const res = await fetch(`${API}/api/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `${res.status} on /api/ask`);
  }
  return res.json() as Promise<AskAnswer>;
}

/**
 * A failed read, carrying the status.
 *
 * A screen needs to tell "this thing does not exist" apart from "the server is
 * down", and those want different words: one is a dead link the reader can walk
 * back from, the other is a fault they can do nothing about. Matching on the
 * text of a message to decide would break the first time the text changed.
 */
export class HttpError extends Error {
  readonly status: number;
  readonly path: string;

  constructor(status: number, path: string) {
    super(`${status} on ${path}`);
    this.name = "HttpError";
    this.status = status;
    this.path = path;
  }
}

/* ------------------------------------------------- request de-duplication -- */

/**
 * Two GETs for the same thing should be one request.
 *
 * The sidebar reads /api/recommendations for its pending-approval badge on
 * every navigation, and the recommendations page reads the same endpoint for
 * its list -- measured at five calls across four page changes, four of them
 * pure waste. Rather than hoist that state into a provider and have each new
 * screen re-learn the lesson, the fetch layer itself collapses duplicates:
 *
 *   in-flight  a second caller asking while a request is open gets the same
 *              promise instead of a second request
 *   TTL        a repeat within a few seconds is served from memory
 *
 * Anything that writes clears the cache, so a screen never shows a figure the
 * user has just changed. Pass { fresh: true } to bypass both.
 */
const TTL_MS = 8000;

const inflight = new Map<string, Promise<unknown>>();
const cached = new Map<string, { at: number; data: unknown }>();

/** Drop cached reads. Called after every write; exported for manual use. */
export function invalidate(prefix?: string) {
  if (!prefix) { cached.clear(); return; }
  for (const key of [...cached.keys()]) if (key.startsWith(prefix)) cached.delete(key);
}

export async function getJSON<T>(path: string, opts?: { fresh?: boolean }): Promise<T> {
  if (!opts?.fresh) {
    const hit = cached.get(path);
    if (hit && Date.now() - hit.at < TTL_MS) return hit.data as T;

    const open = inflight.get(path);
    if (open) return open as Promise<T>;
  }

  const request = fetch(`${API}${path}`, { cache: "no-store" })
    .then(async (res) => {
      if (!res.ok) throw new HttpError(res.status, path);
      const data = await res.json();
      cached.set(path, { at: Date.now(), data });
      return data;
    })
    .finally(() => inflight.delete(path));

  inflight.set(path, request);
  return request as Promise<T>;
}

export async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `${res.status} on ${path}`);
  }
  invalidate();
  return res.json() as Promise<T>;
}

/* ---------------------------------------------------------------- shapes -- */

export interface Overview {
  watch: {
    mpn: string;
    description: string;
    committed_demand: number;
    usable_stock: number;
    incoming: { ref: string; qty: number; when: string }[];
    expected_supply: number;
    gap: number;
  };
  products: { sku: string; name: string; family: string; lines: number }[];
  feed: { unread: number; total: number };
}

export interface Extraction {
  event_type: string;
  countries: string[];
  categories: string[];
  effective_date: string | null;
  delay_days: number | null;
  confidence: number;
}

export interface Impact {
  mpn: string;
  risk: string;
  boards: string[];
  at_risk_qty: number;
  basis: string;
  rule: string;
}

export interface Shortage {
  mpn: string;
  demand: number;
  usable_stock: number;
  lost: number;
  baseline: number;
  shortage: number;
  severity: string;
  first_short: string;
  ledger: LedgerRow[];
}

export interface LedgerRow {
  date: string; kind: string; ref: string;
  qty: number; balance: number; note: string;
}

export interface Check { name: string; required: string; actual: string; ok: boolean; }

export interface Candidate {
  mpn: string; manufacturer: string; cost: number;
  verdict: string; fit: number; origin: string; note: string; why: string;
  checks: { board: string; verdict: string; checks: Check[] }[];
}

export interface PlanLine {
  supplier: string; mpn: string; quantity: number;
  unit_price: number; total: number; arrival: string; score: number;
}

export interface Considered {
  plan: string; viable: boolean; shortfall: number;
  suppliers: number; total_cost: number; latest_arrival: string | null;
}

export interface BuildLine {
  mpn: string; per_board: number; required: number; stock: number;
  shortage: number; baseline: number; severity: string; first_short: string | null;
}

export const money = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });

export const num = (n: number) => n.toLocaleString("en-US");

/** "2026-10-15" -> "15 October". Nobody reads a shortage date as an ISO string. */
export const day = (iso: string | null | undefined) => {
  if (!iso) return "";
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString("en-GB", { day: "numeric", month: "long" });
};

/* ------------------------------------------------------ list-view shapes -- */

export interface EventRow {
  id: number; external_id: string; source_type: string; headline: string;
  body: string; published_at: string; status: string; is_synthetic: boolean;
  event_type: string | null; skipped_reason: string | null;
}

export interface ShortageRow {
  id: number; mpn: string; demand_qty: number; usable_stock: number;
  expected_supply: number; shortage_qty: number; baseline_shortage_qty: number;
  first_shortfall_date: string | null; severity: string; ledger: LedgerRow[];
  event_id: number | null; build_request_id: number | null;
}

export interface SupplierRow {
  id: number; name: string; country: string; supplier_type: string;
  deliveries: number | null; on_time: number | null; late: number | null;
  score: number | null; avg_days_late: number | null; lead_time_padding: number | null;
}

export interface RecommendationRow {
  id: number; original_mpn: string; category: string; description: string | null;
  qty_required: number; need_by: string;
  /** Null when the recommendation came from a new BOM rather than an event. */
  event_headline: string | null; event_type: string | null;
  strategy: string; rationale: string; requires_bom_change: boolean;
  total_cost: number; latest_arrival: string; status: string;
  approved_by: string | null; considered: Considered[];
  lines: PlanLine[] | null;
}

export interface ImpactRow {
  id: number; external_id: string; mpn: string; category: string;
  risk_level: string; at_risk_qty: number; expected_delay_days: number | null;
  match_basis: string; origin_country: string | null;
  rule_inputs: Record<string, unknown>; explanation: string | null;
}

/* ------------------------------------------ recommendation detail (§4) --- */

export interface RecoDetail {
  recommendation: {
    id: number; original_mpn: string; category: string; description: string;
    qty_required: number; need_by: string; strategy: string; rationale: string;
    requires_bom_change: boolean; total_cost: number; latest_arrival: string;
    status: string; approved_by: string | null; approved_at: string | null;
    considered: Considered[];
  };
  lines: {
    supplier: string; country: string; mpn: string; quantity: number;
    unit_price: number; line_total: number; lead_time_days: number;
    expected_arrival: string; supplier_reliability: number | null;
    on_time: number | null; late: number | null; deliveries: number | null;
    lead_time_padding: number | null;
  }[];
  shortage: {
    demand_qty: number; usable_stock: number; expected_supply: number;
    shortage_qty: number; baseline_shortage_qty: number;
    first_shortfall_date: string; severity: string; ledger: LedgerRow[];
    horizon_start: string; horizon_end: string;
  } | null;
  alternatives: {
    mpn: string; manufacturer: string; standard_cost: number;
    country_of_origin: string; verdict: string; compatibility_score: number;
    rank: number; sourcing_note: string;
    checks: { board: string; verdict: string; checks: Check[] }[];
  }[];
  forecast: {
    period_month: string; committed_qty: number; forecast_qty: number;
    net_demand_qty: number; method: string;
  }[];
  suppliers_considered: {
    id: number; name: string; country: string; score: number | null;
    on_time: number | null; late: number | null; deliveries: number | null;
    avg_days_late: number | null; lead_time_padding: number | null;
    unit_price: number; lead_time_days: number; stock_available: number;
  }[];
  cause: {
    external_id: string; headline: string; published_at: string;
    match_basis: string; origin_country: string | null; risk_level: string;
  } | null;
}

export interface BomPreview {
  filename: string;
  lines: {
    line_number: number; ref: string; mpn_raw: string; matched_mpn: string;
    qty_per_board: number; description: string; resolution: string; note: string;
  }[];
  unknown: string[];
  /** Catalogue candidates for each unmatched line, keyed by line number. */
  suggestions?: Record<string, {
    mpn: string; manufacturer: string; category: string;
    description: string; score: number;
  }[]>;
}

/** The purchase orders an approved recommendation produces, one per supplier. */
export interface PoManifest {
  recommendation_id: number;
  status: string;
  approved_by: string | null;
  orders: {
    po_number: string; supplier_code: string; supplier: string; country: string;
    quantity: number; total: number; promised: string;
  }[];
}
