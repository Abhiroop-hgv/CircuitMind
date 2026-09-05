"use client";

/**
 * Non-negotiable constraints, set by a person before the search runs.
 *
 * The component agent already checks every candidate against what each board
 * demands, read from the stored BOM. This adds the other half: what the
 * engineer knows today and the BOM does not. "This revision has to run at
 * 3.3 V." "Nothing fabbed in China." Those are not preferences to be traded
 * against price, which is why they are set before the search rather than
 * applied to its results.
 *
 * Every parameter here maps to a field that actually exists on our parts, and
 * to a rule the existing engine already enforces -- so a constraint is checked
 * by the same code as a board requirement, and a candidate that fails one is
 * rejected with the reason named rather than silently ranked lower.
 *
 * Five is the cap, deliberately. A gate with twelve conditions is not a gate,
 * it is a search that returns nothing, and the person who set it will blame the
 * tool rather than the twelfth condition.
 */

import { useState } from "react";

import { Icon } from "@/components/ui";

export interface Parameter {
  key: string;
  label: string;
  rule: string;
  unit?: string;
  placeholder: string;
  kind: "number" | "text" | "list";
  hint: string;
}

/** Each key is a constraint the rule engine already understands. */
export const PARAMETERS: Parameter[] = [
  { key: "footprint_id", label: "Package / footprint", rule: "EXACT", kind: "text",
    placeholder: "LQFP100_14X14_P050",
    hint: "The land pattern on the board. A different package will not sit on it." },
  { key: "pin_count", label: "Pin count", rule: "EXACT", kind: "number",
    placeholder: "100", hint: "Exact pin count." },
  { key: "rail_voltage_v", label: "Supply rail", rule: "MUST WORK AT", kind: "number",
    unit: "V", placeholder: "3.3",
    hint: "The rail on this board. The part's operating window must contain it." },
  { key: "min_freq_mhz", label: "Clock speed", rule: "AT LEAST", kind: "number",
    unit: "MHz", placeholder: "168", hint: "Rated maximum clock, at least this." },
  { key: "min_flash_kb", label: "Flash", rule: "AT LEAST", kind: "number",
    unit: "kB", placeholder: "1024", hint: "On-chip flash, at least this." },
  { key: "min_ram_kb", label: "RAM", rule: "AT LEAST", kind: "number",
    unit: "kB", placeholder: "192", hint: "On-chip RAM, at least this." },
  { key: "min_io_count", label: "I/O count", rule: "AT LEAST", kind: "number",
    placeholder: "78", hint: "Usable I/O lines, at least this." },
  { key: "ambient_temp_max_c", label: "Ambient temperature, high", rule: "MUST REACH",
    kind: "number", unit: "C", placeholder: "85",
    hint: "The part must be rated to at least this." },
  { key: "ambient_temp_min_c", label: "Ambient temperature, low", rule: "MUST REACH",
    kind: "number", unit: "C", placeholder: "-40",
    hint: "The part must be rated down to at least this." },
  { key: "required_interfaces", label: "Required interfaces", rule: "ALL PRESENT",
    kind: "list", placeholder: "CAN, SPI, USB_OTG",
    hint: "Comma separated. Every one must be present." },
  { key: "manufacturer", label: "Manufacturer", rule: "EXACT", kind: "text",
    placeholder: "STMicroelectronics", hint: "Only parts from this manufacturer." },
  { key: "country_of_origin", label: "Country of origin", rule: "EXACT", kind: "text",
    placeholder: "France", hint: "Only parts fabricated in this country." },
];

const MAX = 5;

export function ConstraintGate({
  open, initial, onCancel, onApply,
}: {
  open: boolean;
  initial: Record<string, string | number | string[]>;
  onCancel: () => void;
  onApply: (constraints: Record<string, string | number | string[]>) => void;
}) {
  const [picked, setPicked] = useState<string[]>(Object.keys(initial));
  const [values, setValues] = useState<Record<string, string>>(
    Object.fromEntries(Object.entries(initial).map(([k, v]) =>
      [k, Array.isArray(v) ? v.join(", ") : String(v)])));

  if (!open) return null;

  function toggle(key: string) {
    setPicked((p) =>
      p.includes(key) ? p.filter((k) => k !== key)
        : p.length >= MAX ? p
        : [...p, key]);
  }

  function apply() {
    const out: Record<string, string | number | string[]> = {};
    for (const key of picked) {
      const raw = (values[key] ?? "").trim();
      if (!raw) continue;                    // set but never filled in: ignore
      const param = PARAMETERS.find((p) => p.key === key)!;
      if (param.kind === "number") {
        const n = Number(raw);
        if (Number.isFinite(n)) out[key] = n;
      } else if (param.kind === "list") {
        const items = raw.split(",").map((x) => x.trim()).filter(Boolean);
        if (items.length) out[key] = items;
      } else {
        out[key] = raw;
      }
    }
    onApply(out);
  }

  const chosen = PARAMETERS.filter((p) => picked.includes(p.key));
  const filled = chosen.filter((p) => (values[p.key] ?? "").trim()).length;

  return (
    <div className="modal-wrap" role="dialog" aria-label="Non-negotiable constraints">
      <div className="modal">
        <header>
          <span className="glyph"><Icon name="shortages" size={19} /></span>
          <div>
            <h2>Non-negotiable constraints</h2>
            <p>Conditions a substitute must satisfy. Set before the search runs.</p>
          </div>
          <span className="count">{picked.length} / {MAX} selected</span>
          <button className="x" onClick={onCancel} aria-label="close">&times;</button>
        </header>

        <section>
          <h3>1. Choose the parameters that cannot be traded</h3>
          <div className="params">
            {PARAMETERS.map((p) => {
              const on = picked.includes(p.key);
              const full = !on && picked.length >= MAX;
              return (
                <button
                  key={p.key}
                  className={`param${on ? " on" : ""}${full ? " full" : ""}`}
                  onClick={() => toggle(p.key)}
                  disabled={full}
                  title={full ? `Five is the maximum. Remove one first.` : p.hint}
                >
                  {on && <Icon name="tick" size={12} />}
                  {p.label}
                  <span className="rule">{p.rule}</span>
                </button>
              );
            })}
          </div>
        </section>

        <section>
          <h3>2. Give each one a value</h3>
          {chosen.length === 0 ? (
            <p className="empty-note">
              Nothing selected. The search will use each board&rsquo;s own design
              constraints, which is the normal case.
            </p>
          ) : (
            <div className="values">
              {chosen.map((p) => (
                <label key={p.key}>
                  <span className="top">
                    {p.label}
                    <span className="rule">{p.rule}</span>
                  </span>
                  <span className="field">
                    <input
                      value={values[p.key] ?? ""}
                      placeholder={p.placeholder}
                      inputMode={p.kind === "number" ? "decimal" : "text"}
                      onChange={(e) =>
                        setValues((v) => ({ ...v, [p.key]: e.target.value }))}
                    />
                    {p.unit && <span className="unit">{p.unit}</span>}
                  </span>
                  <span className="hint">{p.hint}</span>
                </label>
              ))}
            </div>
          )}
        </section>

        <div className="callout warn">
          <b>These are hard limits.</b> A candidate that misses one is rejected
          outright, however close it is otherwise. If nothing passes, that is the
          answer &mdash; the alternative is a substitute that does not fit the board.
        </div>

        <footer>
          <button className="btn sec" onClick={onCancel}>Cancel</button>
          <button className="btn" onClick={apply} disabled={picked.length > 0 && filled === 0}>
            {filled === 0 ? "Continue without constraints"
              : `Apply ${filled} constraint${filled === 1 ? "" : "s"}`}
          </button>
        </footer>
      </div>
    </div>
  );
}

/** "3.3 V rail, ST only" -- for the button that opens this. */
export function describe(constraints: Record<string, string | number | string[]>): string {
  const parts = Object.entries(constraints).map(([k, v]) => {
    const p = PARAMETERS.find((x) => x.key === k);
    const value = Array.isArray(v) ? v.join(", ") : String(v);
    return `${p?.label ?? k} ${value}${p?.unit ? " " + p.unit : ""}`;
  });
  return parts.join(" · ");
}
