"use client";

import { useState, useMemo } from "react";
import dynamic from "next/dynamic";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { RhumbBackdrop } from "./rhumb-backdrop";
import { DitherMap } from "./dither-map";
import { SiteHeader } from "./site-header";
import { SiteFooter } from "./site-footer";
import { Btn, Tag, Card, Terminal, DirArrow, Ltr } from "./ui";
import { CatalogCard } from "./registry/catalog-card";
import type { Catalog } from "@/lib/catalogs";
import { getValidationTier } from "@/lib/catalogs";

type SubmitState = "idle" | "submitting" | "success" | "error";

// Placeholder shown while the deck.gl/maplibre chunk loads on first map view.
function MapSkeleton() {
  const t = useTranslations("registry");
  return (
    <div className="h-[520px] md:h-[600px] rounded-[var(--p-r-lg)] border border-p-line bg-p-bg-soft animate-pulse flex items-center justify-center">
      <span className="text-micro text-p-ink-3 font-mono">{t("map.loading")}</span>
    </div>
  );
}

// home-page is already a Client Component, so ssr:false is legal here. The
// chunk only loads the first time the map view renders.
const CatalogMap = dynamic(() => import("./registry/catalog-map"), {
  ssr: false,
  loading: () => <MapSkeleton />,
});

interface HomePageProps {
  catalogs?: Catalog[];
}

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

export function HomePage({ catalogs = [] }: HomePageProps) {
  const t = useTranslations();

  const [searchQuery, setSearchQuery] = useState("");
  const [selectedTags, setSelectedTags] = useState<Set<string>>(new Set());
  const [validationFilter, setValidationFilter] = useState<"all" | "unvalidated" | "basic" | "full">("all");
  const [bboxFilter, setBboxFilter] = useState<{ west: string; south: string; east: string; north: string }>({
    west: "", south: "", east: "", north: ""
  });
  const [showBboxFilter, setShowBboxFilter] = useState(false);
  const [registryView, setRegistryView] = useState<"cards" | "map">("cards");

  const [submitUrl, setSubmitUrl] = useState("");
  const [submitState, setSubmitState] = useState<SubmitState>("idle");
  const [submitPrUrl, setSubmitPrUrl] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const isValidSubmitUrl = submitUrl.trim().endsWith("catalog.json");

  const allTags = useMemo(() => {
    return Array.from(new Set(catalogs.flatMap((c) => c.keywords ?? []))).sort();
  }, [catalogs]);

  const parsedBbox = useMemo(() => {
    const { west, south, east, north } = bboxFilter;
    if (!west && !south && !east && !north) return null;
    const w = parseFloat(west);
    const s = parseFloat(south);
    const e = parseFloat(east);
    const n = parseFloat(north);
    if ([w, s, e, n].some(isNaN)) return null;
    return { west: w, south: s, east: e, north: n };
  }, [bboxFilter]);

  const filteredCatalogs = useMemo(() => {
    return catalogs.filter((catalog) => {
      const query = searchQuery.toLowerCase();
      const matchesSearch =
        query === "" ||
        catalog.title.toLowerCase().includes(query) ||
        catalog.description.toLowerCase().includes(query);

      const catalogKeywords = catalog.keywords ?? [];
      const matchesTags =
        selectedTags.size === 0 ||
        catalogKeywords.some((keyword) => selectedTags.has(keyword));

      const tier = getValidationTier(catalog.validation);
      const matchesValidation =
        validationFilter === "all" || tier === validationFilter;

      let matchesBbox = true;
      if (parsedBbox && catalog.bbox) {
        const [catWest, catSouth, catEast, catNorth] = catalog.bbox;
        matchesBbox =
          catEast >= parsedBbox.west &&
          catWest <= parsedBbox.east &&
          catNorth >= parsedBbox.south &&
          catSouth <= parsedBbox.north;
      }

      return matchesSearch && matchesTags && matchesValidation && matchesBbox;
    });
  }, [catalogs, searchQuery, selectedTags, validationFilter, parsedBbox]);

  const handleTagToggle = (tag: string) => {
    setSelectedTags((prev) => {
      const next = new Set(prev);
      if (next.has(tag)) {
        next.delete(tag);
      } else {
        next.add(tag);
      }
      return next;
    });
  };

  const handleClearFilters = () => {
    setSearchQuery("");
    setSelectedTags(new Set());
    setValidationFilter("all");
    setBboxFilter({ west: "", south: "", east: "", north: "" });
  };

  const hasActiveFilters = searchQuery !== "" || selectedTags.size > 0 || validationFilter !== "all" || parsedBbox !== null;

  const handleSubmitCatalog = async () => {
    if (!isValidSubmitUrl || submitState === "submitting") return;

    setSubmitState("submitting");
    setSubmitError(null);

    try {
      const res = await fetch("/api/submit-catalog", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: submitUrl.trim() }),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error || "Submission failed");
      }

      setSubmitPrUrl(data.pr_url);
      setSubmitState("success");
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Something went wrong");
      setSubmitState("error");
    }
  };

  const handleResetSubmit = () => {
    setSubmitUrl("");
    setSubmitState("idle");
    setSubmitPrUrl(null);
    setSubmitError(null);
  };

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
                    {t("hero.quickstart")} <DirArrow />
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
                {t("toolkit.allProjects")} <DirArrow />
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
                      <Ltr>{t("toolkit.cli.name")}</Ltr>
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
                      <Ltr>{t("toolkit.viewer.name")}</Ltr>
                    </div>
                    <Tag tone="default">{t("toolkit.viewer.tag")}</Tag>
                  </div>
                  <h3 className="text-card-title-lg">{t("toolkit.viewer.title")}</h3>
                  <p className="text-body leading-relaxed">
                    {t("toolkit.viewer.description")}
                  </p>
                  <span className="mt-auto text-small text-p-primary hover:underline">
                    {t("toolkit.readMore")} <DirArrow />
                  </span>
                </Card>
              </a>
              <a href="https://github.com/portolan-sdi/portolan-skills" className="contents">
                <Card className="flex flex-col gap-3 transition-shadow hover:shadow-[var(--p-shadow-md)]">
                  <div className="flex justify-between items-start">
                    <div className="font-mono text-eyebrow text-p-primary-ink">
                      <Ltr>{t("toolkit.skills.name")}</Ltr>
                    </div>
                    <Tag tone="default">{t("toolkit.skills.tag")}</Tag>
                  </div>
                  <h3 className="text-card-title-lg">{t("toolkit.skills.title")}</h3>
                  <p className="text-body leading-relaxed">
                    {t("toolkit.skills.description")}
                  </p>
                  <span className="mt-auto text-small text-p-primary hover:underline">
                    {t("toolkit.readMore")} <DirArrow />
                  </span>
                </Card>
              </a>
            </div>
          </div>
        </div>
      </section>

      {/* Registry */}
      {catalogs.length > 0 && (
        <section id="registry" className="px-[var(--p-pad-section-x)] py-[var(--p-pad-section-y)] bg-p-bg-soft border-t border-p-line-soft">
          <div className="max-w-[1240px] mx-auto">
            <span className="font-mono text-eyebrow text-p-ink-3 tracking-[0.08em]">
              {t("registry.eyebrow")}
            </span>
            <h2 className="text-section mt-1.5 mb-6 font-semibold tracking-[-0.02em]">
              {t("registry.title", { count: catalogs.length })}
            </h2>
            <p className="text-body-lg text-p-ink-2 mb-8 max-w-2xl">
              {t("registry.description")}
            </p>

            {/* Filters */}
            <div className="space-y-4 mb-8">
              <div className="flex flex-col sm:flex-row gap-4">
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder={t("registry.search.placeholder")}
                  className="flex-1 bg-p-paper border border-p-line rounded-[var(--p-r-md)] px-4 py-2.5 text-body text-p-ink placeholder:text-p-ink-3 focus:outline-none focus:border-p-primary transition-colors"
                />
                <div className="relative">
                  <select
                    value={validationFilter}
                    onChange={(e) => setValidationFilter(e.target.value as typeof validationFilter)}
                    className="appearance-none bg-p-paper border border-p-line rounded-[var(--p-r-md)] pl-3 pr-8 py-2.5 text-body text-p-ink focus:outline-none focus:border-p-primary transition-colors cursor-pointer"
                    aria-label={t("registry.filters.validation")}
                  >
                    <option value="all">{t("registry.filters.all")}</option>
                    <option value="unvalidated">{t("registry.validation.unvalidated")}</option>
                    <option value="basic">{t("registry.validation.basic")}</option>
                    <option value="full">{t("registry.validation.full")}</option>
                  </select>
                  <svg className="absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-p-ink-3 pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </div>
                <button
                  type="button"
                  onClick={() => setShowBboxFilter(!showBboxFilter)}
                  className={`flex items-center gap-2 px-3 py-2.5 text-body border rounded-[var(--p-r-md)] transition-colors ${
                    showBboxFilter || parsedBbox
                      ? "bg-[color-mix(in_oklab,var(--p-primary)_10%,transparent)] border-[color-mix(in_oklab,var(--p-primary)_25%,transparent)] text-p-primary-ink"
                      : "bg-p-paper border-p-line text-p-ink hover:border-p-ink-3"
                  }`}
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
                  </svg>
                  {t("registry.filters.bbox")}
                </button>

                {/* Cards | Map view toggle */}
                <div className="flex items-center gap-1 p-1 bg-p-paper border border-p-line rounded-[var(--p-r-md)] self-start sm:ms-auto">
                  {(["cards", "map"] as const).map((view) => {
                    const isActive = registryView === view;
                    return (
                      <button
                        key={view}
                        type="button"
                        onClick={() => setRegistryView(view)}
                        aria-pressed={isActive}
                        className={`font-mono text-micro px-3 py-1.5 rounded-[var(--p-r-sm)] transition-colors ${
                          isActive
                            ? "bg-[color-mix(in_oklab,var(--p-primary)_12%,transparent)] text-p-primary-ink"
                            : "text-p-ink-3 hover:text-p-ink-2"
                        }`}
                      >
                        {t(`registry.view.${view}`)}
                      </button>
                    );
                  })}
                </div>
              </div>

              {showBboxFilter && (
                <div className="flex flex-wrap items-center gap-3 p-4 bg-p-paper border border-p-line rounded-[var(--p-r-md)]">
                  <span className="text-micro text-p-ink-3 font-mono w-full sm:w-auto">{t("registry.filters.bboxLabel")}</span>
                  <div className="flex flex-wrap gap-2">
                    {(["west", "south", "east", "north"] as const).map((dir) => (
                      <div key={dir} className="flex items-center gap-1">
                        <label className="text-micro text-p-ink-3 uppercase w-6">{dir[0]}</label>
                        <input
                          type="number"
                          step="any"
                          value={bboxFilter[dir]}
                          onChange={(e) => setBboxFilter((prev) => ({ ...prev, [dir]: e.target.value }))}
                          placeholder={dir === "west" || dir === "east" ? "lon" : "lat"}
                          className="w-20 px-2 py-1.5 text-micro bg-p-bg border border-p-line rounded-[var(--p-r-sm)] text-p-ink placeholder:text-p-ink-3 focus:outline-none focus:border-p-primary"
                        />
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {allTags.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {allTags.map((tag) => {
                    const isSelected = selectedTags.has(tag);
                    return (
                      <button
                        key={tag}
                        type="button"
                        onClick={() => handleTagToggle(tag)}
                        className={`text-micro font-mono px-3 py-1.5 rounded-full border transition-colors ${
                          isSelected
                            ? "bg-[color-mix(in_oklab,var(--p-primary)_12%,transparent)] text-p-primary-ink border-[color-mix(in_oklab,var(--p-primary)_25%,transparent)]"
                            : "bg-p-bg text-p-ink-3 border-p-line hover:bg-p-line hover:text-p-ink-2"
                        }`}
                      >
                        {tag}
                      </button>
                    );
                  })}
                </div>
              )}

              {hasActiveFilters && (
                <button
                  type="button"
                  onClick={handleClearFilters}
                  className="text-micro text-p-ink-3 hover:text-p-ink-2 underline underline-offset-2"
                >
                  {t("registry.search.clearFilters")}
                </button>
              )}
            </div>

            {/* Catalog view: map or grid */}
            {registryView === "map" ? (
              <CatalogMap catalogs={filteredCatalogs} />
            ) : filteredCatalogs.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
                {filteredCatalogs.map((catalog) => (
                  <CatalogCard
                    key={catalog.id}
                    catalog={catalog}
                    onTagClick={handleTagToggle}
                  />
                ))}
              </div>
            ) : (
              <div className="text-center py-12">
                <p className="text-body text-p-ink-2">{t("registry.search.noResults")}</p>
                <button
                  type="button"
                  onClick={handleClearFilters}
                  className="mt-3 text-small text-p-primary hover:underline"
                >
                  {t("registry.search.clearFilters")}
                </button>
              </div>
            )}

            {/* Inline Submit */}
            <div className="mt-10 bg-p-paper border border-p-line rounded-[var(--p-r-lg)] p-6">
              <div className="flex flex-col md:flex-row md:items-center gap-4">
                <div className="flex-1">
                  <h3 className="text-card-title font-semibold text-p-ink">{t("registry.cta.title")}</h3>
                  <p className="text-body text-p-ink-2 mt-1">{t("registry.cta.description")}</p>
                </div>
                {submitState === "success" ? (
                  <div className="flex items-center gap-3">
                    <div className="flex items-center gap-2 text-body text-[var(--p-success)]">
                      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                      </svg>
                      {t("registry.submit.successTitle")}
                    </div>
                    {submitPrUrl && (
                      <a
                        href={submitPrUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-small text-p-primary hover:underline"
                      >
                        {t("registry.submit.viewPr")} <DirArrow />
                      </a>
                    )}
                    <button
                      type="button"
                      onClick={handleResetSubmit}
                      className="text-micro text-p-ink-3 hover:text-p-ink-2 underline"
                    >
                      {t("registry.submit.submitAnother")}
                    </button>
                  </div>
                ) : (
                  <div className="flex flex-col sm:flex-row gap-2 md:w-auto w-full">
                    <div className="flex-1 sm:min-w-[300px]">
                      <input
                        type="url"
                        value={submitUrl}
                        onChange={(e) => setSubmitUrl(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && isValidSubmitUrl && handleSubmitCatalog()}
                        placeholder="https://...catalog.json"
                        disabled={submitState === "submitting"}
                        className={`w-full bg-p-bg border rounded-[var(--p-r-md)] px-4 py-2.5 text-body text-p-ink placeholder:text-p-ink-3 focus:outline-none transition-colors disabled:opacity-50 ${
                          submitUrl && !isValidSubmitUrl ? "border-red-400" : "border-p-line focus:border-p-primary"
                        }`}
                      />
                      {submitUrl && !isValidSubmitUrl && (
                        <p className="text-micro text-red-500 mt-1">{t("registry.submit.urlError")}</p>
                      )}
                      {submitError && (
                        <p className="text-micro text-red-500 mt-1">{submitError}</p>
                      )}
                    </div>
                    <button
                      type="button"
                      onClick={handleSubmitCatalog}
                      disabled={!isValidSubmitUrl || submitState === "submitting"}
                      className={`px-5 py-2.5 rounded-[var(--p-r-md)] text-body font-medium transition-all whitespace-nowrap ${
                        isValidSubmitUrl && submitState !== "submitting"
                          ? "bg-p-primary text-white hover:opacity-90"
                          : "bg-p-line text-p-ink-3 cursor-not-allowed"
                      }`}
                    >
                      {submitState === "submitting" ? t("registry.submit.submitting") : t("registry.submit.submit")}
                    </button>
                  </div>
                )}
              </div>
            </div>
          </div>
        </section>
      )}

      {/* Footer */}
      <SiteFooter />
    </div>
  );
}
