"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import dynamic from "next/dynamic";
import { useLocale, useTranslations } from "next-intl";
import { PageHero } from "./page-hero";
import { AWAY_ITEMS, SiteShell } from "./site-rail";
import { DirArrow, PROSE_LINK } from "./ui";
import { CatalogCard } from "./registry/catalog-card";
import type { MapState } from "./registry/catalog-map";
import type { Catalog } from "@/lib/catalogs";
import { formatDate } from "@/lib/catalogs";
import {
  EMPTY_EXPLORER_STATE,
  explorerParamString,
  type ExplorerState,
} from "@/lib/explorer-url";
import {
  buildIndex,
  catalogsInViewport,
  fetchCoverage,
  type CoverageIndex,
} from "@/lib/collection-points";

// The registry, on its own route.
//
// The page reads top to bottom: what the registry is, where the data sits, and
// which catalogs answer the place you are looking at. The map is the entry
// point, and the cards below it are the result.
//
// The map draws collection centroids. The results match on collection bboxes.
// Those are different geometries on purpose: a centroid says where to draw a
// point, and only a bbox can say whether a catalog reaches the view.

type SubmitState = "idle" | "submitting" | "success" | "error";

// Two rows of three on a wide screen.
const CARDS_PER_PAGE = 6;

// How long the URL waits after the last pan, keystroke, or page change.
const URL_DEBOUNCE_MS = 300;

const REGISTRY_REPO = "https://github.com/portolan-sdi/portolan-registry";

// The <reg> tag is part of the message contract and carries the same text span
// in every locale.
function registryLink(chunks: ReactNode) {
  return (
    <a
      href={REGISTRY_REPO}
      target="_blank"
      rel="noopener noreferrer"
      className={PROSE_LINK}
    >
      {chunks}
    </a>
  );
}

// Page control shared by the card grid and the talks row idiom.
function Pager({
  page,
  pageCount,
  onChange,
}: {
  page: number;
  pageCount: number;
  onChange: (next: number) => void;
}) {
  const t = useTranslations("registry.pagination");
  if (pageCount <= 1) return null;

  return (
    <div className="mt-8 flex items-center justify-end gap-4">
      <span className="font-mono text-small text-p-ink-3">
        {t("status", { page: String(page + 1), total: String(pageCount) })}
      </span>
      <div className="flex border border-p-line">
        <button
          type="button"
          onClick={() => onChange(page - 1)}
          disabled={page === 0}
          aria-label={t("prev")}
          className="px-3 py-1.5 text-p-ink transition-colors hover:bg-p-bg-soft disabled:text-p-ink-3 disabled:hover:bg-transparent cursor-pointer disabled:cursor-default"
        >
          {/* U+2039 is bidi-mirrored, so the engine flips it on an RTL page.
              The old rtl: swap mirrored it a second time, which made prev and
              next render as the same glyph in Arabic. */}
          <span aria-hidden="true">&#8249;</span>
        </button>
        <button
          type="button"
          onClick={() => onChange(page + 1)}
          disabled={page >= pageCount - 1}
          aria-label={t("next")}
          className="border-s border-p-line px-3 py-1.5 text-p-ink transition-colors hover:bg-p-bg-soft disabled:text-p-ink-3 disabled:hover:bg-transparent cursor-pointer disabled:cursor-default"
        >
          <span aria-hidden="true">&#8250;</span>
        </button>
      </div>
    </div>
  );
}

// Placeholder shown while the maplibre chunk and the bbox index load.
function MapSkeleton() {
  const t = useTranslations("registry");
  return (
    <div className="h-[440px] md:h-[540px] border border-p-line bg-p-bg-soft animate-pulse flex items-center justify-center">
      <span className="text-small text-p-ink-3 font-mono">{t("map.loading")}</span>
    </div>
  );
}

// registry-page is already a Client Component, so ssr:false is legal here.
const CatalogMap = dynamic(() => import("./registry/catalog-map"), {
  ssr: false,
  loading: () => <MapSkeleton />,
});

interface RegistryPageProps {
  catalogs?: Catalog[];
  /** Explorer state the request URL carried, read on the server. */
  initial?: ExplorerState;
}

/** Write the explorer state back, without touching the history stack. */
function writeExplorerUrl(state: ExplorerState) {
  const query = explorerParamString(state);
  window.history.replaceState(null, "", query ? `?${query}` : window.location.pathname);
}

export function RegistryPage({
  catalogs = [],
  initial = EMPTY_EXPLORER_STATE,
}: RegistryPageProps) {
  const t = useTranslations();
  const locale = useLocale();

  const [index, setIndex] = useState<CoverageIndex | null>(null);
  const [mapState, setMapState] = useState<MapState | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // The server read the URL, so the first paint already shows the shared
  // search. Reading it on the client instead would make the two disagree.
  const [searchQuery, setSearchQuery] = useState(initial.query);
  const [rawPage, setPage] = useState(initial.page);

  const [submitUrl, setSubmitUrl] = useState("");
  const [submitEmail, setSubmitEmail] = useState("");
  const [submitState, setSubmitState] = useState<SubmitState>("idle");
  const [submitPrUrl, setSubmitPrUrl] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const isValidSubmitUrl = submitUrl.trim().endsWith("catalog.json");
  // Same shape the API enforces. The registry writes to this address when a
  // catalog stops validating, so an entry without one is rejected at its gate.
  const isValidSubmitEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(submitEmail.trim());
  const canSubmit = isValidSubmitUrl && isValidSubmitEmail;

  useEffect(() => {
    const controller = new AbortController();
    fetchCoverage(controller.signal)
      .then((data) => setIndex(buildIndex(data)))
      .catch((err) => {
        if (err instanceof DOMException && err.name === "AbortError") return;
        console.error("Failed to load collection extents:", err);
      });
    return () => controller.abort();
  }, []);

  // Catalogs the crawl could place. The rest are named under the map.
  const locatedIds = useMemo(
    () => new Set((index?.catalogs ?? []).map((catalog) => catalog.id)),
    [index]
  );

  const titles = useMemo(
    () => new Map(catalogs.map((catalog) => [catalog.id, catalog.title])),
    [catalogs]
  );

  // viewport -> collection bbox overlap -> unique catalogs.
  const geoIds = useMemo(() => {
    if (!index || !mapState) return null;
    return catalogsInViewport(index, mapState.viewport);
  }, [index, mapState]);

  // A catalog the crawl could not place cannot be ruled out by geography, so
  // the viewport never hides it. A global catalog answers here through its own
  // bboxes, which overlap every view, even though the map draws no point for it.
  const inView = useMemo(
    () =>
      geoIds
        ? catalogs.filter(
            (catalog) => geoIds.has(catalog.id) || !locatedIds.has(catalog.id)
          )
        : catalogs,
    [catalogs, geoIds, locatedIds]
  );

  // The opening view holds every catalog, so it reads as no filter at all.
  // Mercator never shows the poles, so asking whether the viewport covers the
  // world would answer no even there.
  const geoActive = inView.length < catalogs.length;

  // Search runs inside the geographic set, never across it.
  const filteredCatalogs = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (query === "") return inView;
    return inView.filter(
      (catalog) =>
        catalog.title.toLowerCase().includes(query) ||
        catalog.id.toLowerCase().includes(query) ||
        Object.keys(catalog.licenses).some((id) => id.toLowerCase().includes(query))
    );
  }, [inView, searchQuery]);

  const pageCount = Math.max(1, Math.ceil(filteredCatalogs.length / CARDS_PER_PAGE));
  // Filtering can shrink the list under the current page.
  const page = Math.min(rawPage, pageCount - 1);
  const pagedCatalogs = filteredCatalogs.slice(
    page * CARDS_PER_PAGE,
    page * CARDS_PER_PAGE + CARDS_PER_PAGE
  );

  const handleMove = useCallback((state: MapState) => {
    setMapState(state);
    setPage(0);
  }, []);

  const handleSearch = useCallback((value: string) => {
    setSearchQuery(value);
    setPage(0);
  }, []);

  // Selecting from the map has to bring the card into view, which can mean
  // turning to the page that holds it.
  const handleSelect = useCallback(
    (id: string | null) => {
      setSelectedId((current) => (current === id ? null : id));
      if (!id) return;
      const at = filteredCatalogs.findIndex((catalog) => catalog.id === id);
      if (at >= 0) setPage(Math.floor(at / CARDS_PER_PAGE));
    },
    [filteredCatalogs]
  );

  useEffect(() => {
    if (!selectedId) return;
    const card = document.querySelector(`[data-catalog-id="${CSS.escape(selectedId)}"]`);
    card?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [selectedId, page]);

  // Escape drops the selection, alongside clicking the point again, clicking
  // the card title again, and clicking empty ground on the map.
  useEffect(() => {
    if (!selectedId) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelectedId(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedId]);

  // The URL follows the explorer, once the moving stops.
  useEffect(() => {
    const id = window.setTimeout(() => {
      writeExplorerUrl({
        view: mapState
          ? { zoom: mapState.zoom, latitude: mapState.latitude, longitude: mapState.longitude }
          : null,
        query: searchQuery,
        page,
      });
    }, URL_DEBOUNCE_MS);
    return () => window.clearTimeout(id);
  }, [mapState, searchQuery, page]);

  const crawledAt = formatDate(catalogs[0]?.last_crawled ?? null, locale);

  // Catalogs the map draws no point for. Either every extent is too broad to
  // stand for a place, or the crawl found no extent at all. Both still answer
  // the viewport filter and both still appear in the results.
  const offMapCount = useMemo(() => {
    const drawn = new Set(index?.points.map((point) => point.catalogId) ?? []);
    return catalogs.filter((catalog) => !drawn.has(catalog.id)).length;
  }, [catalogs, index]);

  const handleSubmitCatalog = async () => {
    if (!canSubmit || submitState === "submitting") return;

    setSubmitState("submitting");
    setSubmitError(null);

    try {
      const res = await fetch("/api/submit-catalog", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: submitUrl.trim(),
          submitterEmail: submitEmail.trim(),
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        if (res.status === 409) {
          throw new Error(t("registry.submit.alreadyExistsError"));
        }
        throw new Error(data.error || t("registry.submit.failedError"));
      }

      setSubmitPrUrl(data.pr_url);
      setSubmitState("success");
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : t("registry.submit.genericError"));
      setSubmitState("error");
    }
  };

  const handleResetSubmit = () => {
    setSubmitUrl("");
    setSubmitEmail("");
    setSubmitState("idle");
    setSubmitPrUrl(null);
    setSubmitError(null);
  };

  return (
    <SiteShell navItems={AWAY_ITEMS} activeId="registry">
      {/* The header band renders whether or not the listing loaded, so a
          failed fetch still returns a page with a title. */}
      <PageHero title={t("registry.title")}>
        {/* What the registry is, in two sentences. The name links to the
            repository the listing comes from. */}
        <p className="mt-6 text-lead text-p-ink-2">
          {t.rich("registry.intro", { reg: registryLink })}
        </p>
        {/* Mirrors are a transition state, so the note sits with the
            description rather than beside the listing it qualifies. */}
        <p className="mt-4 text-body italic text-p-ink-3">
          {t("registry.note")}
        </p>
      </PageHero>

      {catalogs.length > 0 && (
        <section id="registry" className="px-[var(--p-pad-section-x)] pb-[var(--p-pad-section-y)] pt-[clamp(28px,3.5vw,48px)]">
          <div className="max-w-[1240px] mx-auto">

            {/* The map. It filters the results below it as it moves. */}
            {index ? (
              <CatalogMap
                index={index}
                titles={titles}
                selectedId={selectedId}
                onSelect={handleSelect}
                onMove={handleMove}
                initialView={initial.view ?? null}
              />
            ) : (
              <MapSkeleton />
            )}

            {/* What matches, what the map cannot draw, and when the registry
                last read the catalogs. The count follows the map. */}
            <p className="mt-3 flex flex-wrap items-center gap-x-1.5 font-mono text-small text-p-ink-3">
              <span className="text-p-primary">
                {geoActive
                  ? t("registry.results.inView", { count: filteredCatalogs.length })
                  : t("registry.results.all", { count: filteredCatalogs.length })}
              </span>
              {index && offMapCount > 0 && (
                <>
                  <span aria-hidden="true">·</span>
                  <span>{t("registry.results.global", { count: offMapCount })}</span>
                </>
              )}
              {crawledAt && (
                <>
                  <span aria-hidden="true">·</span>
                  <span>{t("registry.lastChecked", { date: crawledAt })}</span>
                </>
              )}
            </p>

            {/* Results */}
            <div className="mt-10 border-t border-p-line pt-8">
              <input
                type="search"
                value={searchQuery}
                onChange={(e) => handleSearch(e.target.value)}
                placeholder={t("registry.search.placeholder")}
                aria-label={t("registry.search.placeholder")}
                className="w-full bg-p-paper border border-p-line px-4 py-2.5 text-body text-p-ink placeholder:text-p-ink-3 focus:outline-none focus:border-p-primary transition-colors sm:max-w-[360px]"
              />

              {filteredCatalogs.length > 0 ? (
                <>
                  <div className="mt-6 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5 items-stretch">
                    {pagedCatalogs.map((catalog) => (
                      <CatalogCard
                        key={catalog.id}
                        catalog={catalog}
                        selected={catalog.id === selectedId}
                        onSelect={handleSelect}
                      />
                    ))}
                  </div>
                  <Pager page={page} pageCount={pageCount} onChange={setPage} />
                </>
              ) : (
                <div className="py-12 text-center">
                  <p className="text-body text-p-ink-2">{t("registry.search.noResults")}</p>
                </div>
              )}
            </div>

            {/* Inline Submit */}
            <div className="mt-10 bg-p-paper border border-p-line rounded-[var(--p-r-lg)] p-6">
              <div className="flex flex-col lg:flex-row lg:items-center gap-4">
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
                      className="text-small text-p-ink-3 hover:text-p-ink-2 underline"
                    >
                      {t("registry.submit.submitAnother")}
                    </button>
                  </div>
                ) : (
                  <form
                    onSubmit={(event) => {
                      event.preventDefault();
                      void handleSubmitCatalog();
                    }}
                    noValidate
                    aria-busy={submitState === "submitting"}
                    aria-describedby={submitError ? "registry-submit-error" : undefined}
                    className="lg:w-auto w-full">
                    <div className="flex flex-col lg:flex-row gap-2">
                    <div className="flex-1 lg:min-w-[260px]">
                      <label htmlFor="registry-submit-url" className="sr-only">{t("registry.submit.urlLabel")}</label>
                      <input
                        id="registry-submit-url"
                        type="url"
                        value={submitUrl}
                        onChange={(e) => setSubmitUrl(e.target.value)}
                        placeholder={t("registry.submit.urlPlaceholder")}
                        required
                        aria-invalid={submitUrl !== "" && !isValidSubmitUrl}
                        aria-describedby={submitUrl !== "" && !isValidSubmitUrl ? "registry-submit-url-error" : undefined}
                        disabled={submitState === "submitting"}
                        className={`w-full bg-p-bg border rounded-[var(--p-r-md)] px-4 py-2.5 text-body text-p-ink placeholder:text-p-ink-3 focus:outline-none transition-colors disabled:opacity-50 ${
                          submitUrl && !isValidSubmitUrl ? "border-p-danger" : "border-p-line focus:border-p-primary"
                        }`}
                      />
                      {submitUrl && !isValidSubmitUrl && (
                        <p id="registry-submit-url-error" className="text-small text-p-danger mt-1" role="alert">{t("registry.submit.urlError")}</p>
                      )}
                    </div>
                    <div className="lg:w-[200px]">
                      <label htmlFor="registry-submit-email" className="sr-only">{t("registry.submit.emailInputLabel")}</label>
                      <input
                        id="registry-submit-email"
                        type="email"
                        value={submitEmail}
                        onChange={(e) => setSubmitEmail(e.target.value)}
                        placeholder={t("registry.submit.emailPlaceholder")}
                        required
                        aria-describedby={submitEmail !== "" && !isValidSubmitEmail ? "registry-submit-email-error" : undefined}
                        aria-invalid={submitEmail !== "" && !isValidSubmitEmail}
                        disabled={submitState === "submitting"}
                        className={`w-full bg-p-bg border rounded-[var(--p-r-md)] px-4 py-2.5 text-body text-p-ink placeholder:text-p-ink-3 focus:outline-none transition-colors disabled:opacity-50 ${
                          submitEmail && !isValidSubmitEmail ? "border-p-danger" : "border-p-line focus:border-p-primary"
                        }`}
                      />
                      {submitEmail && !isValidSubmitEmail && (
                        <p id="registry-submit-email-error" className="text-small text-p-danger mt-1" role="alert">{t("registry.submit.emailError")}</p>
                      )}
                    </div>
                    <button
                      type="submit"
                      disabled={!canSubmit || submitState === "submitting"}
                      className={`px-5 py-2.5 rounded-[var(--p-r-md)] text-body font-semibold transition-colors whitespace-nowrap lg:self-start ${
                        canSubmit && submitState !== "submitting"
                          ? "bg-p-primary text-p-on-primary hover:bg-p-primary-ink"
                          : "bg-p-line text-p-ink-3 cursor-not-allowed"
                      }`}
                    >
                      {submitState === "submitting" ? t("registry.submit.submitting") : t("registry.submit.submit")}
                    </button>
                    </div>
                    {submitError && (
                      <p id="registry-submit-error" className="text-small text-p-danger mt-1" role="alert" aria-live="assertive" tabIndex={-1}>{submitError}</p>
                    )}
                  </form>
                )}
              </div>
            </div>
          </div>
        </section>
      )}
    </SiteShell>
  );
}
