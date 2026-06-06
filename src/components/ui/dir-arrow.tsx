// Decorative inline arrow that mirrors in RTL so it always points in the
// reading-forward direction (→ becomes ←, ↗ becomes ↖). aria-hidden.
export function DirArrow({ kind = "forward" }: { kind?: "forward" | "external" }) {
  return (
    <span aria-hidden className="inline-block rtl:-scale-x-100">
      {kind === "external" ? "↗" : "→"}
    </span>
  );
}
