"use client";

/**
 * A tool's result, rendered for a person rather than for a developer.
 *
 * The "how I got this" panel is the assistant's whole credibility: it shows the
 * number came from a query rather than from the model. But a wall of JSON only
 * proves that to someone who reads JSON, and the person deciding whether to
 * spend $56,960 usually does not.
 *
 * So the same payload is shown twice, and the default is the readable one:
 *
 *   scalars              a two-column table, keys turned into English
 *   lists of objects     a real table, one row each
 *   everything else      left as text
 *
 * The raw JSON stays one click away, because a technical reviewer asking "is
 * that actually what the database returned" deserves a straight answer.
 */

import { useState } from "react";

import { day } from "@/components/ui";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
// Postgres hands back "2026-09-05 15:25:33.178082+05:30". Nobody reading a
// dashboard wants six decimal places of a second.
const ISO_STAMP = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/;

/** "reserved_for_other_jobs" -> "Reserved for other jobs" */
export function label(key: string): string {
  const words = key.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function scalar(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "number") return v.toLocaleString("en-US");
  if (typeof v === "string") {
    if (ISO_DATE.test(v)) return day(v);
    const stamp = ISO_STAMP.exec(v);
    if (stamp) return `${day(stamp[1])}, ${stamp[2]}`;
    return v;
  }
  if (Array.isArray(v)) return v.map(scalar).join(", ");
  return JSON.stringify(v);
}

function isRow(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function Rows({ rows }: { rows: Record<string, unknown>[] }) {
  // Union of keys, in the order they first appear, so a row missing a field
  // still lines up with the others.
  const cols: string[] = [];
  for (const r of rows) for (const k of Object.keys(r)) if (!cols.includes(k)) cols.push(k);

  const shown = rows.slice(0, 12);
  return (
    <>
      <div className="scroll">
        <table>
          <thead>
            <tr>{cols.map((c) => <th key={c}>{label(c)}</th>)}</tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={i}>
                {cols.map((c) => (
                  <td key={c} className={typeof r[c] === "number" ? "num mono" : undefined}>
                    {scalar(r[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > shown.length && (
        <p className="note" style={{ marginTop: 6 }}>
          and {rows.length - shown.length} more — see the raw result
        </p>
      )}
    </>
  );
}

export function ToolResult({ result }: { result: unknown }) {
  const [raw, setRaw] = useState(false);

  if (raw) {
    return (
      <>
        <button className="working" onClick={() => setRaw(false)}>show as a table</button>
        <pre className="mono">{JSON.stringify(result, null, 2)}</pre>
      </>
    );
  }

  const body = !isRow(result) ? (
    <pre className="mono">{JSON.stringify(result, null, 2)}</pre>
  ) : (
    <>
      {(() => {
        const entries = Object.entries(result);
        const flat = entries.filter(([, v]) => !(Array.isArray(v) && v.some(isRow)));
        const lists = entries.filter(([, v]) => Array.isArray(v) && v.some(isRow)) as
          [string, Record<string, unknown>[]][];

        return (
          <>
            {flat.length > 0 && (
              <table className="pairs">
                <tbody>
                  {flat.map(([k, v]) => (
                    <tr key={k}>
                      <th>{label(k)}</th>
                      <td className={typeof v === "number" ? "num mono" : undefined}>
                        {scalar(v)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {lists.map(([k, rows]) => (
              <div key={k} style={{ marginTop: flat.length ? 10 : 0 }}>
                <span className="listname">{label(k)}</span>
                <Rows rows={rows} />
              </div>
            ))}
          </>
        );
      })()}
    </>
  );

  return (
    <>
      {body}
      <button className="working" onClick={() => setRaw(true)}>show the raw result</button>
    </>
  );
}
