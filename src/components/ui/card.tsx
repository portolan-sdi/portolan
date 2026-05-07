import { HTMLAttributes } from "react";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  accent?: string;
}

export function Card({ children, accent, className, style, ...props }: CardProps) {
  return (
    <div
      className={`
        bg-p-paper border border-p-line
        rounded-[var(--p-r-lg)] p-[var(--p-pad-md)]
        shadow-[var(--p-shadow-sm)] relative
        ${className ?? ""}
      `}
      style={{
        ...(accent ? { borderTopWidth: 3, borderTopColor: accent } : {}),
        ...style,
      }}
      {...props}
    >
      {children}
    </div>
  );
}
