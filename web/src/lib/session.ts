/**
 * Who is signed in.
 *
 * This is a demo sign-in, and the code says so rather than implying otherwise.
 * There is no password, no server-side session and no authorisation: anyone who
 * can reach the page can enter any name. It exists for two honest reasons.
 *
 *   1. A dashboard that opens straight onto someone else's inventory has no
 *      sense of "you". Naming the viewer costs nothing and frames the rest.
 *   2. Approving a recommendation records WHO approved it. That was a free-text
 *      box anyone could type anything into. Taking the name from the session is
 *      a slightly better record of a decision, and it is one less thing to type
 *      on stage.
 *
 * Kept in localStorage, which is per-browser and never reaches the server. Every
 * access is wrapped: a private window, cleared site data or a browser set to
 * block storage all make these throw rather than return null.
 */

const KEY = "overlay.session";

export interface Person {
  name: string;
  role: string;
}

export const ROLES = [
  "Procurement lead",
  "Supply planner",
  "Design engineer",
  "Operations manager",
];

export function readSession(): Person | null {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<Person>;
    if (!parsed?.name?.trim()) return null;
    return { name: parsed.name, role: parsed.role || ROLES[1] };
  } catch {
    return null;
  }
}

export function writeSession(person: Person): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(person));
  } catch {
    // Storage unavailable. The sign-in still works for this page view; it just
    // will not survive a reload. Better than refusing to let anyone in.
  }
}

export function clearSession(): void {
  try {
    window.localStorage.removeItem(KEY);
  } catch {
    /* nothing to do */
  }
}

/** "A Sujay" -> "AS". Used for the sidebar avatar. */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}
