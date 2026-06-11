"use client";

import { useTranslations } from "next-intl";
import { DirArrow, Ltr, SectionHead } from "./ui";

// Strips the outer quotation marks from a quote string so we can re-render them
// as accent-colored marks without doubling. The words are unchanged.
function stripOuterQuotes(s: string) {
  return s.replace(/^[“”«»"']+|[“”«»"']+$/g, "");
}

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
      className="px-[var(--p-pad-section-x)] py-[var(--p-pad-section-y)] bg-p-bg-soft border-y border-p-line"
    >
      <div className="max-w-[1240px] mx-auto">
        <SectionHead
          index="05"
          eyebrow={t("eyebrow")}
          title={t("title")}
          subtitle={t("subtitle")}
        />
        <div className="border-t border-p-line-strong">
          {talks.map((talk) => {
            const quote = stripOuterQuotes(t(`items.${talk.key}.quote`));
            return (
              <a
                key={talk.key}
                href={talk.href}
                target="_blank"
                rel="noopener noreferrer"
                className="group block py-[clamp(2.5rem,5vw,4rem)] border-b border-p-line last:border-b-0"
              >
                <div className="grid grid-cols-1 lg:grid-cols-[1fr_1.1fr] gap-7 lg:gap-[clamp(2.5rem,5vw,5rem)] lg:items-center">
                  <blockquote className="text-section-sm font-bold tracking-[-0.03em] leading-[1.12] text-p-ink">
                    <span className="text-p-primary">“</span>
                    {quote}
                    <span className="text-p-primary">”</span>
                  </blockquote>
                  <div>
                    <h3 className="text-card-title-lg font-bold tracking-[-0.02em] mb-3 transition-colors group-hover:text-p-primary">
                      <Ltr>{t(`items.${talk.key}.title`)}</Ltr> <DirArrow kind="external" />
                    </h3>
                    <div className="font-mono text-small text-p-ink-3 mb-4 tracking-[0.02em]">
                      <Ltr>{t(`items.${talk.key}.attribution`)}</Ltr>
                    </div>
                    <p className="text-body-lg leading-relaxed max-w-[640px]">
                      {t(`items.${talk.key}.description`)}
                    </p>
                  </div>
                </div>
              </a>
            );
          })}
        </div>
      </div>
    </section>
  );
}
