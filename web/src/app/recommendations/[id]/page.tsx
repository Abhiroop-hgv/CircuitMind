"use client";

/**
 * Recommendation detail -- the page the whole product exists to produce.
 *
 * Header, the one action, then five collapsed evidence sections. The evidence
 * is genuinely collapsed: someone who trusts the verdict must never scroll past
 * open detail to reach the approve button.
 */

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { API, getJSON, postJSON, type RecoDetail, type PoManifest, HttpError } from "@/lib/api";
import { readSession } from "@/lib/session";
import { Shell } from "@/components/Shell";
import { Chip, Icon, day, money, num, plainName, severityChip } from "@/components/ui";

function Section({
  n, title, summary, children,
}: { n: number; title: string; summary: string; children: React.ReactNode }) {
  return (
    <details className="ev">
      <summary>
        <span className="n">{n}</span>
        <span>
          <span className="t">{title}</span>
          <span className="s" style={{ marginLeft: 8 }}>{summary}</span>
        </span>
        <span className="sp">
          <span className="chev"><Icon name="chev" size={13} /></span>
        </span>
      </summary>
      <div className="inner">{children}</div>
    </details>
  );
}

export default function RecommendationDetail() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<RecoDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Who is signed in, rather than a box anyone can type anything into.
  const [approver, setApprover] = useState("");

  // The orders this approval produces. Fetched only once approved, because
  // the endpoint refuses anything else -- which is the point of it.
  const [manifest, setManifest] = useState<PoManifest | null>(null);

  useEffect(() => {
    const person = readSession();
    if (person) setApprover(person.name);
  }, []);
  const [busy, setBusy] = useState(false);

  const [missing, setMissing] = useState(false);

  useEffect(() => {
    getJSON<RecoDetail>(`/api/recommendations/${id}`)
      .then(setData)
      .catch((e) => {
        // A recommendation can genuinely stop existing: a later run replaces
        // the shortage it was raised against and takes it with it. That is a
        // dead link, not a fault, and it should not read like one.
        if (e instanceof HttpError && e.status === 404) { setMissing(true); return; }
        setError(e instanceof Error ? e.message : String(e));
      });
  }, [id]);

  const status = data?.recommendation.status;
  useEffect(() => {
    if (status !== "APPROVED") { setManifest(null); return; }
    getJSON<PoManifest>(`/api/recommendations/${id}/po/manifest`, { fresh: true })
      .then(setManifest)
      .catch(() => setManifest(null));
  }, [id, status]);

  async function approve() {
    if (!data) return;
    setBusy(true);
    try {
      await postJSON(`/api/recommendations/${id}/approve`, { approver });
      setData({
        ...data,
        recommendation: { ...data.recommendation, status: "APPROVED", approved_by: approver },
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  const crumb = (
    <Link href="/recommendations" className="crumb row" style={{ gap: 6 }}>
      <Icon name="back" size={13} /> Recommendations
    </Link>
  );

  if (error) {
    return (
      <Shell title="Recommendation" crumb={crumb}>
        <div className="callout bad">{error}</div>
      </Shell>
    );
  }
  if (missing) {
    return (
      <Shell title="Recommendation" crumb={crumb}>
        <div className="card">
          <div className="empty" style={{ textAlign: "left" }}>
            <b>Recommendation #{id} no longer exists.</b>
            <p>
              Recommendations are raised against a specific shortage. When that
              shortage is recalculated &mdash; a new pipeline run, or a board
              registered through BOM intake &mdash; the old recommendation is
              replaced along with it. A link to one from before that run stops
              resolving.
            </p>
            <p>
              <Link className="btn" href="/recommendations">
                See current recommendations
              </Link>
            </p>
          </div>
        </div>
      </Shell>
    );
  }
  if (!data) {
    return (
      <Shell title="Recommendation" crumb={crumb}>
        <div className="card"><div className="body stack">
          <div className="skel" style={{ height: 44 }} />
          <div className="skel" style={{ height: 18, width: "50%" }} />
        </div></div>
      </Shell>
    );
  }

  const r = data.recommendation;
  const s = data.shortage;
  const approved = r.status === "APPROVED";
  const boards = ["MC-3000", "SD-220"];
  const chosen = data.alternatives.find((a) => a.mpn === data.lines[0]?.mpn);
  const cheapest = r.considered.find((c) => c.viable && c.plan !== r.strategy);

  return (
    <Shell title={`Recommendation #${r.id}`} crumb={crumb}>
      <header className="stack" style={{ marginBottom: 18 }}>
        <div className="row">
          {severityChip(s?.severity)}
          {r.requires_bom_change && <Chip tone="warning">BOM change</Chip>}
          {!approved && <Chip tone="accent">Awaiting approval</Chip>}
        </div>
        <h1>{plainName(r.category, boards)}</h1>
        <div className="note">
          <span className="mono">{r.original_mpn}</span>
          {s && (
            <> &mdash; short <span className="mono">{num(s.shortage_qty)}</span> units
            from <span className="mono">{day(s.first_shortfall_date)}</span></>
          )}
        </div>
      </header>

      {/* ------------------------------------------------- the one action -- */}
      <section className="card">
        <div className="body stack">
          <p style={{ color: "var(--text-2)", maxWidth: "76ch" }}>{r.rationale}</p>

          <div className="grid3">
            <div className="stat">
              <div className="l">Supplier{data.lines.length > 1 ? "s" : ""}</div>
              <div className="v" style={{ fontSize: 17 }}>
                {data.lines.map((l) => l.supplier).join(", ") || "—"}
              </div>
              <div className="q">{data.lines.length} order line{data.lines.length === 1 ? "" : "s"}</div>
            </div>
            <div className="stat">
              <div className="l">Estimated cost</div>
              <div className="v mono">{money(r.total_cost)}</div>
              {cheapest && (
                <div className="q">
                  {money(Math.abs(r.total_cost - cheapest.total_cost))} vs single-sourcing
                </div>
              )}
            </div>
            <div className="stat">
              <div className="l">Arrives by</div>
              <div className="v mono" style={{ fontSize: 20 }}>{day(r.latest_arrival)}</div>
              <div className="q">needed {day(r.need_by)}</div>
            </div>
          </div>

          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th>supplier</th><th>part</th><th className="num">qty</th>
                  <th className="num">unit</th><th className="num">line total</th>
                  <th>arrives</th><th className="num">on-time record</th>
                </tr>
              </thead>
              <tbody>
                {data.lines.map((l, i) => (
                  <tr key={i}>
                    <td>{l.supplier}</td>
                    <td className="mono">{l.mpn}</td>
                    <td className="num mono">{num(l.quantity)}</td>
                    <td className="num mono">{money(l.unit_price)}</td>
                    <td className="num mono">{money(l.line_total)}</td>
                    <td className="mono">{day(l.expected_arrival)}</td>
                    <td className="num mono">
                      {l.deliveries
                        ? `${l.on_time}/${l.deliveries}`
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="row" style={{ borderTop: "1px solid var(--border-soft)", paddingTop: 16 }}>
            {approved ? (
              <Chip tone="success">Approved by {r.approved_by}</Chip>
            ) : (
              <>
                <span className="note">
                  Approving as <b>{approver || "nobody"}</b>
                </span>
                <button className="btn" onClick={approve} disabled={!approver.trim() || busy}>
                  Approve recommendation
                </button>
                <button className="btn sec" disabled>Request changes</button>
              </>
            )}
          </div>

          {approved && manifest && manifest.orders.length > 0 && (
            <div className="pos">
              <div className="head">
                <b>Purchase orders</b>
                <span className="note">
                  one per supplier &mdash; each file contains only that supplier&rsquo;s order
                </span>
                <a
                  className="btn"
                  href={`${API}/api/recommendations/${id}/po.zip`}
                  target="_blank" rel="noopener noreferrer"
                >
                  Download all {manifest.orders.length} (ZIP)
                </a>
              </div>

              <div className="scroll">
                <table>
                  <thead>
                    <tr>
                      <th>order</th><th>supplier</th><th className="num">qty</th>
                      <th className="num">value</th><th>promised</th><th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {manifest.orders.map((o) => (
                      <tr key={o.po_number}>
                        <td className="mono">{o.po_number}</td>
                        <td>{o.supplier} <span className="note">{o.country}</span></td>
                        <td className="num mono">{num(o.quantity)}</td>
                        <td className="num mono">{money(o.total)}</td>
                        <td className="mono">{day(o.promised)}</td>
                        <td className="num">
                          <a
                            className="linkish"
                            href={`${API}/api/recommendations/${id}/po?supplier=${o.supplier_code}`}
                            target="_blank" rel="noopener noreferrer"
                          >
                            PDF
                          </a>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <p className="note" style={{ marginTop: 10, maxWidth: "78ch" }}>
                Send each supplier only their own file. The{" "}
                <a className="linkish"
                   href={`${API}/api/recommendations/${id}/po`}
                   target="_blank" rel="noopener noreferrer">combined copy</a>{" "}
                carries every supplier&rsquo;s quantities and unit prices on the same
                document, so it is for internal review and must not go out. Nothing
                here is transmitted anywhere &mdash; issuing an order stays a human act.
              </p>
            </div>
          )}

          <p className="note" style={{ maxWidth: "78ch" }}>
            Approving records <b>who approved it and when, in our own database</b>. It
            does not contact any supplier, and there is no code in this system that can.
          </p>
        </div>
      </section>

      {/* --------------------------------------------------- the evidence -- */}
      <h2 style={{ margin: "26px 0 12px", color: "var(--text-2)" }}>Evidence</h2>

      <Section
        n={1} title="Demand forecast"
        summary={data.forecast.length
          ? `${num(data.forecast.reduce((n, f) => n + f.net_demand_qty, 0))} units`
          : "not run"}
      >
        {data.forecast.length === 0 ? (
          <p>No forecast has been run for this component.</p>
        ) : (
          <>
            <p>
              {data.forecast[0].method}. For each month the planner takes whichever is
              larger &mdash; the committed order book or the forecast. Adding them
              would count the same customer twice; this is forecast consumption.
            </p>
            <div className="scroll">
              <table>
                <thead>
                  <tr>
                    <th>month</th><th className="num">committed</th>
                    <th className="num">forecast</th><th className="num">used</th><th>which led</th>
                  </tr>
                </thead>
                <tbody>
                  {data.forecast.map((f, i) => (
                    <tr key={i}>
                      <td className="mono">{String(f.period_month).slice(0, 7)}</td>
                      <td className="num mono">{num(f.committed_qty)}</td>
                      <td className="num mono">{num(f.forecast_qty)}</td>
                      <td className="num mono"><b>{num(f.net_demand_qty)}</b></td>
                      <td>{f.committed_qty >= f.forecast_qty ? "order book" : "forecast"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Section>

      <Section
        n={2} title="Stock ledger"
        summary={s ? `${s.ledger.length} movements` : "not run"}
      >
        {!s ? <p>No shortage record found.</p> : (
          <>
            <p>
              A running balance, not a single subtraction. Demand and supply can
              balance across a quarter while you still run dry mid-way, because parts
              land after the boards were due out. The highlighted row is where the
              balance turns negative.
            </p>
            <div className="scroll">
              <table>
                <thead>
                  <tr>
                    <th>date</th><th>movement</th><th>reference</th>
                    <th className="num">change</th><th className="num">balance</th>
                  </tr>
                </thead>
                <tbody>
                  {s.ledger.map((row, i) => {
                    const first = s.ledger.findIndex((x) => x.balance < 0);
                    return (
                      <tr key={i} className={i === first ? "flag" : undefined}>
                        <td className="mono">{row.date}</td>
                        <td>{row.kind.toLowerCase().replace(/_/g, " ")}</td>
                        <td className="mono">{row.ref}</td>
                        <td className="num mono">{num(row.qty)}</td>
                        <td className="num mono">{num(row.balance)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Section>

      <Section
        n={3} title="Compatibility check"
        summary={`${data.alternatives.filter((a) => a.verdict === "PASS").length} of ${data.alternatives.length} fit`}
      >
        <p>
          Each candidate is checked against what the <b>board</b> requires, not against
          the part being replaced &mdash; and it must clear every board the original is
          fitted on.
        </p>
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>part</th><th className="num">unit cost</th><th>verdict</th>
                <th>per board</th><th>sourcing</th>
              </tr>
            </thead>
            <tbody>
              {data.alternatives.map((a) => (
                <tr key={a.mpn} className={a.verdict === "PASS" ? undefined : "mute"}>
                  <td className="mono">{a.mpn}</td>
                  <td className="num mono">{money(a.standard_cost)}</td>
                  <td>
                    {a.verdict === "PASS"
                      ? <Chip tone="success">Fits</Chip>
                      : <Chip tone="danger">No</Chip>}
                  </td>
                  <td className="mono">
                    {a.checks.map((b) => `${b.board} ${b.verdict === "PASS" ? "ok" : "fail"}`).join(" · ")}
                  </td>
                  <td style={{ color: a.sourcing_note.startsWith("SOURCING") ? "var(--warning)" : undefined }}>
                    {a.sourcing_note.startsWith("SOURCING")
                      ? "demoted — only sold by affected suppliers"
                      : a.sourcing_note}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {chosen && (
          <details className="ev" style={{ margin: 0 }}>
            <summary>
              <span className="t">Every constraint checked for {chosen.mpn}</span>
              <span className="sp">
                <span className="s">
                  {chosen.checks.reduce((n, b) => n + b.checks.length, 0)} checks
                </span>
                <span className="chev"><Icon name="chev" size={13} /></span>
              </span>
            </summary>
            <div className="inner">
              <div className="scroll">
                <table>
                  <thead>
                    <tr><th>board</th><th>constraint</th><th>needs</th><th>has</th><th></th></tr>
                  </thead>
                  <tbody>
                    {chosen.checks.flatMap((b) =>
                      b.checks.map((k, i) => (
                        <tr key={`${b.board}-${i}`} className={k.ok ? undefined : "flag"}>
                          <td className="mono">{b.board}</td>
                          <td className="mono">{k.name}</td>
                          <td className="mono">{k.required}</td>
                          <td className="mono">{k.actual}</td>
                          <td>{k.ok ? "ok" : "fail"}</td>
                        </tr>
                      )),
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </details>
        )}
      </Section>

      <Section
        n={4} title="Supplier comparison"
        summary={`${data.suppliers_considered.length} suppliers`}
      >
        <p>
          Ranked on a reliability-adjusted price, not the quote. A supplier&rsquo;s
          score is the recency-weighted share of past orders that arrived by the
          promised date; the padding is added to their quoted lead time before asking
          whether an order can land in time.
        </p>
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th>supplier</th><th className="num">on time</th><th className="num">score</th>
                <th className="num">quote</th><th className="num">adjusted</th>
                <th className="num">lead +pad</th><th className="num">allocated</th>
              </tr>
            </thead>
            <tbody>
              {data.suppliers_considered.map((sup) => {
                const score = sup.score ?? 1;
                const adjusted = sup.unit_price * (1 + (1 - score) * 0.15);
                const line = data.lines.find((l) => l.supplier === sup.name);
                return (
                  <tr key={sup.id} className={line ? undefined : "mute"}>
                    <td>{sup.name}</td>
                    <td className="num mono">
                      {sup.deliveries ? `${sup.on_time}/${sup.deliveries}` : "—"}
                    </td>
                    <td className="num mono">{score.toFixed(2)}</td>
                    <td className="num mono">{money(sup.unit_price)}</td>
                    <td className="num mono">{money(adjusted)}</td>
                    <td className="num mono">
                      {sup.lead_time_days}
                      {sup.lead_time_padding ? ` +${sup.lead_time_padding}` : ""}
                    </td>
                    <td className="num mono">{line ? num(line.quantity) : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Section>

      <Section
        n={5} title="Cost breakdown"
        summary={money(r.total_cost)}
      >
        <div className="scroll">
          <table>
            <thead>
              <tr><th>plan considered</th><th className="num">cost</th><th>outcome</th></tr>
            </thead>
            <tbody>
              {r.considered.map((c) => (
                <tr key={c.plan} className={c.plan === r.strategy ? undefined : "mute"}>
                  <td>
                    {c.plan}
                    {c.plan === r.strategy && <> &nbsp;<Chip tone="accent">chosen</Chip></>}
                  </td>
                  <td className="num mono">{c.viable ? money(c.total_cost) : "—"}</td>
                  <td>{c.viable ? `${c.suppliers} supplier(s)` : `short ${num(c.shortfall)}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p>
          Single-sourcing is usually cheapest, and concentration is what caused this
          shortage. The split is costed as well and taken when it comes in under a 5%
          premium.
        </p>
      </Section>
    </Shell>
  );
}
