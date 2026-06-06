// Keeps a pure-Latin token (brand, format name, version, URL, license) left-to-right
// and correctly ordered inside RTL Arabic text. A no-op inside LTR pages.
export function Ltr({ children }: { children: React.ReactNode }) {
  return <span dir="ltr">{children}</span>;
}
