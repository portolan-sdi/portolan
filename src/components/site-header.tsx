"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { PortolanLogo } from "./portolan-logo";
import { ThemeToggle } from "./theme-toggle";

const navLinks = [
  { href: "/#why", key: "why" },
  { href: "/#how", key: "howItWorks" },
  { href: "/#tools", key: "tools" },
  {
    href: "https://portolan-sdi.github.io/portolan-cli",
    key: "docs",
    external: true,
  },
] as const;

export function SiteHeader() {
  const t = useTranslations();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <header className="relative border-b border-p-line-soft">
      <div className="flex items-center justify-between px-[var(--p-pad-section-x)] py-4">
        <Link href="/" aria-label="Portolan home">
          <PortolanLogo size={28} />
        </Link>
        <nav className="hidden md:flex gap-7 text-small text-p-ink-2">
          {navLinks.map((link) => {
            const isExternal = "external" in link && link.external;
            const className = "text-inherit hover:text-p-ink transition-colors";
            const label = `${t(`nav.${link.key}`)}${isExternal ? " ↗" : ""}`;
            return isExternal ? (
              <a key={link.key} href={link.href} className={className}>
                {label}
              </a>
            ) : (
              <Link key={link.key} href={link.href} className={className}>
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <a
            href="https://github.com/portolan-sdi"
            aria-label="GitHub"
            className="inline-flex items-center justify-center w-8 h-8 rounded-[var(--p-r-md)] text-p-ink-2 transition-colors hover:bg-p-bg-soft hover:text-p-ink"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.58.1.79-.25.79-.56v-2c-3.2.7-3.87-1.36-3.87-1.36-.52-1.33-1.28-1.69-1.28-1.69-1.05-.71.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.18 1.18a11.07 11.07 0 015.79 0c2.21-1.49 3.18-1.18 3.18-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.84 1.19 3.1 0 4.42-2.69 5.39-5.25 5.68.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56C20.21 21.39 23.5 17.08 23.5 12 23.5 5.65 18.35.5 12 .5z" />
            </svg>
          </a>
          <button
            type="button"
            aria-label="Toggle menu"
            aria-expanded={open}
            aria-controls="mobile-nav"
            onClick={() => setOpen((v) => !v)}
            className="md:hidden inline-flex items-center justify-center w-8 h-8 rounded-[var(--p-r-md)] text-p-ink-2 transition-colors hover:bg-p-bg-soft hover:text-p-ink"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              {open ? (
                <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
              ) : (
                <path d="M3 6h18M3 12h18M3 18h18" strokeLinecap="round" />
              )}
            </svg>
          </button>
        </div>
      </div>
      <nav
          id="mobile-nav"
          className={`md:hidden flex-col px-[var(--p-pad-section-x)] pb-4 gap-1 border-t border-p-line-soft bg-p-bg ${open ? "flex" : "hidden"}`}
        >
          {navLinks.map((link) => {
            const isExternal = "external" in link && link.external;
            const className =
              "py-2.5 text-body-lg text-p-ink-2 hover:text-p-ink transition-colors";
            const label = `${t(`nav.${link.key}`)}${isExternal ? " ↗" : ""}`;
            return isExternal ? (
              <a
                key={link.key}
                href={link.href}
                onClick={() => setOpen(false)}
                className={className}
              >
                {label}
              </a>
            ) : (
              <Link
                key={link.key}
                href={link.href}
                onClick={() => setOpen(false)}
                className={className}
              >
                {label}
              </Link>
            );
          })}
        </nav>
    </header>
  );
}
