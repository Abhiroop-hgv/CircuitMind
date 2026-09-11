"use client";

/**
 * CircuitMind — the scroll-driven landing story.
 *
 * Seven cinematic scenes on one pinned stage, cross-faded and parallaxed by
 * scroll position:
 *   0 Hero            a chip over a circuit board
 *   1 Components      chips fall toward the board
 *   2 Assembly        they come together under light
 *   3 Board alive     the board powers on, traces run
 *   4 Disruption      a world map lights up red with live events
 *   5 CircuitMind     the risk is read and a costed action proposed
 *   6 Sign in         the door into the product (no separate /login page)
 */

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { useGSAP } from "@gsap/react";

import { readSession, writeSession, ROLES, type Person } from "@/lib/session";
import { ChipArt, PcbArt, MiniChip, DisruptionArcs } from "./art";

gsap.registerPlugin(ScrollTrigger, useGSAP);

const SCENES = 7;

const DROPS = [
  { left: "52%", top: "10%", s: 96, r: -16 },
  { left: "68%", top: "24%", s: 74, r: 12 },
  { left: "82%", top: "8%", s: 108, r: -8 },
  { left: "60%", top: "44%", s: 64, r: 20 },
  { left: "88%", top: "40%", s: 84, r: -12 },
  { left: "74%", top: "58%", s: 72, r: 14 },
  { left: "50%", top: "68%", s: 58, r: 24 },
];

const EVENTS = [
  { t: "EXPORT RESTRICTION", d: "A country restricts exports of selected microcontrollers.", x: "77%", y: "37%" },
  { t: "SUPPLIER DELAY", d: "A supplier's lead time jumps without warning.", x: "75%", y: "54%" },
  { t: "DEMAND SURGE", d: "Forecast demand runs past available inventory.", x: "30%", y: "40%" },
];

const CHECKS = [
  "Monitors global events in real time",
  "Identifies the components they touch",
  "Verifies the best alternatives",
  "Recommends an action, with the reasoning",
];

const PITCH = [
  "Real-time supply-chain intelligence",
  "AI-verified recommendations",
  "Built for the semiconductor industry",
];

function Logo() {
  return <img src="/circuitmind-icon.png" alt="" className="cm-mark-icon" />;
}
function Check() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden fill="none">
      <circle cx="10" cy="10" r="9" stroke="currentColor" strokeWidth="1.4" opacity="0.5" />
      <path d="M6 10.5l2.5 2.5L14 7.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function WelcomePage() {
  const router = useRouter();
  const root = useRef<HTMLDivElement>(null);
  const story = useRef<HTMLDivElement>(null);
  const [scene, setScene] = useState(0);
  const [navScrolled, setNavScrolled] = useState(false);

  const [name, setName] = useState("");
  const [role, setRole] = useState(ROLES[0]);
  useEffect(() => {
    const s = readSession();
    if (s) { setName(s.name); setRole(s.role); }
  }, []);

  function toSignIn() {
    const el = story.current;
    if (!el) return;
    window.scrollTo({ top: el.offsetTop + el.offsetHeight - window.innerHeight + 4, behavior: "smooth" });
  }
  function scrollOn() {
    window.scrollBy({ top: window.innerHeight * 1.15, behavior: "smooth" });
  }
  function signIn() {
    const person: Person = { name: name.trim(), role };
    if (!person.name) return;
    writeSession(person);
    router.push("/");
  }

  useGSAP(
    () => {
      const q = gsap.utils.selector(root);
      const sc = (i: number, sel = "") => `.cm-scene[data-i="${i}"] ${sel}`.trim();
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

      if (reduce) {
        gsap.set(q(".cm-scene"), { opacity: 1, clearProps: "all" });
        gsap.set(q(".cm-drop, .cm-event, .cm-insight, .cm-checklist li, .cm-beams i, .cm-signin > *"), { clearProps: "all", opacity: 1 });
        return;
      }

      const stNav = ScrollTrigger.create({
        start: 24, end: "max",
        onUpdate: (s) => setNavScrolled(s.scroll() > 24),
        onToggle: (s) => setNavScrolled(s.isActive),
      });

      // load-in: transform only, so the copy never depends on a frame loop for visibility
      gsap.from(q(sc(0, ".cm-kicker, h1, .cm-scene-copy > p, .cm-cta-row")), {
        y: 22, duration: 0.8, stagger: 0.08, ease: "power3.out", clearProps: "transform",
      });
      gsap.to(q(sc(0, ".cm-chip")), { y: 16, duration: 4, ease: "sine.inOut", repeat: -1, yoyo: true });

      const tl = gsap.timeline({
        defaults: { ease: "none" },
        scrollTrigger: {
          trigger: story.current, start: "top top", end: "bottom bottom", scrub: 0.6,
          onUpdate: (s) => setScene(Math.min(SCENES - 1, Math.floor(s.progress * SCENES * 0.999))),
        },
      });

      for (let i = 1; i < SCENES; i++) {
        tl.to(q(sc(i - 1)), { autoAlpha: 0, duration: 0.45 }, i - 0.22)
          .fromTo(q(sc(i)), { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.45 }, i - 0.22);
      }
      tl.to(q(".cm-scrollhint"), { autoAlpha: 0, duration: 0.3 }, 0.3);

      // 0 · hero
      tl.to(q(sc(0, ".cm-chip")), { y: -40, rotate: -3, scale: 0.94 }, 0)
        .to(q(sc(0, ".cm-pcb")), { yPercent: -6, scale: 1.06 }, 0);

      // 1 · components fall
      tl.from(q(sc(1, ".cm-drop")), {
        yPercent: -420, autoAlpha: 0, rotate: (i: number) => (i % 2 ? -50 : 50),
        stagger: 0.09, ease: "power1.in",
      }, 0.72)
        .to(q(sc(1, ".cm-drop")), { y: 30, stagger: 0.05 }, 1.15);

      // 2 · assembly
      tl.from(q(sc(2, ".cm-beams i")), { scaleY: 0, autoAlpha: 0, stagger: 0.04, ease: "power2.out" }, 1.7)
        .from(q(sc(2, ".cm-drop")), {
          x: (i: number) => (i % 2 ? -260 : 260) - (i - 3) * 40,
          y: (i: number) => (i % 3 ? -160 : 180),
          autoAlpha: 0, rotate: (i: number) => (i % 2 ? -30 : 30),
          stagger: 0.05, ease: "power3.out",
        }, 1.85)
        .from(q(sc(2, ".cm-chip")), { scale: 0.6, autoAlpha: 0, ease: "power3.out" }, 2.0);

      // 3 · board alive
      tl.from(q(sc(3, ".cm-board-glow")), { autoAlpha: 0, scale: 0.7 }, 2.72)
        .fromTo(q(sc(3, ".cm-pcb-live path")),
          { strokeDashoffset: 1, opacity: 0 },
          { strokeDashoffset: 0, opacity: 1, stagger: 0.14, ease: "power1.inOut" }, 2.8)
        .from(q(sc(3, ".cm-chip")), { scale: 0.88, autoAlpha: 0 }, 2.8);

      // 4 · disruption
      tl.from(q(sc(4, ".cm-worldwrap")), { autoAlpha: 0, scale: 0.94 }, 3.72)
        .from(q(sc(4, ".cm-marker")), { scale: 0, autoAlpha: 0, stagger: 0.12, ease: "back.out(2)" }, 3.9)
        .from(q(sc(4, ".cm-event")), { x: 70, autoAlpha: 0, stagger: 0.13, ease: "power3.out" }, 3.95);

      // 5 · CircuitMind responds
      tl.from(q(sc(5, ".cm-checklist li")), { x: -22, autoAlpha: 0, stagger: 0.08, ease: "power3.out" }, 4.75)
        .from(q(sc(5, ".cm-insight")), { y: 46, autoAlpha: 0, ease: "power3.out" }, 4.8)
        .from(q(sc(5, ".cm-insight dl > *")), { autoAlpha: 0, y: 10, stagger: 0.04 }, 5.0);

      // 6 · sign in — and retire the (dark) nav as the light panel arrives
      tl.to(q(".cm-nav"), { autoAlpha: 0, duration: 0.4 }, 5.55)
        .from(q(sc(6, ".cm-signin-pitch > *")), { x: -24, autoAlpha: 0, stagger: 0.06, ease: "power3.out" }, 5.75)
        .from(q(sc(6, ".cm-signin-card")), { y: 40, autoAlpha: 0, ease: "power3.out" }, 5.8);

      return () => stNav.kill();
    },
    { scope: root },
  );

  return (
    <div ref={root}>
      <nav className="cm-nav" data-scrolled={navScrolled}>
        <div className="cm-brand"><Logo />CircuitMind</div>
        <div className="cm-nav-links">
          <button onClick={scrollOn}>Why</button>
          <button onClick={scrollOn}>Solution</button>
          <button onClick={toSignIn}>Impact</button>
        </div>
        <div className="cm-nav-actions">
          <button className="cm-login" onClick={toSignIn} style={{ background: "none", border: 0, cursor: "pointer" }}>Login</button>
          <button className="cm-btn cm-btn--primary" onClick={toSignIn}>Get Started</button>
        </div>
      </nav>

      <div className="cm-story" ref={story}>
        <div className="cm-stage">

          {/* 0 · HERO */}
          <section className="cm-scene" data-i="0">
            <div className="cm-scene-copy">
              <p className="cm-kicker">Supply-chain intelligence for a more resilient tomorrow</p>
              <h1>Smarter supply chains for a <span className="accent">more connected world</span>.</h1>
              <p>AI-powered intelligence for the semiconductor industry.</p>
              <div className="cm-cta-row">
                <button className="cm-btn cm-btn--primary" onClick={scrollOn}>Explore CircuitMind</button>
                <button className="cm-btn cm-btn--ghost" onClick={scrollOn}>See how it works</button>
              </div>
            </div>
            <div className="cm-artwrap">
              <PcbArt className="cm-pcb" />
              <ChipArt className="cm-chip" />
            </div>
          </section>

          {/* 1 · COMPONENTS */}
          <section className="cm-scene" data-i="1">
            <div className="cm-scene-copy">
              <p className="cm-kicker">Components power progress</p>
              <h1>Every product starts with components.</h1>
              <p>Millions of chips. Global suppliers. Complex dependencies.</p>
            </div>
            <div className="cm-artwrap">
              <PcbArt className="cm-pcb" style={{ opacity: 0.35, transform: "translateY(20%)" }} />
              <div className="cm-fall">
                {DROPS.map((d, i) => (
                  <div key={i} className="cm-drop" style={{ left: d.left, top: d.top, transform: `rotate(${d.r}deg)` }}>
                    <MiniChip size={d.s} />
                  </div>
                ))}
              </div>
            </div>
          </section>

          {/* 2 · ASSEMBLY */}
          <section className="cm-scene" data-i="2">
            <div className="cm-scene-copy">
              <p className="cm-kicker">From components to possibility</p>
              <h1>Components come together to build what moves the world.</h1>
              <p>From consumer electronics to automotive, industrial systems and beyond.</p>
            </div>
            <div className="cm-artwrap">
              <PcbArt className="cm-pcb" style={{ opacity: 0.3 }} />
              <div className="cm-beams">{Array.from({ length: 7 }, (_, i) => <i key={i} />)}</div>
              <div className="cm-fall">
                {DROPS.slice(0, 5).map((_, i) => (
                  <div key={i} className="cm-drop" style={{ left: `${44 + (i - 2) * 6}%`, top: `${40 + (i % 2) * 8}%` }}>
                    <MiniChip size={70} />
                  </div>
                ))}
              </div>
              <ChipArt className="cm-chip" style={{ right: "26%" }} />
            </div>
          </section>

          {/* 3 · BOARD ALIVE */}
          <section className="cm-scene" data-i="3">
            <div className="cm-scene-copy">
              <p className="cm-kicker">A complex, interconnected world</p>
              <h1>Thousands of decisions. <span className="accent">One bigger picture.</span></h1>
              <p>Components. Suppliers. Inventory. Demand. All connected.</p>
            </div>
            <div className="cm-artwrap">
              <div className="cm-board-glow" />
              <PcbArt className="cm-pcb" alive />
              <ChipArt className="cm-chip" style={{ right: "20%" }} />
            </div>
          </section>

          {/* 4 · DISRUPTION */}
          <section className="cm-scene" data-i="4">
            <div className="cm-scene-copy">
              <p className="cm-kicker">The world can change overnight</p>
              <h1>But the world is unpredictable.</h1>
              <p>Export restrictions. Supplier risks. Natural disasters. Sudden demand shifts. A single event can disrupt everything downstream.</p>
            </div>
            <div className="cm-worldwrap">
              <div className="cm-worldmap echo" />
              <div className="cm-worldmap" />
              <DisruptionArcs className="cm-arcs" />
              {EVENTS.map((e) => (
                <span key={e.t} className="cm-marker" style={{ left: e.x, top: e.y }} />
              ))}
            </div>
            <div className="cm-events">
              {EVENTS.map((e) => (
                <div key={e.t} className="cm-event">
                  <span className="dot" />
                  <div><b>{e.t}</b><span>{e.d}</span></div>
                </div>
              ))}
            </div>
          </section>

          {/* 5 · CIRCUITMIND RESPONDS */}
          <section className="cm-scene cm-scene--respond" data-i="5">
            <div className="cm-scene-copy">
              <p className="cm-kicker">Turn uncertainty into action</p>
              <h1>CircuitMind detects risk early and recommends <span className="accent">the best action</span>.</h1>
              <ul className="cm-checklist">
                {CHECKS.map((c) => <li key={c}><Check />{c}</li>)}
              </ul>
            </div>
            <div className="cm-insight">
              <span className="tag">Example insight</span>
              <div className="flag">Projected shortage detected</div>
              <dl>
                <dt>Component</dt><dd>KSZ8081RNBIA-TR</dd>
                <dt>Affected product</dt><dd>MC-3000 / SD-220</dd>
                <dt>Shortage</dt><dd>500 units, from 15 Nov</dd>
                <dt>Recommended supplier</dt><dd>Hanwoo Precision Co. Ltd</dd>
                <dt>Estimated cost</dt><dd className="big">$1,008.40</dd>
                <dt>Arrival</dt><dd>16 September — early</dd>
              </dl>
              <button className="cm-btn cm-btn--primary go" onClick={toSignIn}>
                See what&rsquo;s coming. Decide before it hits. →
              </button>
            </div>
          </section>

          {/* 6 · SIGN IN */}
          <section className="cm-scene cm-scene--signin" data-i="6" id="signin">
            <div className="cm-signin">
              <div className="cm-signin-pitch">
                <div className="brand"><Logo />CircuitMind</div>
                <h2>See what&rsquo;s coming.<br />Decide before it hits.</h2>
                <p className="lede">
                  From a global signal to a costed, approvable plan — in one workflow.
                  Sign in to open the dashboard.
                </p>
                <ul>{PITCH.map((p) => <li key={p}><Check />{p}</li>)}</ul>
                <span className="tagline">ANTICIPATE. ADAPT. ALWAYS AHEAD.</span>
              </div>
              <div className="cm-signin-form">
                <div className="cm-signin-card">
                  <h3>Enter CircuitMind</h3>
                  <p className="sub">Recorded against every approval you make.</p>

                  <label htmlFor="cm-name">Name</label>
                  <input
                    id="cm-name" type="text" value={name} placeholder="e.g. A Sujay"
                    autoComplete="off"
                    onChange={(e) => setName(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") signIn(); }}
                  />

                  <label htmlFor="cm-role">Role</label>
                  <select id="cm-role" value={role} onChange={(e) => setRole(e.target.value)}>
                    {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>

                  <button className="cm-btn cm-btn--primary enter" onClick={signIn} disabled={!name.trim()}>
                    Enter dashboard →
                  </button>

                  <p className="demo">
                    <b>Demo sign-in.</b> No password, no account. It names the person in the
                    session so approvals carry a name; it is not an access control.
                  </p>
                </div>
              </div>
            </div>
          </section>

          <div className="cm-scrollhint"><span className="cm-bar" /><span>SCROLL TO EXPLORE</span></div>
          <div className="cm-rail">
            {Array.from({ length: SCENES }, (_, i) => <i key={i} data-on={scene === i} />)}
          </div>
        </div>
      </div>
    </div>
  );
}
