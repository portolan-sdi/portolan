"use client";

import { useTranslations } from "next-intl";
import { Card, DirArrow, Ltr } from "./ui";

const resources = [
  { key: "holmesTalk", href: "https://cholmes.github.io/open-geodag-presentation/" },
  { key: "calculator", href: "https://cholmes.github.io/open-geodag-presentation/calculator.html" },
  { key: "parksBuildings", href: "https://cholmes.github.io/open-geodag-presentation/parks_buildings.html" },
  { key: "monuments", href: "https://cholmes.github.io/open-geodag-presentation/monuments.html" },
  { key: "nextSdi", href: "https://jatorre.github.io/carto-ogc-helsinki/" },
  { key: "finlandAgent", href: "https://jatorre.github.io/carto-ogc-helsinki/webapp/" },
  { key: "nlDemo", href: "https://portolan-sdi.github.io/portolan-nl-demo" },
  { key: "github", href: "https://github.com/portolan-sdi" },
] as const;

export function ResourcesSection() {
  const t = useTranslations("resources");

  return (
    <section
      id="resources"
      className="px-[var(--p-pad-section-x)] py-[var(--p-pad-section-y)] bg-p-bg-soft border-t border-p-line-soft"
    >
      <div className="max-w-[1240px] mx-auto">
        <span className="font-mono text-eyebrow text-p-ink-3 tracking-[0.08em]">
          {t("eyebrow")}
        </span>
        <h2 className="text-section mt-1.5 mb-3 font-semibold tracking-[-0.02em]">
          {t("title")}
        </h2>
        <p className="text-body-lg leading-relaxed max-w-[720px] mb-10">
          {t("subtitle")}
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
          {resources.map((resource) => (
            <a
              key={resource.key}
              href={resource.href}
              target="_blank"
              rel="noopener noreferrer"
              className="contents"
            >
              <Card className="flex flex-col gap-3 transition-shadow hover:shadow-[var(--p-shadow-md)]">
                <div className="font-mono text-eyebrow text-p-primary-ink">
                  <Ltr>{t(`items.${resource.key}.attribution`)}</Ltr>
                </div>
                <h3 className="text-card-title font-semibold">
                  <Ltr>{t(`items.${resource.key}.title`)}</Ltr>
                </h3>
                <p className="text-body leading-relaxed">
                  {t(`items.${resource.key}.description`)}
                </p>
                <span className="mt-auto text-small text-p-primary">
                  <DirArrow kind="external" />
                </span>
              </Card>
            </a>
          ))}
        </div>
      </div>
    </section>
  );
}
