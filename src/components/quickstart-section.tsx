"use client";

import { useTranslations } from "next-intl";
import { Btn, Card, Terminal, DirArrow } from "./ui";

const duckdbLines = [
  { text: "$ duckdb", color: "#c5cce8" },
  { text: "", color: "#c5cce8" },
  { text: "SELECT * FROM read_parquet(", color: "#c5cce8" },
  { text: "  'https://my-catalog.s3.amazonaws.com/parcels.parquet'", color: "#f4b860" },
  { text: ") WHERE area_sqm > 1000 LIMIT 10;", color: "#c5cce8" },
];

const cliLines = [
  { text: "$ uv tool install portolan-cli", color: "#c5cce8" },
  { text: "$ cd my-data && portolan init", color: "#c5cce8" },
  { text: "$ portolan add .", color: "#c5cce8" },
  { text: "$ portolan check --fix", color: "#c5cce8" },
  { text: "  → parcels.shp   →  GeoParquet", color: "#c5cce8" },
  { text: "  → ortho.tif     →  COG", color: "#c5cce8" },
  { text: "  ✓ catalog generated", color: "#848bd8" },
  { text: "$ portolan push s3://my-bucket/catalog", color: "#c5cce8" },
  { text: "  ✓ synced 12 assets", color: "#848bd8" },
  { text: "  ▸ https://my-bucket.s3.amazonaws.com/catalog.json", color: "#f4b860" },
];

const claudeLines = [
  { text: "# Install the Portolan skill", color: "#5775d6" },
  { text: "$ claude install portolan-sdi/portolan-cli", color: "#c5cce8" },
  { text: "", color: "#c5cce8" },
  { text: "$ claude", color: "#c5cce8" },
  { text: "", color: "#c5cce8" },
  { text: "  > /portolan-cli publish the shapefiles in", color: "#f4b860" },
  { text: "    ./gov-data to s3://my-catalog", color: "#f4b860" },
];

export function QuickstartSection() {
  const t = useTranslations("quickstart");

  return (
    <section
      id="quickstart"
      className="px-[var(--p-pad-section-x)] py-[var(--p-pad-section-y)] bg-p-bg-soft border-y border-p-line-soft"
    >
      <div className="max-w-[1240px] mx-auto">
        <span className="font-mono text-eyebrow text-p-ink-3 tracking-[0.08em]">
          {t("eyebrow")}
        </span>
        <h2 className="text-section mt-1.5 mb-3 font-semibold tracking-[-0.02em]">
          {t("title")}
        </h2>
        <p className="text-body-lg leading-relaxed max-w-[720px] mb-10">
          {t("intro")}
        </p>
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
