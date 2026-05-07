interface RhumbBackdropProps {
  opacity?: number;
  color?: string;
  originX?: number;
  originY?: number;
}

export function RhumbBackdrop({
  opacity = 0.18,
  color,
  originX = 50,
  originY = 50,
}: RhumbBackdropProps) {
  const lines = [];
  for (let i = 0; i < 32; i++) {
    const angle = (i / 32) * Math.PI * 2;
    const x2 = originX + Math.cos(angle) * 200;
    const y2 = originY + Math.sin(angle) * 200;
    lines.push(
      <line
        key={i}
        x1={originX}
        y1={originY}
        x2={x2}
        y2={y2}
        stroke={color || "var(--p-primary)"}
        strokeWidth="0.15"
      />
    );
  }

  return (
    <svg
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      className="absolute inset-0 w-full h-full pointer-events-none"
      style={{ opacity }}
    >
      {[8, 16, 24, 32, 40].map((r) => (
        <circle
          key={r}
          cx={originX}
          cy={originY}
          r={r}
          fill="none"
          stroke={color || "var(--p-primary)"}
          strokeWidth="0.12"
        />
      ))}
      {lines}
    </svg>
  );
}
