"use client";

import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { RhumbBackdrop } from "./rhumb-backdrop";
import { DitherMap } from "./dither-map";
import { SiteHeader } from "./site-header";
import { SiteFooter } from "./site-footer";
import { Btn, Tag, Card, Terminal } from "./ui";

const terminalLines = [
  { text: "# Convert a folder of shapefiles + tiffs to a portable catalog", color: "#5775d6" },
  { text: "$ portolan ingest ./gov-data --to s3://my-catalog", color: "#c5cce8" },
  { text: "", color: "#c5cce8" },
  { text: "  ✓ scanned 142 files (3.2 GB)", color: "#848bd8" },
  { text: "  → land_parcels.shp        →  GeoParquet (412 MB)", color: "#c5cce8" },
  { text: "  → ortho_2024.tif          →  COG (2.1 GB)", color: "#c5cce8" },
  { text: "  → roads_centerlines.shp   →  GeoParquet (84 MB)", color: "#c5cce8" },
  { text: "  → ... 11 more", color: "#8d96bd" },
  { text: "", color: "#c5cce8" },
  { text: "  ✓ STAC catalog generated  (catalog.json + 14 collections)", color: "#848bd8" },
  { text: "  ✓ synced to s3://my-catalog (1.4 GB compressed)", color: "#848bd8" },
  { text: "", color: "#c5cce8" },
  { text: "  ▸ catalog.json: https://my-catalog.s3.amazonaws.com/catalog.json", color: "#f4b860" },
  { text: "  ▸ STAC browser: https://radiantearth.github.io/stac-browser/...", color: "#f4b860" },
  { text: "", color: "#c5cce8" },
  { text: "  done · 0:48 elapsed", color: "#28c840" },
];

export function HomePage() {
  const t = useTranslations();

  const whyCards = [
    { key: "open", id: "01" },
    { key: "aiReady", id: "02" },
    { key: "cheap", id: "03" },
    { key: "sovereign", id: "04" },
    { key: "scales", id: "05" },
    { key: "breaks", id: "06" },
  ] as const;

  const howSteps = [
    "convert",
    "catalog",
    "publish",
    "browse",
  ] as const;

  return (
    <div className="bg-p-bg min-h-full font-sans">
      {/* Header */}
      <SiteHeader />

      {/* Hero */}
      <section className="relative min-h-[88svh] md:min-h-[85vh] flex items-center border-b border-p-line-soft overflow-hidden">
        <DitherMap className="absolute inset-0 w-full h-full opacity-80 dark:opacity-60" />
        <div className="absolute inset-0 bg-gradient-to-r from-p-bg via-p-bg/85 via-50% to-p-bg/40" />
        <div className="relative z-10 px-[var(--p-pad-section-x)] py-[var(--p-pad-section-y)] w-full">
          <div className="max-w-[1240px] mx-auto">
            <div className="max-w-[640px]">
              <Tag tone="primary" className="mb-6">
                {t("hero.tagline")}
              </Tag>
              <h1 className="text-hero font-semibold tracking-[-0.03em] mb-6">
                {t("hero.title")} <br />
                <span className="bg-gradient-to-r from-p-grad-a to-p-grad-b bg-clip-text text-transparent">
                  {t("hero.titleHighlight")}
                </span>
              </h1>
              <p className="text-lead leading-relaxed mb-10">
                {t("hero.description")}
              </p>
              <div className="flex gap-4 items-center flex-wrap">
                <Link href="/quickstart">
                  <Btn variant="primary" size="lg">
                    {t("hero.quickstart")} →
                  </Btn>
                </Link>
                <a href="https://browser.portolan-sdi.org/">
                  <Btn variant="secondary" size="lg">
                    {t("hero.browseCatalogs")}
                  </Btn>
                </a>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Why Portolan */}
      <section id="why" className="px-[var(--p-pad-section-x)] py-[var(--p-pad-section-y)]">
        <div className="max-w-[1240px] mx-auto">
          <div className="flex items-baseline justify-between mb-8">
            <div>
              <span className="font-mono text-eyebrow text-p-ink-3 tracking-[0.08em]">
                {t("why.eyebrow")}
              </span>
              <h2 className="text-section mt-1.5 font-semibold tracking-[-0.02em]">
                {t("why.title")}
              </h2>
            </div>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-px bg-p-line border border-p-line rounded-[var(--p-r-lg)] overflow-hidden">
            {whyCards.map((card) => (
              <div
                key={card.key}
                className="bg-p-paper p-6 flex flex-col gap-3"
              >
                <div className="flex justify-between items-center">
                  <span className="font-mono text-eyebrow text-p-ink-3">{card.id}</span>
                  <span className="w-2 h-2 rounded-full bg-p-primary" />
                </div>
                <h3 className="text-card-title font-semibold">
                  {t(`why.cards.${card.key}.title`)}
                </h3>
                <p className="text-body leading-relaxed">
                  {t(`why.cards.${card.key}.description`)}
                </p>
                <div className="mt-auto font-mono text-micro text-p-primary-ink px-2.5 py-1.5 bg-p-bg-soft rounded-[var(--p-r-sm)] border border-p-line-soft self-start">
                  {t(`why.cards.${card.key}.tag`)}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section id="how" className="px-[var(--p-pad-section-x)] py-[var(--p-pad-section-y)] bg-p-bg-soft border-y border-p-line-soft">
        <div className="max-w-[1240px] mx-auto">
          <span className="font-mono text-eyebrow text-p-ink-3 tracking-[0.08em]">
            {t("howItWorks.eyebrow")}
          </span>
          <h2 className="text-section mt-1.5 mb-3 font-semibold tracking-[-0.02em]">
            {t("howItWorks.title")}
          </h2>
          <p className="text-body-lg leading-relaxed max-w-[720px] mb-10">
            {t("howItWorks.subtitle")}
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
            {howSteps.map((step) => (
              <Card key={step} className="flex flex-col gap-3">
                <div className="flex justify-between items-center">
                  <span className="font-mono text-eyebrow text-p-ink-3">
                    {t(`howItWorks.steps.${step}.id`)}
                  </span>
                  <span className="w-2 h-2 rounded-full bg-p-accent" />
                </div>
                <h3 className="text-card-title font-semibold">
                  {t(`howItWorks.steps.${step}.title`)}
                </h3>
                <p className="text-body leading-relaxed">
                  {t(`howItWorks.steps.${step}.description`)}
                </p>
              </Card>
            ))}
          </div>
        </div>
      </section>

      {/* Toolkit */}
      <section
        id="tools"
        className="px-[var(--p-pad-section-x)] py-[var(--p-pad-section-y)] relative overflow-hidden"
      >
        <RhumbBackdrop opacity={0.08} originX={15} originY={50} />
        <div className="max-w-[1240px] mx-auto relative">
          <div className="flex flex-col gap-4 md:flex-row md:justify-between md:items-end mb-10">
            <div>
              <span className="font-mono text-eyebrow text-p-ink-3 tracking-[0.08em]">
                {t("toolkit.eyebrow")}
              </span>
              <h2 className="text-section mt-1.5 font-semibold leading-tight max-w-[720px] tracking-[-0.02em]">
                {t("toolkit.title")}
              </h2>
            </div>
            <a href="https://github.com/portolan-sdi/">
              <Btn variant="secondary" size="md">
                {t("toolkit.allProjects")} →
              </Btn>
            </a>
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-[3fr_2fr] gap-5 items-stretch">
            {/* CLI Card */}
            <a href="https://cli.portolan-sdi.org/" className="contents">
              <Card className="flex flex-col gap-4 transition-shadow hover:shadow-[var(--p-shadow-md)]">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="font-mono text-eyebrow text-p-primary-ink mb-1">
                      {t("toolkit.cli.name")}
                    </div>
                    <h3 className="text-feature">{t("toolkit.cli.title")}</h3>
                  </div>
                  <Tag tone="accent">{t("toolkit.cli.version")}</Tag>
                </div>
                <p className="text-body-lg leading-relaxed">{t("toolkit.cli.description")}</p>
                <Terminal title="my-catalog · zsh" lines={terminalLines} />
                <div className="font-mono text-micro text-p-ink-3 mt-auto">
                  {t("toolkit.cli.compatibility")}
                </div>
              </Card>
            </a>

            {/* Side Cards */}
            <div className="grid grid-rows-2 gap-5 min-h-0">
              <a href="https://github.com/portolan-sdi/portolan-browser" className="contents">
                <Card className="flex flex-col gap-3 transition-shadow hover:shadow-[var(--p-shadow-md)]">
                  <div className="flex justify-between items-start">
                    <div className="font-mono text-eyebrow text-p-primary-ink">
                      {t("toolkit.viewer.name")}
                    </div>
                    <Tag tone="default">{t("toolkit.viewer.tag")}</Tag>
                  </div>
                  <h3 className="text-card-title-lg">{t("toolkit.viewer.title")}</h3>
                  <p className="text-body leading-relaxed">
                    {t("toolkit.viewer.description")}
                  </p>
                  <span className="mt-auto text-small text-p-primary hover:underline">
                    {t("toolkit.readMore")} →
                  </span>
                </Card>
              </a>
              <a href="https://github.com/portolan-sdi/portolan-skills" className="contents">
                <Card className="flex flex-col gap-3 transition-shadow hover:shadow-[var(--p-shadow-md)]">
                  <div className="flex justify-between items-start">
                    <div className="font-mono text-eyebrow text-p-primary-ink">
                      {t("toolkit.skills.name")}
                    </div>
                    <Tag tone="default">{t("toolkit.skills.tag")}</Tag>
                  </div>
                  <h3 className="text-card-title-lg">{t("toolkit.skills.title")}</h3>
                  <p className="text-body leading-relaxed">
                    {t("toolkit.skills.description")}
                  </p>
                  <span className="mt-auto text-small text-p-primary hover:underline">
                    {t("toolkit.readMore")} →
                  </span>
                </Card>
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <SiteFooter />
    </div>
  );
}
