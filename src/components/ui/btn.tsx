import { ButtonHTMLAttributes, forwardRef } from "react";

type BtnVariant = "primary" | "secondary" | "ghost";
type BtnSize = "sm" | "md" | "lg";

interface BtnProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: BtnVariant;
  size?: BtnSize;
  asChild?: boolean;
}

const sizeClasses: Record<BtnSize, string> = {
  sm: "px-4 py-2 text-[13px]",
  md: "px-5 py-2.5 text-sm",
  lg: "px-7 py-3.5 text-[15px]",
};

const variantClasses: Record<BtnVariant, string> = {
  primary:
    "bg-gradient-to-b from-p-grad-a to-p-primary text-white border border-p-primary-ink shadow-[inset_0_1px_0_rgba(255,255,255,0.18),var(--p-shadow-sm)]",
  secondary: "bg-p-paper text-p-ink border border-p-line",
  ghost: "bg-transparent text-p-ink-2 border border-transparent",
};

export const Btn = forwardRef<HTMLButtonElement, BtnProps>(
  ({ children, variant = "primary", size = "md", className, ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={`
          inline-flex items-center justify-center gap-2
          rounded-[var(--p-r-md)] font-medium font-sans
          cursor-pointer whitespace-nowrap
          transition-[transform,box-shadow] duration-100
          hover:opacity-90 active:scale-[0.98]
          ${sizeClasses[size]}
          ${variantClasses[variant]}
          ${className ?? ""}
        `}
        {...props}
      >
        {children}
      </button>
    );
  }
);

Btn.displayName = "Btn";
