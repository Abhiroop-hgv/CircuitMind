"use client";

/** Not in the design spec — flagged, built because the sidebar links here. */

import { useEffect, useState } from "react";

import { getJSON, type ShortageRow } from "@/lib/api";
import { Shell } from "@/components/Shell";
import { Card, day, num, plainName, severityChip } from "@/components/ui";

export default function ShortagesPage() {
  const [rows, setRows] = useState<ShortageRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getJSON<ShortageRow[]>("/api/shortages")
      .then(setRows)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const active = rows?.filter((r) => r.shortage_qty > 0) ?? [];

  return (
    <Shell title="Shortages">
      {error && <div className="callout bad">{error}</div>}
      <Card title={`Active shortages${rows ? ` (${active.length})` : ""}`}>
        {rows === null && <div className="skel" style={{ height: 40 }} />}
        {rows && active.length === 0 && (
          <div className="empty">Nothing short. Every committed order is covered.</div>
        )}
        {active.length > 0 && (
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th>part</th><th>severity</th><th className="num">need</th>
                  <th className="num">usable stock</th><th className="num">short</th>
                  <th className="num">was short</th><th>runs out</th><th>source</th>
                </tr>
              </thead>
              <tbody>
                {active.map((s) => (
                  <tr key={s.id}>
                    <td>
                      <div>{plainName(s.category, s.skus)}</div>
                      <div className="note mono">{s.mpn}</div>
                    </td>
                    <td>{severityChip(s.severity)}</td>
                    <td className="num mono">{num(s.demand_qty)}</td>
                    <td className="num mono">{num(s.usable_stock)}</td>
                    <td className="num mono"><b>{num(s.shortage_qty)}</b></td>
                    <td className="num mono" style={{ color: "var(--text-3)" }}>
                      {num(s.baseline_shortage_qty)}
                    </td>
                    <td className="mono">{day(s.first_shortfall_date)}</td>
                    <td className="note">
                      {s.build_request_id ? "new board" : "disruption"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </Shell>
  );
}
