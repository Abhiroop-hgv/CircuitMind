"use client";

/**
 * Sign in, and the pitch.
 *
 * Two jobs on one screen. The left half has to answer "what is this?" for
 * someone who has never seen it -- a judge walking up mid-demo -- in the time
 * it takes them to read one column. The right half gets them in.
 *
 * The pitch is written as named capabilities with the mechanism stated, then a
 * worked example carrying real figures from the current dataset. Adjectives would
 * weaken the claim; the numbers do not, so the numbers do the work.
 *
 *
 * The boundary line at the bottom is deliberate and stays. Claiming to be an
 * ERP invites the one question we would lose on; saying plainly that we sit on
 * top of one turns that question into a strength.
 */

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { readSession, writeSession, ROLES, type Person } from "@/lib/session";
import { BoardArt } from "@/components/BoardArt";
import { Icon } from "@/components/ui";

const CAPABILITIES = [
  {
    step: "Event ingestion and extraction",
    body: "Published notices are read under a constrained JSON schema, so the model " +
          "can only emit categories, countries and dates that exist in your data. " +
          "Only events that have already occurred are analysed; nothing is forecast.",
  },
  {
    step: "Company-specific exposure",
    body: "Each event is resolved against your supplier lanes and the country of " +
          "origin of each part. The output is named part numbers, the suppliers " +
          "behind them and the quantity exposed — not a market-level advisory.",
  },
  {
    step: "Shortage quantification",
    body: "A running stock ledger runs your committed order book and a Holt-Winters " +
          "forecast against usable inventory, dating every movement. Deliveries " +
          "landing after they are needed are excluded rather than netted off.",
  },
  {
    step: "Substitute verification",
    body: "Candidates are retrieved by category, then checked against each board’s " +
          "design constraints — supply rail, footprint, temperature range, " +
          "interfaces — rule by rule. Verification is deterministic; the model " +
          "has no vote in it.",
  },
  {
    step: "Procurement optimisation",
    body: "Suppliers hit by the event are excluded outright. The rest are ranked on " +
          "quoted price adjusted for their recency-weighted on-time record, with " +
          "lead-time padding applied before feasibility is tested.",
  },
  {
    step: "Human approval",
    body: "Every plan is presented with the options that were rejected and the reason " +
          "for each. The system issues no orders and holds no write access to " +
          "procurement; approval is recorded against a named person.",
  },
];

export default function LoginPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [role, setRole] = useState(ROLES[0]);
  const [ready, setReady] = useState(false);

  // If someone is already signed in, do not make them do it again.
  useEffect(() => {
    const existing = readSession();
    if (existing) {
      setName(existing.name);
      setRole(existing.role);
    }
    setReady(true);
  }, []);

  function signIn() {
    const person: Person = { name: name.trim(), role };
    if (!person.name) return;
    writeSession(person);
    router.push("/");
  }

  return (
    <div className="login">
      <section className="pitch">
        <div className="brand">
          <span style={{ color: "var(--accent)" }}><Icon name="layer" size={30} /></span>
          <span>
            <b>CircuitMind</b>
            <span>supply-chain intelligence</span>
          </span>
        </div>

        <h1>External events, resolved to your own part numbers.</h1>

        <p className="lede">
          Your ERP records what you hold. It does not read trade notices, and it cannot
          tell you that an export licence published this morning leaves one
          microcontroller 5,130 units short by 15&nbsp;October. CircuitMind closes that gap:
          it reads events that have already occurred, resolves them against your bill of
          materials, supplier lanes and open purchase orders, and produces a costed
          procurement plan for a person to approve.
        </p>

        <ol className="chain">
          {CAPABILITIES.map((c, i) => (
            <li key={c.step}>
              <span className="n">{i + 1}</span>
              <div>
                <b>{c.step}</b>
                <span>{c.body}</span>
              </div>
            </li>
          ))}
        </ol>

        <div className="worked">
          <span className="label">Worked example, from the current dataset</span>
          <ol>
            <li>Export licence notice on microcontroller shipments originating in China</li>
            <li><b>STM32F407VGT6</b> matched by supplier lane, 4,000 units in transit exposed</li>
            <li>Cover lost <b>15 October</b>; shortfall <b>5,130</b> of 11,130 required</li>
            <li><b>STM32F429VGT6</b> verified against both boards that carry the original</li>
            <li><b>$56,960.50</b> across three suppliers, all landing 23 days early</li>
            <li>Held for approval, no order placed</li>
          </ol>
        </div>

        <p className="boundary">
          <b>CircuitMind is not an ERP.</b> It performs no order entry, invoicing, warehouse
          or accounting function, and reads from the systems you already operate. Every
          quantity, price, lead time and date is returned by a database query. The
          language model interprets text and selects which query to run; it is never the
          source of a number.
        </p>
      </section>

      <section className="gate">
        <BoardArt />

        <div className="card">
          <h2>Sign in</h2>
          <p className="note">Recorded against every approval you make.</p>

          <label htmlFor="who">Name</label>
          <input
            id="who" type="text" value={name} placeholder="e.g. A Sujay"
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") signIn(); }}
            autoComplete="off"
          />

          <label htmlFor="role">Role</label>
          <select id="role" value={role} onChange={(e) => setRole(e.target.value)}>
            {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>

          <button className="btn wide" onClick={signIn} disabled={!ready || !name.trim()}>
            Enter dashboard <Icon name="chev" size={13} />
          </button>

          <p className="demo">
            <b>Demo sign-in.</b> No password is set and no account is created. This
            identifies the person using the session so that approvals carry a name;
            it is not an access control.
          </p>
        </div>
      </section>
    </div>
  );
}
