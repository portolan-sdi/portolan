"use client";

import { useEffect, useState } from "react";

interface LiveCountProps {
  target?: number;
  durationMs?: number;
}

export function LiveCount({ target = 142, durationMs = 1400 }: LiveCountProps) {
  const [n, setN] = useState(0);

  useEffect(() => {
    const start = performance.now();
    let raf: number;

    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / durationMs);
      const eased = 1 - Math.pow(1 - p, 3);
      setN(Math.round(target * eased));
      if (p < 1) raf = requestAnimationFrame(tick);
    };

    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, durationMs]);

  return <span className="tabular-nums">{n}</span>;
}
