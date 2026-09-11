import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./welcome.css";

export const metadata: Metadata = {
  title: "CircuitMind — See what's coming. Decide before it hits.",
  description:
    "AI-powered intelligence for the semiconductor supply chain. From a global signal to a costed, approvable plan in one workflow.",
};

export default function WelcomeLayout({ children }: { children: ReactNode }) {
  return <div className="cm-landing">{children}</div>;
}
