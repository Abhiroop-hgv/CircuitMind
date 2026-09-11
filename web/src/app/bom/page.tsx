"use client";

/**
 * BOM intake.
 *
 * Preview first, register second. Registering is a real and permanent side
 * effect -- the board joins erp.products and starts being watched -- so it is
 * stated plainly under the button rather than discovered afterwards.
 */

import { useRef, useState } from "react";

import { API, streamFrames, type BomPreview, getJSON, postJSON, type PoManifest } from "@/lib/api";
import { ConstraintGate, describe } from "@/components/ConstraintGate";
import { readSession } from "@/lib/session";
import { Shell } from "@/components/Shell";
import { Chip, Icon, day, money, num } from "@/components/ui";

// resolve.py tags every OCR-derived line this way, matched or not -- see its
// module docstring. Surfaced here rather than left in a field the UI never
// reads, since the entire point of the tag is that a person sees it.
const isOcr = (note: string) => note.toLowerCase().includes("ocr");

const ACCEPTED = ["CSV", "TSV", "XLSX", "PDF", "TXT", "JPG", "PNG"];

export default function BomPage() {
  const [file, setFile] = useState<File | null>(null);
  const [over, setOver] = useState(false);
  const [preview, setPreview] = useState<BomPreview | null>(null);
  const [parseMs, setParseMs] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [registered, setRegistered] = useState<string | null>(null);

  // What the run produced, and the orders that follow once a person approves.
  const [recoId, setRecoId] = useState<number | null>(null);
  const [manifest, setManifest] = useState<PoManifest | null>(null);
  const [approving, setApproving] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  // What the engineer says a substitute must satisfy, set before the run.
  // Quantity edits and unknown-line resolutions, keyed by line number. The
  // file is what the customer sent; this is what we are actually building.
  const [edits, setEdits] = useState<Record<number, { mpn?: string; quantity?: number }>>({});
  const [gateOpen, setGateOpen] = useState(false);
  const [constraints, setConstraints] =
    useState<Record<string, string | number | string[]>>({});

  const [sku, setSku] = useState("SH-100");
  const [name, setName] = useState("Sensor Hub SH-100");
  const [qty, setQty] = useState(500);
  const [needBy, setNeedBy] = useState("2026-11-15");

  async function choose(f: File | null) {
    setFile(f); setPreview(null); setError(null); setRegistered(null);
    setEdits({});
    setRecoId(null); setManifest(null);
    if (!f) return;
    setBusy(true);
    const started = Date.now();
    try {
      const form = new FormData();
      form.append("file", f);
      const res = await fetch(`${API}/api/bom/preview`, { method: "POST", body: form });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      setPreview(await res.json());
      setParseMs(Date.now() - started);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  /**
   * Approve the plan this run produced, then fetch its purchase orders.
   *
   * Two calls rather than one, and deliberately so: the run never approves
   * anything, and the orders only exist because a named person pressed this.
   * Removing the press would remove the only human step in the chain.
   */
  async function approveAndGenerate() {
    if (!recoId) return;
    const who = readSession()?.name?.trim();
    if (!who) { setError("Sign in first, so the approval has a name against it."); return; }

    setApproving(true); setError(null);
    try {
      await postJSON(`/api/recommendations/${recoId}/approve`, { approver: who });
      setManifest(await getJSON<PoManifest>(
        `/api/recommendations/${recoId}/po/manifest`, { fresh: true }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setApproving(false);
    }
  }

  async function register() {
    if (!file) return;
    setBusy(true); setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("sku", sku);
      form.append("name", name);
      form.append("qty", String(qty));
      form.append("need_by", needBy);
      form.append("approver", "");
      form.append("constraints", JSON.stringify(constraints));
      form.append("overrides", JSON.stringify(edits));
      for await (const f of streamFrames("/api/run/bom", form)) {
        if (f.event === "error") setError(String(f.data.message));
        if (f.event === "stage" && f.data.stage === "parse" && f.data.status === "done") {
          setRegistered(String(f.data.product_id ?? ""));
        }
        if (f.event === "complete" && f.data.recommendation_id) {
          setRecoId(Number(f.data.recommendation_id));
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally { setBusy(false); }
  }

  // A line stops blocking the run once a person has said which part it is.
  // The file said something we do not stock; they know what they meant.
  const unresolvedLines = (preview?.lines ?? [])
    .filter((l) => l.resolution === "UNKNOWN" && !edits[l.line_number]?.mpn);
  const unresolved = unresolvedLines.map((l) => l.mpn_raw);

  // How many of those we could actually fill. A line with no suggestion at all
  // stays for a person to deal with rather than being counted and then skipped.
  const topPickable = unresolvedLines.filter(
    (l) => (preview?.suggestions?.[String(l.line_number)] ?? []).length > 0).length;

  /**
   * Fill every unresolved line with its highest-ranked match.
   *
   * This is a shortcut through ten dropdowns, not an automatic matcher. The
   * distinction matters and the interface keeps it: a person presses it, each
   * row then shows the swap it made, and any one of them can be changed or
   * cleared before the run. Nothing is matched without someone choosing to.
   */
  function useTopSuggestions() {
    setEdits((prev) => {
      const next = { ...prev };
      for (const line of unresolvedLines) {
        const top = preview?.suggestions?.[String(line.line_number)]?.[0];
        if (top) {
          next[line.line_number] = { ...next[line.line_number], mpn: top.mpn };
        }
      }
      return next;
    });
  }
  const counts = preview
    ? {
        exact: preview.lines.filter((l) => l.resolution === "EXACT").length,
        normalised: preview.lines.filter((l) => l.resolution === "NORMALISED").length,
        unknown: preview.lines.filter((l) => l.resolution === "UNKNOWN").length,
      }
    : null;

  return (
    <Shell title="BOM intake">
      <div className="stack" style={{ maxWidth: 980 }}>
        <div
          className={`drop ${over ? "over" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); void choose(e.dataTransfer.files?.[0] ?? null); }}
          onClick={() => input.current?.click()}
          role="button" tabIndex={0}
          onKeyDown={(e) => { if (e.key === "Enter") input.current?.click(); }}
        >
          <div className="big">{file ? file.name : "Drag a file here, or browse"}</div>
          <div className="sm">
            A bill of materials for a board you want to build &mdash;
            or a scan or photo of one, read via OCR.
          </div>
          <div className="types">
            {ACCEPTED.map((t) => <Chip key={t} tone="neutral">{t}</Chip>)}
          </div>
        </div>
        <input
          ref={input} type="file" style={{ display: "none" }}
          accept=".csv,.tsv,.xlsx,.xls,.pdf,.txt,.jpg,.jpeg,.png,.bmp,.tiff,.tif"
          onChange={(e) => void choose(e.target.files?.[0] ?? null)}
        />

        {error && <div className="callout bad">{error}</div>}

        {preview && counts && (
          <>
            <section className="card">
              <header>
                <h2>{preview.filename}</h2>
                <span className="note mono">
                  {preview.lines.length} lines
                  {parseMs != null ? ` · parsed in ${parseMs} ms` : ""}
                </span>
                {counts.unknown > 0
                  ? <Chip tone="danger">{counts.unknown} unknown — blocks build</Chip>
                  : <Chip tone="success">All lines matched</Chip>}
              </header>

              <div className="body stack">
                <div className="counts">
                  <div className="c ok">
                    <div className="v mono">{num(counts.exact)}</div>
                    <div className="l">Exact matches</div>
                  </div>
                  <div className="c mid">
                    <div className="v mono">{num(counts.normalised)}</div>
                    <div className="l">Normalised matches</div>
                  </div>
                  <div className="c bad">
                    <div className="v mono">{num(counts.unknown)}</div>
                    <div className="l">Unknown</div>
                  </div>
                </div>

                <div className="scroll">
                  <table>
                    <thead>
                      <tr>
                        <th className="num">#</th><th>part number</th><th>description</th>
                        <th className="num">qty</th><th>match</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.lines.map((l) => {
                        const edit = edits[l.line_number] ?? {};
                        const picked = edit.mpn ?? "";
                        const qty = edit.quantity ?? l.qty_per_board;
                        const options = preview.suggestions?.[String(l.line_number)] ?? [];
                        const settled = l.resolution !== "UNKNOWN" || !!picked;

                        return (
                          <tr key={l.line_number} className={settled ? undefined : "flag"}>
                            <td className="num mono">{l.line_number}</td>
                            <td className="mono">
                              {l.mpn_raw}
                              {picked && (
                                <span className="swapped"> &rarr; {picked}</span>
                              )}
                              {isOcr(l.note) && (
                                <span title={l.note}>
                                  {" "}<Chip tone="ai">OCR &mdash; verify</Chip>
                                </span>
                              )}
                            </td>
                            <td>
                              {l.description}
                              {l.resolution === "UNKNOWN" && options.length > 0 && (
                                <div className="picks">
                                  <span className="lead">
                                    not stocked &mdash; closest parts we hold:
                                  </span>
                                  {options.slice(0, 3).map((o) => (
                                    <button
                                      key={o.mpn}
                                      className={`pick${picked === o.mpn ? " on" : ""}`}
                                      title={`${o.description} · match ${o.score}`}
                                      onClick={() => setEdits((p) => ({
                                        ...p,
                                        [l.line_number]: {
                                          ...p[l.line_number],
                                          mpn: picked === o.mpn ? undefined : o.mpn,
                                        },
                                      }))}
                                    >
                                      <span className="m mono">{o.mpn}</span>
                                      <span className="c">{o.category.toLowerCase().replace(/_/g, " ")}</span>
                                      <span className="s">{Math.round(o.score * 100)}%</span>
                                    </button>
                                  ))}
                                  {options.length > 3 && (
                                    <select
                                      className="resolve"
                                      value={options.slice(0, 3).some((o) => o.mpn === picked) ? "" : picked}
                                      onChange={(e) => setEdits((p) => ({
                                        ...p,
                                        [l.line_number]: { ...p[l.line_number], mpn: e.target.value || undefined },
                                      }))}
                                    >
                                      <option value="">more&hellip;</option>
                                      {options.slice(3).map((o) => (
                                        <option key={o.mpn} value={o.mpn}>
                                          {o.mpn} &middot; {o.category} &middot; {o.description.slice(0, 40)}
                                        </option>
                                      ))}
                                    </select>
                                  )}
                                </div>
                              )}
                            </td>
                            <td className="num">
                              <input
                                className="qty"
                                type="number"
                                min={0}
                                value={qty}
                                aria-label={`quantity for line ${l.line_number}`}
                                onChange={(e) => setEdits((p) => ({
                                  ...p,
                                  [l.line_number]: {
                                    ...p[l.line_number],
                                    quantity: Math.max(0, Number(e.target.value) || 0),
                                  },
                                }))}
                              />
                              {qty === 0 && <span className="dnp-tag">DNP</span>}
                            </td>
                            <td>
                              {picked
                                ? <Chip tone="accent">Resolved by you</Chip>
                                : <>
                                    {l.resolution === "EXACT" && <Chip tone="success">Exact</Chip>}
                                    {l.resolution === "NORMALISED" && <Chip tone="warning">Normalised</Chip>}
                                    {l.resolution === "UNKNOWN" && <Chip tone="danger">Unknown</Chip>}
                                  </>}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>

            {unresolved.length > 0 && (
              <div className="callout bad">
                <b>{unresolved.join(", ")}</b>{" "}
                {unresolved.length === 1 ? "is" : "are"} not in the parts catalogue.
                Intake will not guess: there is no fuzzy matching, because two part
                numbers can differ by one character and by half the memory, and a
                wrongly matched part ships as the wrong component. Pick the part you
                meant on each row, and the run continues as normal from there.
                {topPickable > 0 && (
                  <div className="fill-row">
                    <button className="btn sec" onClick={useTopSuggestions}>
                      Use the top suggestion for {topPickable === 1
                        ? "the remaining line"
                        : `all ${topPickable} remaining lines`}
                    </button>
                    <span className="note">
                      Fills each row with its highest-ranked match. Every one stays
                      visible and editable &mdash; check them before you run.
                    </span>
                  </div>
                )}
              </div>
            )}

            <section className="card">
              <header><h2>Register this board</h2></header>
              <div className="body stack">
                <div className="row">
                  <input type="text" value={sku} onChange={(e) => setSku(e.target.value)}
                         style={{ width: 110 }} aria-label="SKU" />
                  <input type="text" value={name} onChange={(e) => setName(e.target.value)}
                         style={{ flex: "1 1 200px" }} aria-label="board name" />
                  <input type="number" value={qty} onChange={(e) => setQty(Number(e.target.value))}
                         style={{ width: 100 }} aria-label="quantity to build" />
                  <input type="date" value={needBy} onChange={(e) => setNeedBy(e.target.value)}
                         aria-label="need by" />
                </div>
                <div className="row">
                  <button className="btn" onClick={register} disabled={busy || unresolved.length > 0}>
                    Register board &amp; check buildability
                  </button>
                  <button className="btn sec" onClick={() => setGateOpen(true)}>
                    {Object.keys(constraints).length === 0
                      ? "Set constraints"
                      : `Constraints (${Object.keys(constraints).length})`}
                  </button>
                </div>

                {Object.keys(constraints).length > 0 && (
                  <p className="gate-set">
                    <b>A substitute must satisfy:</b> {describe(constraints)}
                    <button className="linkish" onClick={() => setConstraints({})}>
                      clear
                    </button>
                  </p>
                )}
                <p className="note" style={{ maxWidth: "78ch" }}>
                  Registering adds this board to <span className="mono">erp.products</span>{" "}
                  immediately, so the news monitor, the forecaster and the shortage
                  calculation start watching it from that moment.
                </p>
                {registered && !recoId && (
                  <div className="callout">
                    Registered as product <span className="mono">#{registered}</span>.
                    Everything is covered &mdash; nothing to buy.
                  </div>
                )}

                {recoId && !manifest && (
                  <div className="callout">
                    <b>Recommendation #{recoId} is waiting for approval.</b> The plan is
                    priced and the suppliers are chosen, but nothing is ordered until a
                    person signs it.
                    <div className="fill-row">
                      <button className="btn" onClick={approveAndGenerate} disabled={approving}>
                        {approving ? "Approving\u2026"
                          : `Approve as ${readSession()?.name ?? "\u2014"} and generate purchase orders`}
                      </button>
                      <span className="note">
                        Or open <a href={`/recommendations/${recoId}`}>the full recommendation</a>{" "}
                        to see the plans that were rejected first.
                      </span>
                    </div>
                  </div>
                )}

                {manifest && manifest.orders.length > 0 && (
                  <div className="pos">
                    <div className="head">
                      <b>Purchase orders</b>
                      <span className="note">
                        one per supplier &mdash; each file contains only that supplier&rsquo;s order
                      </span>
                      <a className="btn" target="_blank" rel="noopener noreferrer"
                         href={`${API}/api/recommendations/${recoId}/po.zip`}>
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
                              <td>{o.supplier}</td>
                              <td className="num mono">{num(o.quantity)}</td>
                              <td className="num mono">{money(o.total)}</td>
                              <td className="mono">{day(o.promised)}</td>
                              <td className="num">
                                <a className="linkish" target="_blank" rel="noopener noreferrer"
                                   href={`${API}/api/recommendations/${recoId}/po?supplier=${o.supplier_code}`}>
                                  PDF
                                </a>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <p className="note" style={{ marginTop: 10, maxWidth: "78ch" }}>
                      Approved by <b>{manifest.approved_by}</b>. Send each supplier only
                      their own file. Nothing has been transmitted &mdash; issuing an order
                      stays a human act.
                    </p>
                  </div>
                )}
              </div>
            </section>
          </>
        )}

        {busy && !preview && (
          <div className="row"><Icon name="runs" /> <span className="note">reading the file…</span></div>
        )}
      </div>

      <ConstraintGate
        open={gateOpen}
        initial={constraints}
        onCancel={() => setGateOpen(false)}
        onApply={(c) => { setConstraints(c); setGateOpen(false); }}
      />
    </Shell>
  );
}
