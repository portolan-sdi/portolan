"use client";

import { useEffect, useState, useSyncExternalStore } from "react";

const TYPE_MS = 55; // per character while typing
const DELETE_MS = 28; // per character while deleting
const HOLD_MS = 1800; // pause on a fully-typed phrase
const GAP_MS = 280; // pause after a phrase is fully deleted

type Phase = "holding" | "deleting" | "typing";

// Reduced-motion as an external store: SSR and the first client render both see
// `false`, so markup matches; it re-reads (and subscribes to changes) on the
// client without a synchronous setState in an effect.
function usePrefersReducedMotion() {
  return useSyncExternalStore(
    (onChange) => {
      const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
      mq.addEventListener("change", onChange);
      return () => mq.removeEventListener("change", onChange);
    },
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    () => false
  );
}

// Typewriter that types each headline completion, holds, deletes, and moves on,
// looping the list. A blinking caret trails the text. Server render and
// reduced-motion users see the first phrase fully typed and still, so the
// headline always reads as a complete sentence.
export function HeroRotator({ phrases }: { phrases: string[] }) {
  const [index, setIndex] = useState(0);
  const [count, setCount] = useState(phrases[0]?.length ?? 0);
  const [phase, setPhase] = useState<Phase>("holding");
  const reduced = usePrefersReducedMotion();

  useEffect(() => {
    if (reduced) return;
    const phrase = phrases[index] ?? "";

    let delay: number;
    if (phase === "holding") delay = HOLD_MS;
    else if (phase === "typing") delay = TYPE_MS;
    else delay = count === 0 ? GAP_MS : DELETE_MS;

    const id = setTimeout(() => {
      if (phase === "holding") {
        setPhase("deleting");
      } else if (phase === "deleting") {
        if (count > 0) {
          setCount((c) => c - 1);
        } else {
          setIndex((i) => (i + 1) % phrases.length);
          setPhase("typing");
        }
      } else {
        // typing
        if (count < phrase.length) {
          setCount((c) => c + 1);
        } else {
          setPhase("holding");
        }
      }
    }, delay);

    return () => clearTimeout(id);
  }, [phase, count, index, phrases, reduced]);

  const visible = reduced ? (phrases[0] ?? "") : (phrases[index] ?? "").slice(0, count);

  return (
    <>
      {/* Stable phrase for assistive tech; the animated text is decorative. */}
      <span className="sr-only">{phrases[0]}</span>
      <span aria-hidden="true" className="text-p-primary">
        {visible}
        {!reduced && (
          <span
            className="ms-0.5 inline-block w-[0.06em] -translate-y-[0.04em] self-stretch bg-p-primary align-baseline"
            style={{
              height: "0.82em",
              verticalAlign: "-0.06em",
              animation: "caret-blink 1.05s steps(1) infinite",
            }}
          />
        )}
      </span>
    </>
  );
}
