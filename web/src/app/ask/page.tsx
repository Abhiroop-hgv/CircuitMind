"use client";

/**
 * Ask.
 *
 * A question in English, answered from the same tables every other page reads.
 *
 * The design decision worth defending is the "how I got this" toggle under each
 * answer. A chat box on a supply-chain dashboard is only trustworthy if you can
 * see that the number came from a query rather than from the model's
 * imagination, so every answer carries the tool calls that produced it and the
 * raw result each one returned. Collapsed by default, because a planner wants
 * the number; one click away, because a sceptic wants the receipt.
 *
 * The starter questions are not decoration either -- they are the fastest way
 * for someone who has never seen the system to find out what it can be asked.
 */

import { useEffect, useRef, useState } from "react";

import { ask, type AskCall } from "@/lib/api";
import { Shell } from "@/components/Shell";
import { Card, Icon } from "@/components/ui";
import { ToolResult, label } from "@/components/ToolResult";

/**
 * The model writes **bold** out of habit. Rather than pull in a markdown
 * renderer for one feature -- or set dangerouslySetInnerHTML on model output,
 * which is the wrong instinct even when escaped -- split on the delimiter and
 * render the odd segments as <strong>. Anything else it emits stays literal.
 */
function RichText({ text }: { text: string }) {
  return (
    <>
      {text.split("**").map((part, i) =>
        i % 2 === 1 ? <strong key={i}>{part}</strong> : <span key={i}>{part}</span>)}
    </>
  );
}

interface Turn {
  you: string;
  answer: string | null;
  calls: AskCall[];
  unverified: string[];
  error?: string;
}

const STARTERS = [
  "How much of the STM32F407VGT6 is left?",
  "What is the forecast for September for the STM32F407VGT6?",
  "What news would affect my inventory?",
  "When do we run out of the STM32F407VGT6?",
  "Which supplier delivers late most often?",
];

export default function AskPage() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns, busy]);

  async function send(question: string) {
    const q = question.trim();
    if (!q || busy) return;

    setText("");
    setBusy(true);
    const at = turns.length;
    setTurns((t) => [...t, { you: q, answer: null, calls: [], unverified: [] }]);

    try {
      const out = await ask(q);
      setTurns((t) =>
        t.map((turn, i) =>
          i === at
            ? { ...turn, answer: out.answer, calls: out.calls,
                unverified: out.unverified ?? [] }
            : turn));
    } catch (e) {
      setTurns((t) =>
        t.map((turn, i) =>
          i === at
            ? { ...turn, answer: null, error: e instanceof Error ? e.message : String(e) }
            : turn));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell
      title="Ask"
      right={<span className="note">answers come from the database, not the model</span>}
    >
      <Card title="Assistant">
        {turns.length === 0 && (
          <div className="empty" style={{ textAlign: "left" }}>
            Ask about stock, demand for a month, or which events touch parts you buy.
            Every answer is built from a database query, and you can see the query.
          </div>
        )}

        <div className="chat">
          {turns.map((t, i) => (
            <div key={i} style={{ display: "contents" }}>
              <div className="turn you">
                <div className="bubble">{t.you}</div>
              </div>

              <div className="turn bot">
                {t.error ? (
                  <div className="callout bad">{t.error}</div>
                ) : t.answer === null ? (
                  <div className="bubble" style={{ color: "var(--text-3)" }}>
                    checking the database…
                  </div>
                ) : (
                  <>
                    <div className="bubble"><RichText text={t.answer} /></div>

                    {t.unverified.length > 0 && (
                      <div className="unverified">
                        {t.unverified.length === 1 ? "This figure was" : "These figures were"}{" "}
                        not in any query result: <b>{t.unverified.join(", ")}</b>. It may be
                        arithmetic the assistant did itself — check it against the working
                        below before acting on it.
                      </div>
                    )}

                    {t.calls.length > 0 && (
                      <>
                        <button
                          className="working"
                          onClick={() => setOpen((o) => ({ ...o, [i]: !o[i] }))}
                        >
                          {open[i] ? "hide" : "how I got this"} · {t.calls.length}{" "}
                          {t.calls.length === 1 ? "query" : "queries"}
                        </button>

                        {open[i] && (
                          <div className="calls">
                            {t.calls.map((c, j) => (
                              <div className="call" key={j}>
                                <div className="name">
                                  {label(c.tool)}
                                  {Object.entries(c.arguments)
                                    .filter(([, v]) => v !== null && v !== "")
                                    .map(([k, v]) => (
                                      <span className="arg" key={k}>
                                        {label(k).toLowerCase()}: <b>{String(v)}</b>
                                      </span>
                                    ))}
                                </div>
                                <ToolResult result={c.result} />
                              </div>
                            ))}
                          </div>
                        )}
                      </>
                    )}
                  </>
                )}
              </div>
            </div>
          ))}
          <div ref={endRef} />
        </div>

        <div className="askbar">
          <input
            value={text}
            placeholder="Ask about stock, demand or supply risk"
            aria-label="question"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") send(text); }}
            disabled={busy}
          />
          <button className="btn" onClick={() => send(text)} disabled={busy || !text.trim()}>
            {busy ? "Asking…" : <>Ask <Icon name="chev" size={13} /></>}
          </button>
        </div>

        <div className="starters">
          {STARTERS.map((s) => (
            <button key={s} onClick={() => send(s)} disabled={busy}>{s}</button>
          ))}
        </div>
      </Card>

      <p className="note" style={{ marginTop: 12, maxWidth: "76ch" }}>
        The assistant can read stock, forecasts, supplier records and matched events.
        It cannot approve a recommendation, place an order, or change any record —
        approval stays a human decision. If it has no data for something it says so
        rather than estimating.
      </p>
    </Shell>
  );
}
