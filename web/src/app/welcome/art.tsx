"use client";

/**
 * Vector art for the landing story — one file, all inline SVG so each layer can
 * be parallaxed and lit independently and stays crisp at any zoom.
 */

import type { CSSProperties } from "react";

/* ---------------------------------------------------------------- chip --- */
export function ChipArt({ className, style }: { className?: string; style?: CSSProperties }) {
  // 6 chunky gull-wing leads per side — reads as leads, not a dashed edge
  const leads = [88, 128, 168, 208, 248, 288];
  return (
    <svg className={className} style={style} viewBox="0 0 400 400" aria-hidden>
      <defs>
        <linearGradient id="cm-chip-body" x1="0" y1="0" x2="0.4" y2="1">
          <stop offset="0" stopColor="#242b34" />
          <stop offset="0.5" stopColor="#141a21" />
          <stop offset="1" stopColor="#080b0f" />
        </linearGradient>
        <linearGradient id="cm-chip-pin" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#eed69b" />
          <stop offset="0.5" stopColor="#c8a25e" />
          <stop offset="1" stopColor="#6f5731" />
        </linearGradient>
        <radialGradient id="cm-chip-sheen" cx="0.3" cy="0.22" r="0.95">
          <stop offset="0" stopColor="#ffffff" stopOpacity="0.16" />
          <stop offset="0.55" stopColor="#ffffff" stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* leads */}
      <g fill="url(#cm-chip-pin)">
        {leads.map((p) => (
          <g key={p}>
            <rect x={p - 9} y={44} width={18} height={20} rx={3} />
            <rect x={p - 9} y={336} width={18} height={20} rx={3} />
            <rect x={44} y={p - 9} width={20} height={18} rx={3} />
            <rect x={336} y={p - 9} width={20} height={18} rx={3} />
          </g>
        ))}
      </g>

      {/* body */}
      <rect x="58" y="58" width="284" height="284" rx="26" fill="url(#cm-chip-body)"
            stroke="#333c46" strokeWidth="1.5" />
      <path d="M58 90 Q58 58 90 58 H310 Q342 58 342 90 V150 Q200 120 58 150 Z"
            fill="url(#cm-chip-sheen)" />
      <rect x="58" y="58" width="284" height="3" rx="1.5" fill="#7ea6c8" opacity="0.45" />
      {/* pin-1 dot */}
      <circle cx="84" cy="84" r="6" fill="#4a5762" />

      {/* clean 'C' mark */}
      <path d="M232 152 A56 56 0 1 0 232 248" fill="none" stroke="#48545f" strokeWidth="13"
            strokeLinecap="round" />
      <circle cx="238" cy="200" r="9" fill="#48545f" />
      <text x="200" y="300" textAnchor="middle" fontSize="14" letterSpacing="4"
            fill="#4b5763" fontFamily="var(--font-mono), monospace">CIRCUITMIND</text>

      {/* rim light */}
      <rect x="58" y="58" width="284" height="284" rx="26" fill="none"
            stroke="var(--l-cyan)" strokeWidth="1.5" strokeOpacity="0.4" />
    </svg>
  );
}

/* ----------------------------------------------------------------- pcb --- */
export function PcbArt({ className, style, alive = false }: { className?: string; style?: CSSProperties; alive?: boolean }) {
  return (
    <svg className={`${className ?? ""} ${alive ? "is-alive" : ""}`} style={style}
         viewBox="0 0 1200 700" preserveAspectRatio="xMidYMid slice" aria-hidden>
      <defs>
        <linearGradient id="cm-pcb-bg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#0a1119" />
          <stop offset="1" stopColor="#060a10" />
        </linearGradient>
      </defs>
      <rect width="1200" height="700" fill="url(#cm-pcb-bg)" />

      {/* trace grid */}
      <g className="cm-pcb-trace" stroke="#1c3550" strokeWidth="1.4" fill="none">
        {Array.from({ length: 12 }, (_, i) => (
          <path key={`h${i}`} d={`M0 ${40 + i * 56} H${380 + i * 40} l24 24 H1200`} />
        ))}
        {Array.from({ length: 16 }, (_, i) => (
          <path key={`v${i}`} d={`M${60 + i * 74} 0 V${200 + (i % 4) * 60} l24 24 V700`} />
        ))}
      </g>

      {/* glowing traces radiating from the chip seat (~820,350), fade in when alive */}
      <g className="cm-pcb-live" stroke="var(--l-cyan)" strokeWidth="2.6" fill="none"
         strokeLinecap="round">
        <path d="M820 350 H420 l-40 -40 H0" pathLength={1} />
        <path d="M820 350 H1200" pathLength={1} />
        <path d="M820 350 V120 l-30 -30 V0" pathLength={1} />
        <path d="M820 350 V560 l40 40 V700" pathLength={1} />
        <path d="M820 350 L560 130 l0 -40 V0" pathLength={1} />
        <path d="M820 350 L1080 560 l0 40 V700" pathLength={1} />
        <path d="M820 350 L520 470 H120 l-40 40 H0" pathLength={1} />
      </g>

      {/* vias + solder points */}
      <g>
        {[[520, 256], [632, 332], [760, 420], [330, 400], [420, 190]].map(([x, y], i) => (
          <circle key={i} className="cm-pcb-via" cx={x} cy={y} r="6" fill="#0a1119"
                  stroke="var(--l-cyan)" strokeWidth="1.6" />
        ))}
      </g>

      {/* bokeh */}
      <g className="cm-pcb-bokeh">
        {[[120, 90, 30], [980, 140, 44], [1050, 520, 60], [220, 560, 40], [720, 90, 26], [560, 470, 36]].map(([x, y, r], i) => (
          <circle key={i} cx={x} cy={y} r={r}
                  fill={i % 2 ? "var(--l-cyan)" : "var(--l-blue)"} opacity={0.14} />
        ))}
      </g>
    </svg>
  );
}

/* -------------------------------------------------------- falling chip --- */
/* Reads as a solid IC even at ~60px: a lit top face, a few chunky gold leads
   on two sides, a small die. No thin per-pin rects (they alias to dashes). */
export function MiniChip({ size = 96 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 100 100" aria-hidden style={{ overflow: "visible" }}>
      <defs>
        <linearGradient id={`mc-b-${size}`} x1="0" y1="0" x2="0.5" y2="1">
          <stop offset="0" stopColor="#2a323c" />
          <stop offset="0.55" stopColor="#161c23" />
          <stop offset="1" stopColor="#0b0f14" />
        </linearGradient>
      </defs>
      {/* leads — 4 chunky stubs per side */}
      <g fill="#c2a058">
        {[24, 42, 58, 76].map((y) => (
          <g key={y}>
            <rect x={8} y={y - 4} width={12} height={8} rx={1.5} />
            <rect x={80} y={y - 4} width={12} height={8} rx={1.5} />
          </g>
        ))}
      </g>
      {/* body */}
      <rect x="18" y="16" width="64" height="68" rx="9" fill={`url(#mc-b-${size})`} stroke="#333c46" strokeWidth="1.5" />
      {/* lit top face */}
      <path d="M18 25 Q18 16 27 16 H73 Q82 16 82 25 V38 Q50 30 18 38 Z" fill="#ffffff" opacity="0.06" />
      <rect x="18" y="16" width="64" height="2.5" rx="1.5" fill="#7ea6c8" opacity="0.4" />
      {/* die */}
      <rect x="36" y="40" width="28" height="28" rx="4" fill="#1c2530" stroke="#3a5a72" strokeWidth="1" strokeOpacity="0.5" />
      <circle cx="41" cy="45" r="1.6" fill="#4a5762" />
    </svg>
  );
}

/* --------------------------------------------------- disruption arcs --- */
/* the world map itself is a CSS-masked <div> (see .cm-worldmap); this is just
   the glowing links drawn over it. Coordinates are % of the map box. */
export function DisruptionArcs({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 100 60" preserveAspectRatio="none" aria-hidden>
      <g stroke="var(--l-red)" strokeWidth="0.4" fill="none" opacity="0.55" strokeLinecap="round">
        <path d="M74 22 Q60 6 40 26" />
        <path d="M78 30 Q66 40 52 34" />
        <path d="M40 26 Q30 40 24 30" />
      </g>
    </svg>
  );
}
