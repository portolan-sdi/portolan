"use client";

import { useTranslations } from "next-intl";
import { PortolanLogo } from "./portolan-logo";
import { RhumbBackdrop } from "./rhumb-backdrop";
import { DitherMap } from "./dither-map";
import { ThemeToggle } from "./theme-toggle";
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
      <header className="flex items-center justify-between px-[var(--p-pad-xl)] py-5 border-b border-p-line-soft">
        <a href="/">
          <PortolanLogo size={28} />
        </a>
        <nav className="flex gap-7 text-sm text-p-ink-2">
          <a href="#why" className="text-inherit hover:text-p-ink transition-colors">
            {t("nav.why")}
          </a>
          <a href="#how" className="text-inherit hover:text-p-ink transition-colors">
            {t("nav.howItWorks")}
          </a>
          <a href="#tools" className="text-inherit hover:text-p-ink transition-colors">
            {t("nav.tools")}
          </a>
          <a
            href="https://portolan-sdi.github.io/portolan-cli"
            className="text-inherit hover:text-p-ink transition-colors"
          >
            {t("nav.docs")} ↗
          </a>
        </nav>
        <div className="flex gap-2">
          <ThemeToggle />
          <a
            href="https://github.com/portolan-sdi"
            aria-label="GitHub"
            className="inline-flex items-center justify-center w-8 h-8 rounded-lg text-p-ink-2 transition-colors hover:bg-p-bg-soft hover:text-p-ink"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.58.1.79-.25.79-.56v-2c-3.2.7-3.87-1.36-3.87-1.36-.52-1.33-1.28-1.69-1.28-1.69-1.05-.71.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.18 1.18a11.07 11.07 0 015.79 0c2.21-1.49 3.18-1.18 3.18-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.84 1.19 3.1 0 4.42-2.69 5.39-5.25 5.68.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56C20.21 21.39 23.5 17.08 23.5 12 23.5 5.65 18.35.5 12 .5z" />
            </svg>
          </a>
        </div>
      </header>

      {/* Hero */}
      <section className="relative min-h-[85vh] flex items-center border-b border-p-line-soft overflow-hidden">
        <DitherMap className="absolute inset-0 w-full h-full opacity-80 dark:opacity-60" />
        <div className="absolute inset-0 bg-gradient-to-r from-p-bg via-p-bg/85 via-50% to-p-bg/40" />
        <div className="relative z-10 px-[var(--p-pad-xl)] py-[var(--p-pad-xl)] w-full">
          <div className="max-w-[1240px] mx-auto">
            <div className="max-w-[640px]">
              <Tag tone="primary" className="mb-6">
                {t("hero.tagline")}
              </Tag>
              <h1 className="text-[clamp(40px,5vw,64px)] leading-[1.1] font-semibold tracking-[-0.03em] mb-6">
                {t("hero.title")} <br />
                <span className="bg-gradient-to-r from-p-grad-a to-p-grad-b bg-clip-text text-transparent">
                  {t("hero.titleHighlight")}
                </span>
              </h1>
              <p className="text-[17px] leading-relaxed mb-10">
                {t("hero.description")}
              </p>
              <div className="flex gap-4 items-center flex-wrap">
                <a href="/quickstart">
                  <Btn variant="primary" size="lg">
                    {t("hero.quickstart")} →
                  </Btn>
                </a>
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
      <section id="why" className="px-[var(--p-pad-xl)] py-[var(--p-pad-xl)]">
        <div className="max-w-[1240px] mx-auto">
          <div className="flex items-baseline justify-between mb-8">
            <div>
              <span className="font-mono text-[11px] text-p-ink-3 tracking-[0.08em]">
                {t("why.eyebrow")}
              </span>
              <h2 className="text-4xl mt-1.5 font-semibold tracking-[-0.02em]">
                {t("why.title")}
              </h2>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-px bg-p-line border border-p-line rounded-[var(--p-r-lg)] overflow-hidden">
            {whyCards.map((card) => (
              <div
                key={card.key}
                className="bg-p-paper p-6 flex flex-col gap-3"
              >
                <div className="flex justify-between items-center">
                  <span className="font-mono text-[11px] text-p-ink-3">{card.id}</span>
                  <span className="w-2 h-2 rounded-full bg-p-primary" />
                </div>
                <h3 className="text-lg font-semibold">
                  {t(`why.cards.${card.key}.title`)}
                </h3>
                <p className="text-[13.5px] leading-relaxed">
                  {t(`why.cards.${card.key}.description`)}
                </p>
                <div className="mt-auto font-mono text-[11.5px] text-p-primary-ink px-2.5 py-1.5 bg-p-bg-soft rounded-[var(--p-r-sm)] border border-p-line-soft self-start">
                  {t(`why.cards.${card.key}.tag`)}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section id="how" className="px-[var(--p-pad-xl)] py-[var(--p-pad-xl)] bg-p-bg-soft border-y border-p-line-soft">
        <div className="max-w-[1240px] mx-auto">
          <span className="font-mono text-[11px] text-p-ink-3 tracking-[0.08em]">
            {t("howItWorks.eyebrow")}
          </span>
          <h2 className="text-4xl mt-1.5 mb-3 font-semibold tracking-[-0.02em]">
            {t("howItWorks.title")}
          </h2>
          <p className="text-[15px] leading-relaxed max-w-[720px] mb-10">
            {t("howItWorks.subtitle")}
          </p>
          <div className="grid grid-cols-4 gap-5">
            {howSteps.map((step) => (
              <Card key={step} className="!p-6 flex flex-col gap-3">
                <div className="flex justify-between items-center">
                  <span className="font-mono text-[11px] text-p-ink-3">
                    {t(`howItWorks.steps.${step}.id`)}
                  </span>
                  <span className="w-2 h-2 rounded-full bg-p-accent" />
                </div>
                <h3 className="text-lg font-semibold">
                  {t(`howItWorks.steps.${step}.title`)}
                </h3>
                <p className="text-[13.5px] leading-relaxed">
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
        className="px-[var(--p-pad-xl)] py-[calc(var(--p-pad-xl)*1.4)] relative overflow-hidden"
      >
        <RhumbBackdrop opacity={0.08} originX={15} originY={50} />
        <div className="max-w-[1240px] mx-auto relative">
          <div className="flex justify-between items-end mb-10">
            <div>
              <span className="font-mono text-[11px] text-p-ink-3 tracking-[0.08em]">
                {t("toolkit.eyebrow")}
              </span>
              <h2 className="text-[44px] mt-1.5 font-semibold leading-tight max-w-[720px] tracking-[-0.02em]">
                {t("toolkit.title")}
              </h2>
            </div>
            <a href="https://github.com/portolan-sdi/">
              <Btn variant="secondary" size="md">
                {t("toolkit.allProjects")} →
              </Btn>
            </a>
          </div>
          <div className="grid grid-cols-[3fr_2fr] gap-5 items-stretch">
            {/* CLI Card */}
            <a href="https://cli.portolan-sdi.org/" className="contents">
              <Card className="!p-6 flex flex-col gap-4 transition-shadow hover:shadow-[var(--p-shadow-md)]">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="font-mono text-xs text-p-primary-ink mb-1">
                      {t("toolkit.cli.name")}
                    </div>
                    <h3 className="text-[26px]">{t("toolkit.cli.title")}</h3>
                  </div>
                  <Tag tone="accent">{t("toolkit.cli.version")}</Tag>
                </div>
                <p className="text-sm leading-relaxed">{t("toolkit.cli.description")}</p>
                <Terminal title="my-catalog · zsh" lines={terminalLines} />
                <div className="font-mono text-[11.5px] text-p-ink-3 mt-auto">
                  {t("toolkit.cli.compatibility")}
                </div>
              </Card>
            </a>

            {/* Side Cards */}
            <div className="grid grid-rows-2 gap-5 min-h-0">
              <a href="https://github.com/portolan-sdi/portolan-browser" className="contents">
                <Card className="!p-5 flex flex-col gap-3 transition-shadow hover:shadow-[var(--p-shadow-md)]">
                  <div className="flex justify-between items-start">
                    <div className="font-mono text-xs text-p-primary-ink">
                      {t("toolkit.viewer.name")}
                    </div>
                    <Tag tone="default">{t("toolkit.viewer.tag")}</Tag>
                  </div>
                  <h3 className="text-xl">{t("toolkit.viewer.title")}</h3>
                  <p className="text-[13.5px] leading-relaxed">
                    {t("toolkit.viewer.description")}
                  </p>
                  <span className="mt-auto text-[13px] text-p-primary hover:underline">
                    {t("toolkit.readMore")} →
                  </span>
                </Card>
              </a>
              <a href="https://github.com/portolan-sdi/portolan-skills" className="contents">
                <Card className="!p-5 flex flex-col gap-3 transition-shadow hover:shadow-[var(--p-shadow-md)]">
                  <div className="flex justify-between items-start">
                    <div className="font-mono text-xs text-p-primary-ink">
                      {t("toolkit.skills.name")}
                    </div>
                    <Tag tone="default">{t("toolkit.skills.tag")}</Tag>
                  </div>
                  <h3 className="text-xl">{t("toolkit.skills.title")}</h3>
                  <p className="text-[13.5px] leading-relaxed">
                    {t("toolkit.skills.description")}
                  </p>
                  <span className="mt-auto text-[13px] text-p-primary hover:underline">
                    {t("toolkit.readMore")} →
                  </span>
                </Card>
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="px-[var(--p-pad-xl)] py-[var(--p-pad-lg)] border-t border-p-line-soft flex justify-between items-center text-[13px] text-p-ink-3 flex-wrap gap-4">
        <PortolanLogo size={22} />
        <div className="flex gap-6">
          <span>{t("footer.openGovernance")}</span>
          <span>{t("footer.license")}</span>
          <span>{t("footer.repo")}</span>
        </div>
      </footer>
    </div>
  );
}
