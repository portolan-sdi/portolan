"use client";

import { useEffect, useState } from "react";

const DWELL_MS = 3000;
const CYCLES = 2;

// Rotates through the hero headline completions, then settles permanently on
// the first phrase after CYCLES full passes. The first phrase is also what
// server rendering and reduced-motion users see, so the headline always reads
// as a complete sentence.
export function HeroRotator({ phrases }: { phrases: string[] }) {
  const [tick, setTick] = useState(0);
  const settled = tick >= phrases.length * CYCLES;
  const active = settled ? 0 : tick % phrases.length;

  useEffect(() => {
    if (settled) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const id = setTimeout(() => setTick((t) => t + 1), DWELL_MS);
    return () => clearTimeout(id);
  }, [tick, settled]);

  return (
    // Stacking every phrase in the same grid cell reserves the width and
    // height of the longest one, so the hero never shifts layout.
    <span className="inline-grid align-bottom">
      {phrases.map((phrase, i) => (
        <span
          key={phrase}
          aria-hidden={i !== active}
          className={`col-start-1 row-start-1 bg-gradient-to-r from-p-grad-a to-p-grad-b bg-clip-text text-transparent transition-[opacity,transform] duration-500 ease-out motion-reduce:transition-none ${
            i === active ? "opacity-100 translate-y-0" : "opacity-0 translate-y-[0.25em]"
          }`}
        >
          {phrase}
        </span>
      ))}
    </span>
  );
}
