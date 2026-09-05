"use client";

/**
 * Live pipeline run.
 *
 * Left: a narrated stepper. Right: the raw SSE frames, deliberately more
 * technical -- it is there for someone who wants the underlying pipeline rather
 * than the narration.
 *
 * The endpoints are POSTs with bodies, so EventSource cannot be used; frames
 * are read off fetch's ReadableStream (see lib/api.ts).
 */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { streamFrames, type Frame } from "@/lib/api";
import { Shell } from "@/components/Shell";
import { AiChip, Icon, day, money, num } from "@/components/ui";

type State = "queued" | "running" | "done";

interface StepDef { key: string; name: string; ai: boolean }

const NEWS: StepDef[] = [
  { key: "read",        name: "Intelligence",  ai: true },
  { key: "demand",      name: "Demand",        ai: false },
  { key: "risk",        name: "Supply risk",   ai: false },
  { key: "component",   name: "Component",     ai: false },
  { key: "procurement", name: "Procurement",   ai: false },
];

const BOM: StepDef[] = [
  { key: "parse",       name: "BOM intake",    ai: false },
  { key: "build",       name: "Buildability",  ai: false },
  { key: "component",   name: "Component",     ai: false },
  { key: "procurement", name: "Procurement",   ai: false },
];

export default function RunsPage() {
  const [defs, setDefs] = useState<StepDef[]>(NEWS);
  const [state, setState] = useState<Record<string, State>>({});
  const [result, setResult] = useState<Record<string, string>>({});
  const [took, setTook] = useState<Record<string, number>>({});
  const [log, setLog] = useState<Frame[]>([]);
  const [running, setRunning] = useState(false);
  const [what, setWhat] = useState<string>("Nothing running");
  const [recoId, setRecoId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const clock = useRef<Record<string, number>>({});

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log]);

  /** One sentence per agent, from that agent's own numbers. */
  function narrate(stage: string, d: Record<string, unknown>): string {
    if (stage === "read") {
      const e = d.extraction as { countries?: string[]; categories?: string[] } | undefined;
      const hits = (d.impacts as { risk: string }[] | undefined) ?? [];
      return `Read as ${(e?.countries ?? []).join(", ") || "no country"} / ${
        (e?.categories ?? []).join(", ") || "no category"}. ${
        hits.filter((h) => h.risk !== "LOW").length} part(s) flagged.`;
    }
    if (stage === "demand") {
      return `Order book ${num(Number(d.committed))}, forecast adds ${
        num(Number(d.uncovered))}. Using ${num(Number(d.net))}.`;
    }
    if (stage === "risk") {
      const s = d.shortage as { shortage?: number; first_short?: string } | null;
      return s
        ? `Ledger walked day by day. Balance turns negative on ${day(s.first_short)}, short ${num(s.shortage ?? 0)}.`
        : "Ledger walked. Nothing short.";
    }
    if (stage === "component") {
      const c = (d.candidates as { verdict: string }[] | undefined) ?? [];
      return `${c.filter((x) => x.verdict === "PASS").length} of ${c.length} candidates clear every board.`;
    }
    if (stage === "procurement") {
      return `${d.strategy}. ${money(Number(d.total_cost))}, all in by ${day(String(d.latest_arrival))}.`;
    }
    if (stage === "parse") {
      const counts = d.counts as Record<string, number>;
      return `${counts.total} lines read, ${counts.UNKNOWN ?? 0} not recognised.`;
    }
    if (stage === "build") {
      const lines = (d.lines as { shortage: number }[] | undefined) ?? [];
      return `${lines.filter((l) => l.shortage > 0).length} of ${lines.length} components short.`;
    }
    return "done";
  }

  async function run(path: string, body: BodyInit, steps: StepDef[], label: string) {
    setDefs(steps); setState({}); setResult({}); setTook({}); setLog([]);
    setRecoId(null); setError(null); setWhat(label); setRunning(true);
    clock.current = {};
    try {
      for await (const f of streamFrames(path, body)) {
        setLog((l) => [...l, f]);
        const d = f.data as Record<string, unknown>;

        if (f.event === "error") { setError(String(d.message)); break; }
        if (f.event === "complete" && d.recommendation_id) {
          setRecoId(Number(d.recommendation_id));
        }
        if (f.event === "article") setWhat(String(d.headline));
        if (f.event !== "stage") continue;

        const stage = String(d.stage);
        if (d.status !== "done") {
          clock.current[stage] = Date.now();
          setState((s) => ({ ...s, [stage]: "running" }));
          continue;
        }
        setState((s) => ({ ...s, [stage]: "done" }));
        setTook((t) => ({
          ...t,
          [stage]: clock.current[stage] ? (Date.now() - clock.current[stage]) / 1000 : 0,
        }));
        setResult((r) => ({ ...r, [stage]: narrate(stage, d) }));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setRunning(false); }
  }

  const doneCount = defs.filter((d) => state[d.key] === "done").length;

  return (
    <Shell
      title="Pipeline run"
      right={
        <span className="row" style={{ gap: 8 }}>
          {running && <span className="pulse" />}
          <span className="note">
            {running ? `Running · step ${Math.min(doneCount + 1, defs.length)} of ${defs.length}` : what}
          </span>
        </span>
      }
    >
      <div className="row" style={{ marginBottom: 16 }}>
        <button
          className="btn" disabled={running}
          onClick={() => run("/api/run/news",
            new URLSearchParams({ external_id: "EVT-2026-09-02-001", use_model: "true", approver: "" }),
            NEWS, "Export licence notice")}
        >
          <Icon name="runs" size={15} /> Run disruption pipeline
        </button>
        <Link href="/bom" className="btn sec">New board intake &rsaquo;</Link>
        {recoId && (
          <Link href={`/recommendations/${recoId}`} className="btn sec">
            Open recommendation #{recoId}
          </Link>
        )}
      </div>

      {error && <div className="callout bad" style={{ marginBottom: 16 }}>{error}</div>}

      <div className="run">
        <div className="steps">
          {defs.map((d, i) => {
            const st = state[d.key] ?? "queued";
            return (
              <div className={`step ${st}`} key={d.key}>
                <div className="rail">
                  <span className="bead">
                    {st === "done" ? <Icon name="tick" size={12} /> : i + 1}
                  </span>
                  <span className="wire" />
                </div>
                <div className="box">
                  <div className="hd">
                    <b>{i + 1}. {d.name}</b>
                    <AiChip ai={d.ai} />
                    {took[d.key] != null && st === "done" && (
                      <span className="dur mono">{took[d.key].toFixed(1)}s</span>
                    )}
                  </div>
                  {st === "done" && <div className="res">{result[d.key]}</div>}
                  {st === "running" && <div className="bar"><i /></div>}
                </div>
              </div>
            );
          })}
        </div>

        <div className="card">
          <header><h2>Event stream</h2><span className="note mono">{log.length} frames</span></header>
          <div className="log" ref={logRef}>
            {log.length === 0 && <div style={{ opacity: .6 }}>waiting for a run…</div>}
            {log.map((f, i) => (
              <div className="ln" key={i}>
                <div className="ev-name">event: {f.event}</div>
                <div className="ev-data">data: {JSON.stringify(f.data).slice(0, 400)}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </Shell>
  );
}
