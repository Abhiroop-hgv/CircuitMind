"use client";

/**
 * Events feed.
 *
 * Not in the design spec — flagged, and built because the sidebar links here.
 * The point of the view is the rejections: six of seven events are correctly
 * ignored, and the reason for each is the evidence that the system
 * discriminates rather than reacting to everything.
 */

import { useEffect, useState } from "react";

import { getJSON, type EventRow, type ImpactRow } from "@/lib/api";
import { Shell } from "@/components/Shell";
import { Card, Chip, ago, basisChip, num } from "@/components/ui";

export default function EventsPage() {
  const [events, setEvents] = useState<EventRow[] | null>(null);
  const [impacts, setImpacts] = useState<ImpactRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      getJSON<EventRow[]>("/api/events"),
      getJSON<ImpactRow[]>("/api/impacts"),
    ])
      .then(([e, i]) => { setEvents(e); setImpacts(i); })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const matched = events?.filter((e) => e.status === "ANALYZED") ?? [];

  return (
    <Shell
      title="Events"
      right={events ? (
        <span className="note">
          {matched.length} of {events.length} matched something we buy
        </span>
      ) : undefined}
    >
      {error && <div className="callout bad">{error}</div>}

      <Card title="External feed" rows>
        {events === null && <div className="body"><div className="skel" style={{ height: 40 }} /></div>}
        {events?.map((e) => {
          const hits = impacts.filter((i) => i.external_id === e.external_id);
          const worst = hits.find((h) => h.risk_level === "HIGH") ?? hits[0];
          return (
            <div className="item" key={e.id}>
              <div style={{ paddingTop: 2, minWidth: 128 }}>
                {worst ? basisChip(worst.match_basis) : <Chip tone="neutral">No match</Chip>}
              </div>
              <div className="main">
                <div className="t">{e.headline}</div>
                <div className="s">
                  {hits.length > 0
                    ? `${hits.length} part(s) touched · ${hits.map((h) => h.mpn).join(", ")}`
                    : e.skipped_reason ?? "not analysed yet"}
                </div>
              </div>
              <div className="end">
                <div className="b">{e.event_type ?? "—"}</div>
                <div className="s">{ago(e.published_at)}</div>
              </div>
            </div>
          );
        })}
      </Card>

      {impacts.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <Card title="What was touched">
            <div className="scroll">
              <table>
                <thead>
                  <tr>
                    <th>part</th><th>risk</th><th>matched on</th>
                    <th className="num">in transit</th><th>rule</th>
                  </tr>
                </thead>
                <tbody>
                  {impacts.map((i) => (
                    <tr key={i.id} className={i.risk_level === "LOW" ? "mute" : undefined}>
                      <td className="mono">{i.mpn}</td>
                      <td>
                        {i.risk_level === "HIGH"
                          ? <Chip tone="danger">At risk</Chip>
                          : i.risk_level === "MEDIUM"
                            ? <Chip tone="warning">Monitoring</Chip>
                            : <Chip tone="neutral">Low</Chip>}
                      </td>
                      <td>{basisChip(i.match_basis)}</td>
                      <td className="num mono">{num(i.at_risk_qty)}</td>
                      <td style={{ color: "var(--text-3)" }}>
                        {String((i.rule_inputs as { rule?: string })?.rule ?? "")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}
    </Shell>
  );
}
