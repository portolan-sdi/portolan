interface PortolanLogoProps {
  size?: number;
  withWordmark?: boolean;
  className?: string;
}

export function PortolanLogo({
  size = 28,
  withWordmark = true,
  className,
}: PortolanLogoProps) {
  return (
    <span
      className={`inline-flex items-center gap-2.5 text-p-ink ${className ?? ""}`}
    >
      <svg
        width={size}
        height={size}
        viewBox="0 0 32 32"
        aria-hidden="true"
        className="block"
      >
        <g fill="var(--p-primary)">
          <path d="M2.83 18.247l26.34-9.124L2.83 0z" />
          <path d="M29.17 32V13.753L2.83 22.877z" />
        </g>
      </svg>
      {withWordmark && (
        <span
          className="font-semibold font-sans"
          style={{
            fontSize: size * 0.85,
            letterSpacing: "-0.015em",
          }}
        >
          Portolan
        </span>
      )}
    </span>
  );
}
