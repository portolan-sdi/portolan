"use client";

import { useTranslations } from "next-intl";
import { SiteHeader } from "./site-header";
import { SiteFooter } from "./site-footer";
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
      <SiteHeader />

      {/* Hero */}
      <section className="px-[var(--p-pad-section-x)] pt-[var(--p-pad-section-y)] pb-[var(--p-pad-lg)]">
        <div className="max-w-[860px] mx-auto">
          <h1 className="text-hero-sm font-semibold tracking-[-0.03em] mb-4">
            {t("quickstart.title")}
          </h1>
          <p className="text-lead leading-relaxed text-p-ink-2">
            {t("quickstart.intro")}
          </p>
        </div>
      </section>

      {/* Step 1: Browse */}
      <section className="px-[var(--p-pad-section-x)] py-[var(--p-pad-section-y)]">
        <div className="max-w-[860px] mx-auto">
          <span className="font-mono text-eyebrow text-p-ink-3 tracking-[0.08em]">
            {t("quickstart.browse.eyebrow")}
          </span>
          <h2 className="text-section-sm mt-1.5 mb-4 font-semibold tracking-[-0.02em]">
            {t("quickstart.browse.title")}
          </h2>
          <p className="text-body-lg leading-relaxed mb-6">
            {t("quickstart.browse.description")}
          </p>
          <a href="https://browser.portolan-sdi.org/" className="inline-block mb-10">
            <Btn variant="primary" size="md">
              {t("quickstart.browse.cta")} ↗
            </Btn>
          </a>

          <Card>
            <h3 className="text-card-title font-semibold mb-2">
              {t("quickstart.browse.duckdb.title")}
            </h3>
            <p className="text-body leading-relaxed mb-4">
              {t("quickstart.browse.duckdb.description")}
            </p>
            <Terminal title="duckdb" lines={duckdbLines} />
          </Card>
        </div>
      </section>

      {/* Step 2: Publish */}
      <section className="px-[var(--p-pad-section-x)] py-[var(--p-pad-section-y)] bg-p-bg-soft border-y border-p-line-soft">
        <div className="max-w-[860px] mx-auto">
          <span className="font-mono text-eyebrow text-p-ink-3 tracking-[0.08em]">
            {t("quickstart.publish.eyebrow")}
          </span>
          <h2 className="text-section-sm mt-1.5 mb-4 font-semibold tracking-[-0.02em]">
            {t("quickstart.publish.title")}
          </h2>
          <p className="text-body-lg leading-relaxed mb-10">
            {t("quickstart.publish.description")}
          </p>

          {/* CLI path */}
          <div className="mb-12">
            <h3 className="text-card-title-lg font-semibold mb-2">{t("quickstart.cli.title")}</h3>
            <p className="text-body-lg leading-relaxed mb-4">
              {t("quickstart.cli.description")}
            </p>
            <Terminal title="install · zsh" lines={installLines} />
            <div className="mt-5">
              <Terminal title="my-data · zsh" lines={cliLines} />
            </div>
          </div>

          {/* Claude path */}
          <div>
            <h3 className="text-card-title-lg font-semibold mb-2">{t("quickstart.claude.title")}</h3>
            <p className="text-body-lg leading-relaxed mb-4">
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
      <section className="px-[var(--p-pad-section-x)] py-[var(--p-pad-section-y)]">
        <div className="max-w-[860px] mx-auto">
          <h2 className="text-section-sm mb-6 font-semibold tracking-[-0.02em]">
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
      <SiteFooter />
    </div>
  );
}
