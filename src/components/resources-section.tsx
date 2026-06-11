"use client";

import { useTranslations } from "next-intl";
import { DirArrow, Ltr } from "./ui";

// Exactly two talks. The demos, the cost calculator, and the example catalogs
// are linked elsewhere on the page or from inside these decks — resist adding
// more entries here.
const talks = [
  { key: "holmesTalk", href: "https://cholmes.github.io/open-geodag-presentation/" },
  { key: "nextSdi", href: "https://jatorre.github.io/carto-ogc-helsinki/" },
] as const;

export function ResourcesSection() {
  const t = useTranslations("resources");

  return (
    <section
      id="resources"
      className="px-[var(--p-pad-section-x)] py-[var(--p-pad-section-y)] border-y border-p-line-soft"
    >
      <div className="max-w-[1240px] mx-auto">
        <span className="font-mono text-eyebrow text-p-ink-3 tracking-[0.08em]">
          {t("eyebrow")}
        </span>
        <h2 className="text-section mt-1.5 mb-3 font-semibold tracking-[-0.02em]">
          {t("title")}
        </h2>
        <p className="text-body-lg leading-relaxed max-w-[720px] mb-12">
          {t("subtitle")}
        </p>
        <div>
          {talks.map((talk) => (
            <a
              key={talk.key}
              href={talk.href}
              target="_blank"
              rel="noopener noreferrer"
              className="group block py-10 border-t border-p-line"
            >
              <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] gap-6 lg:gap-12 items-start">
                <div>
                  <div className="font-mono text-eyebrow text-p-primary-ink mb-3">
                    <Ltr>{t(`items.${talk.key}.attribution`)}</Ltr>
                  </div>
                  <h3 className="text-feature font-semibold tracking-[-0.02em] mb-3 transition-colors group-hover:text-p-primary">
                    <Ltr>{t(`items.${talk.key}.title`)}</Ltr> <DirArrow kind="external" />
                  </h3>
                  <p className="text-body-lg leading-relaxed max-w-[640px]">
                    {t(`items.${talk.key}.description`)}
                  </p>
                </div>
                <blockquote className="border-s-2 border-p-accent ps-5 text-card-title-lg leading-snug text-p-ink-2">
                  {t(`items.${talk.key}.quote`)}
                </blockquote>
              </div>
            </a>
          ))}
        </div>
      </div>
    </section>
  );
}
