"use client";

/**
 * Shared primitives. One chip scale, one card, one icon set -- defined once so
 * per-page copies cannot drift apart.
 */

import type { ReactNode } from "react";

/* ------------------------------------------------------------------ chips -- */

type Tone = "danger" | "warning" | "success" | "neutral" | "accent" | "ai" | "noai";

export function Chip({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`chip chip-${tone}`}>{children}</span>;
}

/** Severity from the API is the source of truth; nothing here is hardcoded. */
export function severityChip(severity?: string | null) {
  const s = (severity ?? "").toUpperCase();
  if (s === "CRITICAL") return <Chip tone="danger">Critical</Chip>;
  if (s === "HIGH") return <Chip tone="danger">At risk</Chip>;
  if (s === "MEDIUM") return <Chip tone="warning">Monitoring</Chip>;
  if (s === "LOW") return <Chip tone="neutral">Low</Chip>;
  return <Chip tone="neutral">{severity ?? "—"}</Chip>;
}

/** match_basis in plain words, never the raw enum. */
export function basisChip(basis?: string | null) {
  if (basis === "SUPPLIER_LANE") return <Chip tone="warning">Supplier lane</Chip>;
  if (basis === "PART_ORIGIN") return <Chip tone="warning">Part origin</Chip>;
  if (basis === "BOTH") return <Chip tone="danger">Lane and origin</Chip>;
  return <Chip tone="neutral">No match</Chip>;
}

/**
 * A factual claim about the pipeline: only the Intelligence agent reads with a
 * model. Everything else is arithmetic, rules or SQL.
 */
export function AiChip({ ai }: { ai: boolean }) {
  return ai ? <Chip tone="ai">AI</Chip> : <Chip tone="noai">no AI</Chip>;
}

/* ------------------------------------------------------------------ cards -- */

export function Card({
  title, aside, children, rows,
}: { title?: string; aside?: ReactNode; children: ReactNode; rows?: boolean }) {
  return (
    <section className="card">
      {title && (
        <header>
          <h2>{title}</h2>
          {aside}
        </header>
      )}
      <div className={rows ? "rows" : "body"}>{children}</div>
    </section>
  );
}

export function Stat({
  label, value, qualifier, tone,
}: { label: string; value: ReactNode; qualifier?: string; tone?: "danger" | "warning" | "success" }) {
  return (
    <div className="stat">
      <div className="l">{label}</div>
      <div className="v mono">{value}</div>
      {qualifier && <div className={`q ${tone ?? ""}`}>{qualifier}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------ icons -- */
/* Stroke-only, 24-grid, 1.75 stroke. No emoji, no icon font, nothing filled. */

const S = {
  fill: "none", stroke: "currentColor", strokeWidth: 1.75,
  strokeLinecap: "round" as const, strokeLinejoin: "round" as const,
};

export function Icon({ name, size = 17 }: { name: string; size?: number }) {
  const p = { width: size, height: size, viewBox: "0 0 24 24", ...S };
  switch (name) {
    case "overview":
      return <svg {...p}><rect x="3" y="3" width="7" height="8" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="11" width="7" height="10" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /></svg>;
    case "events":
      return <svg {...p}><path d="M4 6h16M4 12h16M4 18h10" /><circle cx="19" cy="18" r="2" /></svg>;
    case "shortages":
      return <svg {...p}><path d="M12 4v9M12 17v.5" /><path d="M10.3 3.1 2.6 17a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 3.1a2 2 0 0 0-3.4 0Z" /></svg>;
    case "recommendations":
      return <svg {...p}><path d="M5 4h11l4 4v12a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Z" /><path d="M15 4v5h5M9 14l2 2 4-4" /></svg>;
    case "suppliers":
      return <svg {...p}><path d="M3 9h18M3 9l2-5h14l2 5M5 9v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9" /><path d="M9 14h6" /></svg>;
    case "bom":
      return <svg {...p}><path d="M12 3v12M12 15l-4-4M12 15l4-4" /><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" /></svg>;
    case "ask":
      return <svg {...p}><path d="M21 12a8 8 0 0 1-8 8H8l-4 3v-5.5A8 8 0 1 1 21 12Z" /><path d="M9 10h6M9 14h4" /></svg>;
    case "runs":
      return <svg {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3.5 2" /></svg>;
    case "alert":
      return <svg {...p} width={22} height={22}><path d="M12 8v5M12 16.5v.5" /><circle cx="12" cy="12" r="9" /></svg>;
    case "ok":
      return <svg {...p} width={22} height={22}><circle cx="12" cy="12" r="9" /><path d="m8.5 12 2.5 2.5 4.5-5" /></svg>;
    case "chev":
      return <svg {...p} width={14} height={14}><path d="m9 5 7 7-7 7" /></svg>;
    case "back":
      return <svg {...p} width={14} height={14}><path d="m15 5-7 7 7 7" /></svg>;
    case "tick":
      return <svg {...p} width={12} height={12} strokeWidth={2.4}><path d="m5 12 4.5 4.5L19 7" /></svg>;
    case "layer":
      return (
        <svg {...p} width={26} height={26}>
          <path d="M12 3 3 7.5 12 12l9-4.5L12 3Z" />
          <path d="m3 14.5 9 4.5 9-4.5" opacity=".55" />
        </svg>
      );
    default:
      return null;
  }
}

/* ------------------------------------------------------------- formatting -- */

export const money = (n?: number | null) =>
  n == null ? "—" : n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 });

export const num = (n?: number | null) => (n == null ? "—" : n.toLocaleString("en-US"));

/** "2026-10-15" -> "15 October". Raw log panels and raw-data cells keep ISO. */
export const day = (iso?: string | null) => {
  if (!iso) return "—";
  const d = new Date(`${String(iso).slice(0, 10)}T00:00:00`);
  return Number.isNaN(d.getTime())
    ? String(iso)
    : d.toLocaleDateString("en-GB", { day: "numeric", month: "long" });
};

export const ago = (iso?: string | null) => {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  const days = Math.round((Date.now() - then) / 86_400_000);
  if (Number.isNaN(days)) return "";
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  return day(iso);
};

/**
 * Plain-English first, part number second -- everywhere a component appears.
 * Derived from the catalogue category, so a new part gets a sensible name
 * without anyone maintaining a list of MPNs.
 */
const BY_CATEGORY: Record<string, string> = {
  MCU: "controller chip",
  GATE_DRIVER: "motor gate driver",
  MOSFET: "power switching transistor",
  REGULATOR_BUCK: "step-down power converter",
  REGULATOR_LDO: "voltage regulator",
  CAN_TRANSCEIVER: "CAN bus transceiver",
  FLASH_SPI: "memory chip",
  MODULE_WIFI: "Wi-Fi module",
  ETHERNET_PHY: "ethernet controller",
  CRYSTAL: "timing crystal",
  ESD_PROTECTION: "surge protection diode",
  CAPACITOR_MLCC: "ceramic capacitor",
  RESISTOR: "resistor",
  INDUCTOR: "power inductor",
  CONNECTOR: "board connector",
  TVS_DIODE: "protection diode",
};

export function plainName(category?: string | null, boards?: string[] | null) {
  const base = BY_CATEGORY[(category ?? "").toUpperCase()] ?? "part";
  if (!boards?.length) return `the ${base}`;
  if (boards.length === 1) return `the ${base} in your ${boards[0]} board`;
  return `the ${base} in your ${boards.slice(0, 2).join(" and ")} boards`;
}

/**
 * The everyday noun for a category, with no article -- "controller chips".
 *
 * plainName() returns "the controller chip", which reads well mid-sentence but
 * not after a number. This is the countable form.
 */
export function partWord(category?: string | null, qty = 1) {
  const base = BY_CATEGORY[(category ?? "").toUpperCase()] ?? "part";
  return qty === 1 ? base : `${base}s`;
}

/**
 * Days between the last delivery landing and the date we need the parts.
 *
 * Positive means the plan lands early, which is the whole point of showing it:
 * a reader should be able to tell a working plan from a doomed one without
 * subtracting two dates in their head.
 */
export const slackDays = (needBy?: string | null, arrival?: string | null) => {
  if (!needBy || !arrival) return null;
  const ms = new Date(needBy).getTime() - new Date(arrival).getTime();
  return Math.round(ms / 86_400_000);
};
