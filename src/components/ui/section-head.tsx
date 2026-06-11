import { ReactNode } from "react";

interface SectionHeadProps {
  /** Presentational two-digit index, e.g. "01". Rendered before the eyebrow. */
  index: string;
  /** Eyebrow label (from translations). */
  eyebrow: string;
  /** Section title (from translations). */
  title: ReactNode;
  /** Supporting copy shown in the right column on wide screens. */
  subtitle?: ReactNode;
  /** Replaces the subtitle with arbitrary content (e.g. a CTA), bottom-right. */
  aside?: ReactNode;
}

// Editorial section header: title block on the start side, supporting copy (or a
// CTA) on the end side, bottom-aligned on wide screens. Mirrors the mockup's
// `.sec-head`. The `index ·` prefix is presentational; the label is translated.
export function SectionHead({
  index,
  eyebrow,
  title,
  subtitle,
  aside,
}: SectionHeadProps) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_minmax(0,46ch)] gap-5 md:gap-12 md:items-end mb-[clamp(2.5rem,5vw,4rem)]">
      <div>
        <div className="font-mono text-eyebrow text-p-ink-3 tracking-[0.04em]">
          <span aria-hidden="true">{index} · </span>
          {eyebrow}
        </div>
        <h2 className="text-section font-extrabold tracking-[-0.03em] leading-[1.05] mt-3 max-w-[32ch] text-balance">
          {title}
        </h2>
      </div>
      {aside ? (
        <div className="md:justify-self-end">{aside}</div>
      ) : subtitle ? (
        <p className="text-body-lg leading-relaxed text-p-ink-2">{subtitle}</p>
      ) : null}
    </div>
  );
}
