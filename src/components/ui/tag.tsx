import { HTMLAttributes } from "react";

type TagTone = "default" | "primary" | "accent";

interface TagProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: TagTone;
}

const toneClasses: Record<TagTone, string> = {
  default: "bg-p-bg-soft text-p-ink-2 border-p-line",
  primary:
    "bg-[color-mix(in_oklab,var(--p-primary)_12%,transparent)] text-p-primary-ink border-[color-mix(in_oklab,var(--p-primary)_25%,transparent)]",
  accent:
    "bg-[color-mix(in_oklab,var(--p-accent)_18%,transparent)] text-p-accent-ink border-[color-mix(in_oklab,var(--p-accent)_35%,transparent)]",
};

export function Tag({
  children,
  tone = "default",
  className,
  ...props
}: TagProps) {
  return (
    <span
      className={`
        inline-flex items-center gap-2
        text-eyebrow font-mono
        px-2.5 py-1 rounded-[var(--p-r-sm)]
        tracking-[0.02em] uppercase
        border
        ${toneClasses[tone]}
        ${className ?? ""}
      `}
      {...props}
    >
      {children}
    </span>
  );
}
