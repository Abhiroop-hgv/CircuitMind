"use client";

/**
 * The app shell every page uses: sidebar, topbar, content well.
 *
 * The topbar's right-hand slot is a prop rather than fixed content, because a
 * connection indicator belongs on the overview and a run-status indicator
 * belongs on the pipeline page, and forcing both on every page makes each
 * worse. Questions are asked on the Ask page, not from a topbar box.
 */

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { API, getJSON } from "@/lib/api";
import { Icon } from "@/components/ui";
import { clearSession, initials, readSession, type Person } from "@/lib/session";

const NAV = [
  { href: "/", label: "Overview", icon: "overview" },
  { href: "/events", label: "Events", icon: "events" },
  { href: "/shortages", label: "Shortages", icon: "shortages" },
  { href: "/recommendations", label: "Recommendations", icon: "recommendations", badge: true },
  { href: "/suppliers", label: "Suppliers", icon: "suppliers" },
  { href: "/bom", label: "BOM intake", icon: "bom" },
  { href: "/ask", label: "Ask", icon: "ask" },
];

export function Shell({
  title, crumb, right, children,
}: { title: string; crumb?: ReactNode; right?: ReactNode; children: ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [pending, setPending] = useState<number | null>(null);

  // Undefined means "not looked yet", null means "looked, nobody there". The
  // difference matters: rendering the shell before the check would flash the
  // dashboard at someone on their way to the sign-in page.
  const [who, setWho] = useState<Person | null | undefined>(undefined);

  useEffect(() => {
    const person = readSession();
    setWho(person);
    if (!person) router.replace("/welcome");
  }, [router]);

  useEffect(() => {
    if (!who) return;
    getJSON<{ status: string }[]>("/api/recommendations")
      .then((r) => setPending(r.filter((x) => x.status === "PENDING_APPROVAL").length))
      .catch(() => setPending(null));
  }, [path, who]);

  if (who === undefined) return null;
  if (who === null) return null;   // redirecting

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="mark">
          <img
            src="/circuitmind-logo.png"
            alt="CircuitMind — AI supply-chain intelligence"
            className="mark-logo"
          />
        </div>

        <nav className="nav">
          {NAV.map((n) => {
            const on = n.href === "/" ? path === "/" : path.startsWith(n.href);
            return (
              <Link key={n.href} href={n.href} className={on ? "on" : ""}>
                <Icon name={n.icon} />
                {n.label}
                {n.badge && pending ? <span className="count">{pending}</span> : null}
              </Link>
            );
          })}
        </nav>

        <div className="who">
          <span className="avatar">{initials(who.name)}</span>
          <span className="n">
            <b>{who.name}</b>
            <span>{who.role}</span>
          </span>
          <button
            className="signout"
            title="Sign out"
            onClick={() => { clearSession(); router.replace("/welcome"); }}
          >
            Sign out
          </button>
        </div>
      </aside>

      <div>
        <header className="topbar">
          {crumb}
          <span className="title">{title}</span>
          <div className="right">{right}</div>
        </header>
        <main className="content">{children}</main>
      </div>
    </div>
  );
}

export function ApiDot({ online }: { online: boolean | null }) {
  if (online === null) return null;
  return (
    <span className="note" title={API}>
      <span
        className="pulse"
        style={{
          display: "inline-block", marginRight: 7,
          background: online ? "var(--success)" : "var(--danger)",
          animation: online ? undefined : "none",
        }}
      />
      {online ? "API connected" : "API offline"}
    </span>
  );
}
