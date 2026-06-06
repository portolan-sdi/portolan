import "./globals.css";

// All routes are localized under [locale], which owns <html>/<body> so it can
// set lang/dir per locale. This root layout stays as a required pass-through
// (root-level not-found needs a root layout).
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return children;
}
