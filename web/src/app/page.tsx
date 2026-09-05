"use client";

/**
 * Overview.
 *
 * Verdict, then numbers, then the two lists. The verdict slot is never empty --
 * when nothing is wrong it says so in the same shape, because a blank space
 * reads as "not loaded" rather than "all clear".
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  getJSON, type EventRow, type Overview, type RecommendationRow,
  type ShortageRow, type SupplierRow,
} from "@/lib/api";
import { ApiDot, Shell } from "@/components/Shell";
import {
  Card, Chip, Icon, Stat, ago, basisChip, day, num, plainName, severityChip,
} from "@/components/ui";

export default function OverviewPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [shortages, setShortages] = useState<ShortageRow[]>([]);
  const [events, setEvents] = useState<EventRow[]>([]);
  const [recos, setRecos] = useState<RecommendationRow[]>([]);
  const [suppliers, setSuppliers] = useState<SupplierRow[]>([]);
  const [online, setOnline] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      getJSON<Overview>("/api/overview"),
      getJSON<ShortageRow[]>("/api/shortages"),
      getJSON<EventRow[]>("/api/events"),
      getJSON<RecommendationRow[]>("/api/recommendations"),
      getJSON<SupplierRow[]>("/api/suppliers"),
    ])
      .then(([o, s, e, r, sup]) => {
        setOverview(o); setShortages(s); setEvents(e);
        setRecos(r); setSuppliers(sup); setOnline(true);
      })
      .catch(() => setOnline(false))
      .finally(() => setLoading(false));
  }, []);

  const active = shortages.filter((s) => s.shortage_qty > 0);
  const worst = active[0];
  const pending = recos.filter((r) => r.status === "PENDING_APPROVAL");
  const forWorst = worst ? recos.find((r) => r.original_mpn === worst.mpn) : undefined;
  const analysed = events.filter((e) => e.status === "ANALYZED");
  const cause = analysed[0];
  const weekEvents = events.filter(
    (e) => Date.now() - new Date(e.published_at).getTime() < 7 * 86_400_000,
  );
  const blocking = active.filter((s) => s.severity === "CRITICAL").length;
  const shaky = suppliers.filter((s) => s.score != null && s.score < 0.7).length;

  return (
    <Shell title="Overview" right={<ApiDot online={online} />}>
      {loading ? (
        <div className="card"><div className="body stack">
          <div className="skel" style={{ height: 56 }} />
          <div className="skel" style={{ height: 18, width: "55%" }} />
        </div></div>
      ) : online === false ? (
        <div className="verdict bad">
          <span className="ico"><Icon name="alert" /></span>
          <div className="txt">
            <h1>The backend is not reachable</h1>
            <p>
              Start it with{" "}
              <span className="mono">python -m uvicorn api.main:app --port 8000</span>
            </p>
          </div>
        </div>
      ) : worst ? (
        <div className="verdict bad">
          <span className="ico"><Icon name="alert" /></span>
          <div className="txt">
            <h1>
              You run out of {plainName("MCU", ["MC-3000", "SD-220"])} on{" "}
              {day(worst.first_shortfall_date)}
            </h1>
            <p>
              <span className="mono">{worst.mpn}</span> &mdash; short{" "}
              <span className="mono">{num(worst.shortage_qty)}</span> units.
              {cause ? <> Caused by: {cause.headline}</> : null}
            </p>
          </div>
          {forWorst && (
            <div className="act">
              <Link href={`/recommendations/${forWorst.id}`} className="btn">
                Review recommendation <Icon name="chev" size={13} />
              </Link>
            </div>
          )}
        </div>
      ) : (
        <div className="verdict good">
          <span className="ico"><Icon name="ok" /></span>
          <div className="txt">
            <h1>No active shortages</h1>
            <p>
              Every committed order in the next 60 days is covered.
              {overview && (
                <>
                  {" "}Demand <span className="mono">{num(overview.watch.committed_demand)}</span>,
                  usable stock <span className="mono">{num(overview.watch.usable_stock)}</span>.
                </>
              )}
            </p>
          </div>
          <div className="act">
            <Link href="/runs" className="btn sec">Run a pipeline</Link>
          </div>
        </div>
      )}

      <div className="stats">
        <Stat
          label="Active shortages" value={num(active.length)}
          qualifier={blocking ? `${blocking} block a committed order` : "none blocking"}
          tone={blocking ? "danger" : "success"}
        />
        <Stat
          label="Awaiting approval" value={num(pending.length)}
          qualifier={pending.length ? "needs a person" : "nothing pending"}
          tone={pending.length ? "warning" : undefined}
        />
        <Stat
          label="Events this week" value={num(weekEvents.length)}
          qualifier={`${analysed.length} of ${events.length} matched something we buy`}
        />
        <Stat
          label="Suppliers monitored" value={num(suppliers.length)}
          qualifier={shaky ? `${shaky} below 0.70 on delivery` : "all delivering on time"}
          tone={shaky ? "warning" : "success"}
        />
      </div>

      <div className="cols">
        <Card title="Shortages" rows
              aside={<Link href="/shortages" className="note">All &rsaquo;</Link>}>
          {active.length === 0 && <div className="empty">No active shortages.</div>}
          {active.map((s) => (
            <div className="item" key={s.id}>
              <div style={{ paddingTop: 2 }}>{severityChip(s.severity)}</div>
              <div className="main">
                <div className="t">{plainName("MCU", ["MC-3000", "SD-220"])}</div>
                <div className="s mono">{s.mpn}</div>
              </div>
              <div className="end">
                <div className="b mono">{num(s.shortage_qty)}</div>
                <div className="s">short from {day(s.first_shortfall_date)}</div>
              </div>
            </div>
          ))}
        </Card>

        <Card title="Events" rows
              aside={<Link href="/events" className="note">All &rsaquo;</Link>}>
          {events.length === 0 && <div className="empty">No events in the feed.</div>}
          {events.slice(0, 6).map((e) => (
            <div className="item" key={e.id}>
              <div className="main">
                <div className="row" style={{ gap: 8, marginBottom: 4 }}>
                  {e.status === "ANALYZED"
                    ? basisChip("SUPPLIER_LANE")
                    : <Chip tone="neutral">No match</Chip>}
                  <span className="s">{ago(e.published_at)}</span>
                </div>
                <div className="t">{e.headline}</div>
                <div className="s">
                  {e.status === "ANALYZED"
                    ? "matched parts we buy"
                    : e.skipped_reason ?? "not yet analysed"}
                </div>
              </div>
            </div>
          ))}
        </Card>
      </div>
    </Shell>
  );
}
