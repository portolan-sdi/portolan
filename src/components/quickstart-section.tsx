"use client";

import { useTranslations } from "next-intl";
import { Btn, Card, Terminal, DirArrow, SectionHead } from "./ui";

const duckdbLines = [
  { text: "$ duckdb", color: "var(--term-syntax-text)" },
  { text: "", color: "var(--term-syntax-text)" },
  { text: "SELECT * FROM read_parquet(", color: "var(--term-syntax-text)" },
  { text: "  'https://my-catalog.s3.amazonaws.com/parcels.parquet'", color: "var(--term-syntax-accent)" },
  { text: ") WHERE area_sqm > 1000 LIMIT 10;", color: "var(--term-syntax-text)" },
];

const cliLines = [
  { text: "$ uv tool install portolan-cli", color: "var(--term-syntax-text)" },
  { text: "$ cd my-data && portolan init", color: "var(--term-syntax-text)" },
  { text: "$ portolan add .", color: "var(--term-syntax-text)" },
  { text: "$ portolan check --fix", color: "var(--term-syntax-text)" },
  { text: "  → parcels.shp   →  GeoParquet", color: "var(--term-syntax-text)" },
  { text: "  → ortho.tif     →  COG", color: "var(--term-syntax-text)" },
  { text: "  ✓ catalog generated", color: "var(--term-syntax-accent)" },
  { text: "$ portolan push s3://my-bucket/catalog", color: "var(--term-syntax-text)" },
  { text: "  ✓ synced 12 assets", color: "var(--term-syntax-accent)" },
  { text: "  ▸ https://my-bucket.s3.amazonaws.com/catalog.json", color: "var(--term-syntax-accent)" },
];

const claudeLines = [
  { text: "# Install the Portolan skill", color: "var(--term-syntax-muted)" },
  { text: "$ claude install portolan-sdi/portolan-cli", color: "var(--term-syntax-text)" },
  { text: "", color: "var(--term-syntax-text)" },
  { text: "$ claude", color: "var(--term-syntax-text)" },
  { text: "", color: "var(--term-syntax-text)" },
  { text: "  > /portolan-cli publish the shapefiles in", color: "var(--term-syntax-accent)" },
  { text: "    ./gov-data to s3://my-catalog", color: "var(--term-syntax-accent)" },
];

export function QuickstartSection() {
  const t = useTranslations("quickstart");

  return (
    <section
      id="quickstart"
      className="px-[var(--p-pad-section-x)] py-[var(--p-pad-section-y)] border-t border-p-line"
    >
      <div className="max-w-[1240px] mx-auto">
        <SectionHead
          index="04"
          eyebrow={t("eyebrow")}
          title={t("title")}
          subtitle={t("intro")}
        />
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 items-stretch">
          <Card className="flex flex-col gap-3">
            <h3 className="text-card-title-lg font-semibold">{t("browse.title")}</h3>
            <p className="text-body leading-relaxed">{t("browse.description")}</p>
            <a href="https://browser.portolan-sdi.org/" className="self-start">
              <Btn variant="secondary" size="sm">
                {t("browse.cta")} <DirArrow kind="external" />
              </Btn>
            </a>
            <div className="mt-auto">
              <Terminal title="duckdb" lines={duckdbLines} />
            </div>
          </Card>
          <Card className="flex flex-col gap-3">
            <h3 className="text-card-title-lg font-semibold">{t("cli.title")}</h3>
            <p className="text-body leading-relaxed">{t("cli.description")}</p>
            <div className="mt-auto">
              <Terminal title="my-data · zsh" lines={cliLines} />
            </div>
          </Card>
          <Card className="flex flex-col gap-3">
            <h3 className="text-card-title-lg font-semibold">{t("claude.title")}</h3>
            <p className="text-body leading-relaxed">{t("claude.description")}</p>
            <div className="mt-auto">
              <Terminal title="claude code" lines={claudeLines} />
            </div>
          </Card>
        </div>
      </div>
    </section>
  );
}
