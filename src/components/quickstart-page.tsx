"use client";

import { useTranslations } from "next-intl";
import { PortolanLogo } from "./portolan-logo";
import { ThemeToggle } from "./theme-toggle";
import { Btn, Card, Terminal } from "./ui";

const installLines = [
  { text: "$ uv tool install portolan-cli", color: "#c5cce8" },
];

const cliLines = [
  { text: "# Initialize a new catalog", color: "#5775d6" },
  { text: "$ cd my-data && portolan init", color: "#c5cce8" },
  { text: "", color: "#c5cce8" },
  { text: "# Add your data files", color: "#5775d6" },
  { text: "$ portolan add .", color: "#c5cce8" },
  { text: "  ✓ found 12 files (parcels.shp, ortho.tif, roads.shp ...)", color: "#848bd8" },
  { text: "", color: "#c5cce8" },
  { text: "# Convert to cloud-native formats", color: "#5775d6" },
  { text: "$ portolan check --fix", color: "#c5cce8" },
  { text: "  → parcels.shp        →  GeoParquet", color: "#c5cce8" },
  { text: "  → ortho.tif          →  COG", color: "#c5cce8" },
  { text: "  → roads.shp          →  GeoParquet", color: "#c5cce8" },
  { text: "  ✓ STAC catalog generated", color: "#848bd8" },
  { text: "", color: "#c5cce8" },
  { text: "# Push to cloud storage", color: "#5775d6" },
  { text: "$ portolan push s3://my-bucket/catalog", color: "#c5cce8" },
  { text: "  ✓ synced 12 assets to s3://my-bucket/catalog", color: "#848bd8" },
  { text: "  ▸ https://my-bucket.s3.amazonaws.com/catalog.json", color: "#f4b860" },
  { text: "", color: "#c5cce8" },
  { text: "  done · 0:32 elapsed", color: "#28c840" },
];

const claudeInstallLines = [
  { text: "# In Claude Code, install the Portolan skill", color: "#5775d6" },
  { text: "$ claude install portolan-sdi/portolan-cli", color: "#c5cce8" },
];

const claudeRunLines = [
  { text: "$ claude", color: "#c5cce8" },
  { text: "", color: "#c5cce8" },
  { text: "  > /portolan-cli publish the shapefiles in ./gov-data", color: "#f4b860" },
  { text: "    to s3://my-catalog", color: "#f4b860" },
];

const duckdbLines = [
  { text: "$ duckdb", color: "#c5cce8" },
  { text: "", color: "#c5cce8" },
  { text: "SELECT * FROM read_parquet(", color: "#c5cce8" },
  { text: "  'https://my-catalog.s3.amazonaws.com/parcels.parquet'", color: "#f4b860" },
  { text: ") WHERE area_sqm > 1000 LIMIT 10;", color: "#c5cce8" },
];

export function QuickstartPage() {
  const t = useTranslations();

  return (
    <div className="bg-p-bg min-h-full font-sans">
      {/* Header */}
      <header className="flex items-center justify-between px-[var(--p-pad-xl)] py-5 border-b border-p-line-soft">
        <a href="/">
          <PortolanLogo size={28} />
        </a>
        <nav className="flex gap-7 text-sm text-p-ink-2">
          <a href="/#why" className="text-inherit hover:text-p-ink transition-colors">
            {t("nav.why")}
          </a>
          <a href="/#how" className="text-inherit hover:text-p-ink transition-colors">
            {t("nav.howItWorks")}
          </a>
          <a href="/#tools" className="text-inherit hover:text-p-ink transition-colors">
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
      <section className="px-[var(--p-pad-xl)] pt-[var(--p-pad-xl)] pb-[var(--p-pad-lg)]">
        <div className="max-w-[860px] mx-auto">
          <h1 className="text-[clamp(36px,4vw,52px)] leading-[1.1] font-semibold tracking-[-0.03em] mb-4">
            {t("quickstart.title")}
          </h1>
          <p className="text-[17px] leading-relaxed text-p-ink-2">
            {t("quickstart.intro")}
          </p>
        </div>
      </section>

      {/* Step 1: Browse */}
      <section className="px-[var(--p-pad-xl)] py-[var(--p-pad-lg)]">
        <div className="max-w-[860px] mx-auto">
          <span className="font-mono text-[11px] text-p-ink-3 tracking-[0.08em]">
            {t("quickstart.browse.eyebrow")}
          </span>
          <h2 className="text-3xl mt-1.5 mb-4 font-semibold tracking-[-0.02em]">
            {t("quickstart.browse.title")}
          </h2>
          <p className="text-[15px] leading-relaxed mb-6">
            {t("quickstart.browse.description")}
          </p>
          <a href="https://browser.portolan-sdi.org/" className="inline-block mb-10">
            <Btn variant="primary" size="md">
              {t("quickstart.browse.cta")} ↗
            </Btn>
          </a>

          <Card className="!p-6">
            <h3 className="text-lg font-semibold mb-2">
              {t("quickstart.browse.duckdb.title")}
            </h3>
            <p className="text-[13.5px] leading-relaxed mb-4">
              {t("quickstart.browse.duckdb.description")}
            </p>
            <Terminal title="duckdb" lines={duckdbLines} />
          </Card>
        </div>
      </section>

      {/* Step 2: Publish */}
      <section className="px-[var(--p-pad-xl)] py-[var(--p-pad-lg)] bg-p-bg-soft border-y border-p-line-soft">
        <div className="max-w-[860px] mx-auto">
          <span className="font-mono text-[11px] text-p-ink-3 tracking-[0.08em]">
            {t("quickstart.publish.eyebrow")}
          </span>
          <h2 className="text-3xl mt-1.5 mb-4 font-semibold tracking-[-0.02em]">
            {t("quickstart.publish.title")}
          </h2>
          <p className="text-[15px] leading-relaxed mb-10">
            {t("quickstart.publish.description")}
          </p>

          {/* CLI path */}
          <div className="mb-12">
            <h3 className="text-xl font-semibold mb-2">{t("quickstart.cli.title")}</h3>
            <p className="text-[14px] leading-relaxed mb-4">
              {t("quickstart.cli.description")}
            </p>
            <Terminal title="install · zsh" lines={installLines} />
            <div className="mt-5">
              <Terminal title="my-data · zsh" lines={cliLines} />
            </div>
          </div>

          {/* Claude path */}
          <div>
            <h3 className="text-xl font-semibold mb-2">{t("quickstart.claude.title")}</h3>
            <p className="text-[14px] leading-relaxed mb-4">
              {t("quickstart.claude.description")}
            </p>
            <Terminal title="install skill · zsh" lines={claudeInstallLines} />
            <div className="mt-5">
              <Terminal title="claude code" lines={claudeRunLines} />
            </div>
          </div>
        </div>
      </section>

      {/* What's next */}
      <section className="px-[var(--p-pad-xl)] py-[var(--p-pad-lg)]">
        <div className="max-w-[860px] mx-auto">
          <h2 className="text-2xl mb-6 font-semibold tracking-[-0.02em]">
            {t("quickstart.next.title")}
          </h2>
          <div className="flex gap-4 flex-wrap">
            <a href="https://portolan-sdi.github.io/portolan-cli">
              <Btn variant="secondary" size="md">
                {t("quickstart.next.docs")} ↗
              </Btn>
            </a>
            <a href="https://github.com/portolan-sdi">
              <Btn variant="secondary" size="md">
                {t("quickstart.next.github")} ↗
              </Btn>
            </a>
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
