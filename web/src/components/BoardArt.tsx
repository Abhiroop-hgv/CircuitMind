"use client";

/**
 * The picture on the sign-in page.
 *
 * Drawn rather than photographed, and drawn to say something: a board, with one
 * component flagged and an arrow to what replaces it. That is the product in a
 * glance -- not "supply chain" in the abstract, but a specific part on a
 * specific board that a specific event put at risk.
 *
 * Inline SVG rather than an image file: no asset to load or lose, sharp at any
 * size, and every colour is a CSS token rather than a literal. The app has only
 * a light palette today, so there is nothing for it to follow yet -- but when a
 * dark one is added this picture comes with it, instead of being a rectangle of
 * the wrong colour that someone has to notice and fix.
 */

export function BoardArt() {
  return (
    <svg
      className="board-art"
      viewBox="0 0 360 250"
      role="img"
      aria-label="A circuit board with one component flagged as at risk and an arrow to its verified replacement"
    >
      {/* the board */}
      <rect x="14" y="46" width="332" height="176" rx="10"
            fill="var(--surface-2)" stroke="var(--border)" strokeWidth="1.5" />

      {/* copper traces */}
      <g stroke="var(--border)" strokeWidth="1.2" fill="none" opacity="0.85">
        <path d="M40 92h44v34h52" />
        <path d="M40 150h30v42h70" />
        <path d="M236 92h60v46h-34" />
        <path d="M150 196h96v-30h50" />
        <path d="M96 74v-14h120v14" />
      </g>
      <g fill="var(--border)">
        {[[84, 92], [136, 126], [70, 150], [140, 192], [296, 92], [262, 138], [246, 196]]
          .map(([x, y], i) => <circle key={i} cx={x} cy={y} r="2.4" />)}
      </g>

      {/* the part at risk */}
      <g>
        <rect x="96" y="104" width="74" height="58" rx="5"
              fill="var(--danger-soft)" stroke="var(--danger)" strokeWidth="1.8" />
        <g stroke="var(--danger)" strokeWidth="1.6" opacity="0.75">
          {[0, 1, 2, 3].map((i) => (
            <line key={`l${i}`} x1="88" y1={116 + i * 12} x2="96" y2={116 + i * 12} />
          ))}
          {[0, 1, 2, 3].map((i) => (
            <line key={`r${i}`} x1="170" y1={116 + i * 12} x2="178" y2={116 + i * 12} />
          ))}
        </g>
        <text x="133" y="129" textAnchor="middle" className="ref">U1</text>
        <text x="133" y="145" textAnchor="middle" className="mpn">STM32F407</text>
      </g>

      {/* the replacement */}
      <g>
        <rect x="248" y="104" width="74" height="58" rx="5"
              fill="var(--success-soft)" stroke="var(--success)" strokeWidth="1.8" />
        <g stroke="var(--success)" strokeWidth="1.6" opacity="0.75">
          {[0, 1, 2, 3].map((i) => (
            <line key={`l${i}`} x1="240" y1={116 + i * 12} x2="248" y2={116 + i * 12} />
          ))}
          {[0, 1, 2, 3].map((i) => (
            <line key={`r${i}`} x1="322" y1={116 + i * 12} x2="330" y2={116 + i * 12} />
          ))}
        </g>
        <text x="285" y="129" textAnchor="middle" className="ref">U1</text>
        <text x="285" y="145" textAnchor="middle" className="mpn">STM32F429</text>
      </g>

      {/* the substitution */}
      <g stroke="var(--accent)" strokeWidth="2" fill="none">
        <path d="M186 133h44" strokeDasharray="4 4" />
        <path d="M230 133l-8-5m8 5l-8 5" />
      </g>
      <text x="208" y="122" textAnchor="middle" className="tag">verified</text>

      {/* the notice that started it */}
      <g>
        <rect x="14" y="6" width="196" height="30" rx="6"
              fill="var(--surface)" stroke="var(--border-soft)" />
        <circle cx="30" cy="21" r="5" fill="var(--danger)" opacity="0.85" />
        <text x="44" y="19" className="tag">Export licence notice</text>
        <text x="44" y="30" className="tag dim">China &middot; 2 September</text>
      </g>
      <path d="M60 36v10" stroke="var(--danger)" strokeWidth="1.6"
            strokeDasharray="3 3" opacity="0.7" />

      {/* the consequence */}
      <text x="346" y="26" textAnchor="end" className="figure">5,130 short</text>
      <text x="346" y="38" textAnchor="end" className="tag dim">by 15 October</text>
    </svg>
  );
}
