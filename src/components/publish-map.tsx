interface PublishMapProps {
  height?: number;
}

const W = 64;
const H = 32;

const land = [
  "0000000000000000000000000000000000000000000000000000000000000000",
  "0000011111111111111100011111111111111111111111111111111100000000",
  "0000111111111111111111111111111111111111111111111111111100000000",
  "0001111111111111111111111111111111111111111111111111111100000000",
  "0011111111111111111111111111111111111111111111111111111100000000",
  "0001111111111111111111111111111111111111111111111111111000000000",
  "0001111111111111111111111111111111111111111111110000000000000000",
  "0011111111111111111111111111111111111111111110000000000000000000",
  "0001111111111111111100001111111111111111100000000000000000000000",
  "0000011111111111100000001111111111111100000000000000000000000000",
  "0000001111111110000000001111111111100000000000000000000000000000",
  "0000000111111000000000001111111100000000000000000000000000000000",
  "0000000011110000000000000111111000000000000000000000000000000000",
  "0000000001100000000000000011111100000000000000000000000000000000",
  "0000000000110000000000000011111100000000000000000000000000000000",
  "0000000000110000000000000011111100000000000000000000000000000000",
  "0000000000011000000000000001111100000000000000000000000000000000",
  "0000000000011100000000000001111000000000000000000000000000000000",
  "0000000000001110000000000001111000000000000000000000000000000000",
  "0000000000001110000000000001110000000000000000000000000000000000",
  "0000000000000110000000000001100000000000000000000000000000000000",
  "0000000000000010000000000001100000000000000000011000000000000000",
  "0000000000000010000000000000100000000000000011111100000000000000",
  "0000000000000000000000000000000000000000000111111000000000000000",
  "0000000000000000000000000000000000000000000111110000000000000000",
  "0000000000000000000000000000000000000000000011000000000000000000",
  "0000000000000000000000000000000000000000000001000000000000000000",
  "0000000000000000000000000000000000000000000000000000000000000000",
  "0000000000000000000000000000000000000000000000000000000000000000",
  "0000000000000000000000000000000000000000000000000000000000000000",
  "0000000000000000000000000000000000000000000000000000000000000000",
  "0000000000000000000000000000000000000000000000000000000000000000",
];

const nodes = [
  { x: 18, y: 38, l: "Pacific NW Lidar", o: "d" },
  { x: 22, y: 56, l: "Andean Glaciers", o: "glaciares.cl" },
  { x: 36, y: 30, l: "Madrid Open Data", o: "datos.madrid.es" },
  { x: 38, y: 20, l: "Nordic Hydro", o: "hydro.no" },
  { x: 52, y: 48, l: "Red Sea Reefs", o: "redsea.org" },
  { x: 79, y: 44, l: "Coastal Bathymetry", o: "data.gov.tw" },
  { x: 70, y: 32, l: "Mongolia DEMs", o: "mongoliadata.gov" },
  { x: 86, y: 64, l: "GBR Reef Atlas", o: "gbrmpa.gov.au" },
  { x: 30, y: 70, l: "Atlantic SST", o: "noaa.gov" },
];

const connections = [
  [0, 5],
  [5, 7],
  [2, 4],
  [3, 2],
  [6, 5],
  [8, 0],
];

export function PublishMap({ height = 460 }: PublishMapProps) {
  const dots: { x: number; y: number }[] = [];
  const cellW = 100 / W;
  const cellH = 100 / H;

  for (let yy = 0; yy < H; yy++) {
    for (let xx = 0; xx < W; xx++) {
      if (land[yy] && land[yy][xx] === "1") {
        dots.push({ x: xx * cellW + cellW / 2, y: yy * cellH + cellH / 2 });
      }
    }
  }

  return (
    <div
      className="relative bg-p-paper rounded-[var(--p-r-lg)] border border-p-line overflow-hidden shadow-[var(--p-shadow-md)] font-mono"
      style={{ height }}
    >
      {/* Header strip */}
      <div className="absolute top-0 left-0 right-0 z-10 px-4 py-3 flex justify-between items-center text-[11px] text-p-ink-3 border-b border-p-line-soft bg-gradient-to-b from-p-paper to-transparent">
        <span className="tracking-[0.08em] uppercase">
          // PUBLISHED CATALOGS · WORLD
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-p-accent shadow-[0_0_8px_var(--p-accent)]" />
          {nodes.length} live · updated 4m ago
        </span>
      </div>

      {/* Map */}
      <svg
        viewBox="0 0 100 60"
        preserveAspectRatio="xMidYMid meet"
        className="absolute inset-0 w-full h-full"
      >
        {/* Land dots */}
        {dots.map((d, i) => (
          <circle
            key={i}
            cx={d.x}
            cy={d.y * 0.6}
            r="0.32"
            fill="var(--p-ink-3)"
            opacity="0.55"
          />
        ))}

        {/* Equator line */}
        <line
          x1="0"
          y1="30"
          x2="100"
          y2="30"
          stroke="var(--p-primary)"
          strokeWidth="0.08"
          opacity="0.3"
          strokeDasharray="0.5,0.5"
        />

        {/* Connection lines between nodes */}
        {connections.map(([a, b], i) => {
          const A = nodes[a];
          const B = nodes[b];
          const mx = (A.x + B.x) / 2;
          const my = Math.min(A.y, B.y) * 0.6 - 4;
          return (
            <path
              key={`l${i}`}
              d={`M ${A.x} ${A.y * 0.6} Q ${mx} ${my} ${B.x} ${B.y * 0.6}`}
              fill="none"
              stroke="var(--p-primary)"
              strokeWidth="0.18"
              opacity="0.28"
              strokeDasharray="0.6,0.6"
            />
          );
        })}

        {/* Nodes */}
        {nodes.map((n, i) => (
          <g key={i}>
            <circle cx={n.x} cy={n.y * 0.6} r="1.6" fill="var(--p-accent)" opacity="0.18">
              <animate
                attributeName="r"
                values="1.4;2.6;1.4"
                dur="2.6s"
                begin={`${i * 0.3}s`}
                repeatCount="indefinite"
              />
              <animate
                attributeName="opacity"
                values="0.3;0;0.3"
                dur="2.6s"
                begin={`${i * 0.3}s`}
                repeatCount="indefinite"
              />
            </circle>
            <circle
              cx={n.x}
              cy={n.y * 0.6}
              r="0.8"
              fill="var(--p-accent)"
              stroke="var(--p-paper)"
              strokeWidth="0.15"
            />
          </g>
        ))}
      </svg>

      {/* Footer overlay */}
      <div className="absolute bottom-0 left-0 right-0 z-10 px-4 py-3 bg-gradient-to-t from-p-paper via-p-paper/60 to-transparent grid grid-cols-3 gap-x-4 gap-y-1 text-[10.5px] text-p-ink-2">
        {nodes.slice(0, 6).map((n, i) => (
          <div key={i} className="flex items-center gap-1.5 min-w-0">
            <span className="w-[5px] h-[5px] rounded-full bg-p-accent shrink-0" />
            <span className="overflow-hidden text-ellipsis whitespace-nowrap">
              <span className="text-p-ink">{n.l}</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
