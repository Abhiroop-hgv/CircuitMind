"use client";

/** Not in the design spec — flagged, built because the sidebar links here. */

import { useEffect, useState } from "react";

import { getJSON, type SupplierRow } from "@/lib/api";
import { Shell } from "@/components/Shell";
import { Card, Chip, num } from "@/components/ui";

export default function SuppliersPage() {
  const [rows, setRows] = useState<SupplierRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getJSON<SupplierRow[]>("/api/suppliers")
      .then(setRows)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <Shell
      title="Suppliers"
      right={<span className="note">scored from closed purchase orders</span>}
    >
      {error && <div className="callout bad">{error}</div>}
      <Card title="Delivery record">
        {rows === null && <div className="skel" style={{ height: 40 }} />}
        {rows && (
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th>supplier</th><th>country</th><th>type</th>
                  <th className="num">deliveries</th><th className="num">on time</th>
                  <th className="num">late</th><th className="num">avg days over</th>
                  <th className="num">score</th><th className="num">lead-time padding</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => {
                  const score = s.score;
                  return (
                    <tr key={s.id} className={score == null ? "mute" : undefined}>
                      <td>{s.name}</td>
                      <td>{s.country}</td>
                      <td className="note">{s.supplier_type.toLowerCase()}</td>
                      <td className="num mono">{s.deliveries ?? "—"}</td>
                      <td className="num mono">{s.on_time ?? "—"}</td>
                      <td className="num mono">{s.late ?? "—"}</td>
                      <td className="num mono">
                        {s.avg_days_late ? `${Number(s.avg_days_late).toFixed(1)}d` : "—"}
                      </td>
                      <td className="num">
                        {score == null ? "—"
                          : score >= 0.9 ? <Chip tone="success">{score.toFixed(2)}</Chip>
                          : score >= 0.7 ? <Chip tone="warning">{score.toFixed(2)}</Chip>
                          : <Chip tone="danger">{score.toFixed(2)}</Chip>}
                      </td>
                      <td className="num mono">
                        {s.lead_time_padding ? `+${s.lead_time_padding}d` : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <p className="note" style={{ marginTop: 12, maxWidth: "76ch" }}>
        The score is the recency-weighted share of past orders that arrived by the
        promised date. Padding is added to a supplier&rsquo;s quoted lead time before
        asking whether an order can land in time, so a habitually late supplier can be
        ruled out rather than merely ranked lower. Suppliers with fewer than four
        closed orders are shown unscored rather than given a flattering default.
      </p>
    </Shell>
  );
}
