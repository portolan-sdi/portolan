"use client";

import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Link, usePathname } from "@/i18n/navigation";
import { routing, type Locale } from "@/i18n/routing";

// Native language names are always shown in their own language, so they are not
// translated. Order follows routing.locales (en, es, ar).
const NATIVE_NAMES: Record<Locale, string> = {
  en: "English",
  es: "Español",
  ar: "العربية",
};

export function LocaleSwitcher() {
  const t = useTranslations();
  const locale = useLocale() as Locale;
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;

    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    }
    function onPointerDown(e: PointerEvent) {
      if (!wrapperRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [open]);

  return (
    <div ref={wrapperRef} className="relative">
      <button
        ref={buttonRef}
        type="button"
        aria-label={t("nav.languageAria")}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls="locale-menu"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 h-8 px-2 rounded-[var(--p-r-md)] text-small text-p-ink-2 transition-colors hover:bg-p-bg-soft hover:text-p-ink"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="10" />
          <line x1="2" y1="12" x2="22" y2="12" />
          <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
        </svg>
        <span dir="ltr">{locale.toUpperCase()}</span>
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
          className={`transition-transform ${open ? "rotate-180" : ""}`}
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {open ? (
        <div
          id="locale-menu"
          role="menu"
          className="absolute end-0 top-full mt-2 min-w-40 py-1 rounded-[var(--p-r-md)] border border-p-line-soft bg-p-bg shadow-[var(--p-shadow-md)] text-small z-50"
        >
          {routing.locales.map((loc) => {
            const isActive = loc === locale;
            return (
              <Link
                key={loc}
                href={pathname}
                locale={loc}
                role="menuitem"
                aria-current={isActive ? "true" : undefined}
                dir={loc === "ar" ? "rtl" : "ltr"}
                onClick={() => setOpen(false)}
                className={`flex items-center justify-between gap-3 px-3 py-2 transition-colors hover:bg-p-bg-soft ${
                  isActive ? "text-p-ink" : "text-p-ink-2 hover:text-p-ink"
                }`}
              >
                <span>{NATIVE_NAMES[loc]}</span>
                {isActive ? (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M20 6L9 17l-5-5" />
                  </svg>
                ) : null}
              </Link>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
