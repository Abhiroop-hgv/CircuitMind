"use client";

/**
 * The recommendation list.
 *
 * A reader landing here has about three seconds. The row is written so those
 * three seconds are enough, in this order:
 *
 *   what to do    "Buy 5,130 controller chips"      -- an instruction, not a
 *                                                      strategy label
 *   what changes  "STM32F407VGT6 -> STM32F429VGT6"  -- the swap, once
 *   why it exists "China export controls ..."       -- the cause, in the
 *                                                      publisher's own words
 *   does it work  "23 days early"                   -- the answer, precomputed
 *
 * The part numbers stay, because a hardware buyer needs them, but they are
 * demoted to the second line: they are the detail, not the headline. Everything
 * that used to require opening the detail page to understand is now on the row.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import { getJSON, type RecommendationRow } from "@/lib/api";
import { Shell } from "@/components/Shell";
import { Card, Chip, Icon, day, money, num, partWord, slackDays } from "@/components/ui";

export default function RecommendationsPage() {
  const [rows, setRows] = useState<RecommendationRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getJSON<RecommendationRow[]>("/api/recommendations")
      .then(setRows)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <Shell title="Recommendations">
      {error && <div className="callout bad">{error}</div>}
      <Card title="Purchase recommendations" rows>
        {rows === null && <div className="body"><div className="skel" style={{ height: 40 }} /></div>}
        {rows?.length === 0 && (
          <div className="empty">
            Nothing yet. Run a pipeline from <Link href="/runs">the run view</Link>.
          </div>
        )}
        {rows?.map((r) => {
          // Every line of a plan buys the same part; take the one that is not
          // the original, if there is one.
          const bought = [...new Set((r.lines ?? []).map((l) => l.mpn))];
          const replacement = bought.find((m) => m !== r.original_mpn) ?? null;
          const swapped = replacement !== null;

          // How far short we would fall by doing nothing. This is the number
          // that justifies the whole recommendation, and it was previously
          // buried in the rejected-plans table on the detail page.
          const noChange = r.considered?.find((c) => /original part/i.test(c.plan));
          const short = noChange && !noChange.viable ? noChange.shortfall : null;

          const slack = slackDays(r.need_by, r.latest_arrival);
          const approved = r.status === "APPROVED";

          return (
            <Link href={`/recommendations/${r.id}`} key={r.id} className="item">
              <div style={{ paddingTop: 2 }}>
                {approved
                  ? <Chip tone="success">Approved</Chip>
                  : <Chip tone="accent">Awaiting approval</Chip>}
              </div>

              <div className="main">
                <div className="t">
                  Buy {num(r.qty_required)} {partWord(r.category, r.qty_required)}
                  {swapped && " — a verified replacement"}
                </div>

                <div className="s">
                  <span className="mono">
                    {swapped ? `${r.original_mpn} → ${replacement}` : r.original_mpn}
                  </span>
                  {r.requires_bom_change ? " · needs a BOM change" : " · no design change"}
                </div>

                <div className="why">
                  {r.event_headline ?? "Raised by a new board going into production"}
                  {short !== null
                    ? ` — left us ${num(short)} short for ${day(r.need_by)}`
                    : ` — needed by ${day(r.need_by)}`}
                </div>
              </div>

              <div className="end">
                <div className="b mono">{money(r.total_cost)}</div>
                <div style={{ marginTop: 4 }}>
                  {approved ? (
                    <span className="s">by {r.approved_by}</span>
                  ) : slack === null ? (
                    <span className="s">arrives {day(r.latest_arrival)}</span>
                  ) : slack >= 0 ? (
                    <Chip tone="success">lands {slack} days early</Chip>
                  ) : (
                    <Chip tone="danger">{-slack} days late</Chip>
                  )}
                </div>
              </div>

              <span style={{ color: "var(--text-3)", alignSelf: "center" }}>
                <Icon name="chev" size={14} />
              </span>
            </Link>
          );
        })}
      </Card>

      <p className="note" style={{ marginTop: 12, maxWidth: "76ch" }}>
        Every figure above is calculated, not written by the model: the quantity from
        the stock ledger, the shortfall from the plan that was rejected, the cost and
        arrival dates from live supplier offers. Open a row to see the plans that were
        turned down and why.
      </p>
    </Shell>
  );
}
