interface MapPreviewProps {
  height?: number;
  className?: string;
}

export function MapPreview({ height = 360, className }: MapPreviewProps) {
  return (
    <div
      className={`
        relative overflow-hidden
        bg-gradient-to-br from-[#1a2657] to-[#2a3a7a]
        rounded-[var(--p-r-lg)] border border-p-line
        shadow-[var(--p-shadow-md)]
        ${className ?? ""}
      `}
      style={{ height }}
    >
      {/* Graticule */}
      <svg
        viewBox="0 0 600 360"
        preserveAspectRatio="none"
        className="absolute inset-0 w-full h-full"
      >
        {[60, 120, 180, 240, 300].map((y) => (
          <line
            key={`h${y}`}
            x1="0"
            y1={y}
            x2="600"
            y2={y}
            stroke="#5775d6"
            strokeWidth="0.5"
            opacity="0.25"
          />
        ))}
        {[100, 200, 300, 400, 500].map((x) => (
          <line
            key={`v${x}`}
            x1={x}
            y1="0"
            x2={x}
            y2="360"
            stroke="#5775d6"
            strokeWidth="0.5"
            opacity="0.25"
          />
        ))}
        {/* Stylized landmass shapes */}
        <path
          d="M 80 90 Q 140 70 200 100 T 320 110 Q 380 95 420 130 L 410 200 Q 360 220 290 215 T 180 200 Q 120 195 80 180 Z"
          fill="#395eca"
          opacity="0.5"
          stroke="#848bd8"
          strokeWidth="0.8"
        />
        <path
          d="M 440 180 Q 500 175 540 210 L 535 270 Q 480 280 450 260 Z"
          fill="#395eca"
          opacity="0.4"
          stroke="#848bd8"
          strokeWidth="0.8"
        />
        <path
          d="M 100 240 Q 160 230 220 250 L 210 310 Q 150 315 100 300 Z"
          fill="#395eca"
          opacity="0.45"
          stroke="#848bd8"
          strokeWidth="0.8"
        />
        {/* Data points */}
        {Array.from({ length: 35 }).map((_, i) => {
          const x = 60 + ((i * 53.7) % 500);
          const y = 80 + ((i * 31.3) % 240);
          const r = 1.5 + (i % 4) * 0.8;
          return (
            <circle key={i} cx={x} cy={y} r={r} fill="#f4b860" opacity="0.85" />
          );
        })}
      </svg>
      <div className="absolute bottom-3 left-3.5 font-mono text-[11px] text-[#c5cce8] tracking-[0.06em] uppercase">
        Live node · 3 collections · 1.2 TB
      </div>
      <div className="absolute top-3 right-3.5 font-mono text-[11px] text-p-accent tracking-[0.06em] flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-p-accent shadow-[0_0_8px_var(--p-accent)]" />
        LIVE
      </div>
    </div>
  );
}
