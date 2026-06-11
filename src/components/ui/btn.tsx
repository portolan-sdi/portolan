import { ButtonHTMLAttributes, forwardRef } from "react";

type BtnVariant = "primary" | "secondary" | "ghost";
type BtnSize = "sm" | "md" | "lg";

interface BtnProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: BtnVariant;
  size?: BtnSize;
  asChild?: boolean;
}

const sizeClasses: Record<BtnSize, string> = {
  sm: "px-4 py-2 text-small",
  md: "px-5 py-2.5 text-body-lg",
  lg: "px-6 py-3 text-body-lg",
};

const variantClasses: Record<BtnVariant, string> = {
  primary: "bg-p-primary text-p-on-primary hover:bg-p-primary-ink",
  secondary: "bg-p-paper text-p-ink border border-p-line hover:bg-p-bg-soft",
  ghost:
    "bg-transparent text-p-ink rounded-none border-b-2 border-transparent hover:border-p-ink",
};

export const Btn = forwardRef<HTMLButtonElement, BtnProps>(
  ({ children, variant = "primary", size = "md", className, ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={`
          inline-flex items-center justify-center gap-2
          rounded-[var(--p-r-md)] font-semibold font-sans
          cursor-pointer whitespace-nowrap
          transition-[background-color,border-color,color] duration-150
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
