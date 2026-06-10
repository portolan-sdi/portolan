"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import { useCallback, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import DeckGL from "@deck.gl/react";
import { FlyToInterpolator, WebMercatorViewport } from "@deck.gl/core";
import { ScatterplotLayer, PolygonLayer } from "@deck.gl/layers";
import { Map } from "react-map-gl/maplibre";
import type { Catalog } from "@/lib/catalogs";
import { getValidationTier } from "@/lib/catalogs";
import { useResolvedTheme } from "@/hooks/use-resolved-theme";
import { MapGeocoder } from "./map-geocoder";
import { Tag, DirArrow } from "../ui";
import type { GeocodeSuggestion } from "@/hooks/use-geocode";

const CARTO_STYLE = {
  light: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json",
  dark: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
} as const;

const INITIAL_VIEW = { longitude: 0, latitude: 20, zoom: 1.3 };

const MIN_ZOOM = 1;
const MAX_ZOOM = 16;
const FIT_PADDING = 60;
const FIT_MAX_ZOOM = 6;

// One reused interpolator instance; recreating it per call is unnecessary.
const FLY = new FlyToInterpolator();

// Deck/maplibre render the world at 512px per tile; this converts a span in
// degrees to on-screen pixels at a given zoom so we can flip dots <-> rectangles.
const TILE_SIZE = 512;
const RECT_PX_THRESHOLD = 30;
const DEGENERATE_EPS = 1e-4;

type RGB = [number, number, number];

interface Coords {
  longitude: number;
  latitude: number;
  zoom: number;
}

interface LocatedCatalog {
  catalog: Catalog;
  west: number;
  south: number;
  east: number;
  north: number;
  crossesAntimeridian: boolean;
  widthDeg: number;
  heightDeg: number;
  centroid: [number, number];
  isDegenerate: boolean;
  ring: [number, number][];
}

function normalizeLon(lon: number): number {
  return ((lon + 540) % 360) - 180;
}

function clampZoom(zoom: number, max = MAX_ZOOM): number {
  if (!Number.isFinite(zoom)) return max;
  return Math.min(Math.max(zoom, MIN_ZOOM), max);
}

function hexToRgb(hex: string): RGB | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

// Read a Portolan color token from the live DOM so map colors track whatever
// the active light/dark theme defines (e.g. --p-primary differs per theme).
function readThemeColor(varName: string, fallback: RGB): RGB {
  if (typeof window === "undefined") return fallback;
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(varName)
    .trim();
  return hexToRgb(raw) ?? fallback;
}

// A located catalog renders as a rectangle once its bbox is large enough on
// screen, but never when degenerate or antimeridian-crossing (we never feed a
// west > east ring to PolygonLayer).
function showsRectangle(lc: LocatedCatalog, zoom: number): boolean {
  if (lc.isDegenerate || lc.crossesAntimeridian) return false;
  const scale = (TILE_SIZE * 2 ** zoom) / 360;
  const pxWidth = lc.widthDeg * scale;
  const pxHeight = lc.heightDeg * scale;
  return Math.max(pxWidth, pxHeight) >= RECT_PX_THRESHOLD;
}

interface CatalogMapProps {
  catalogs: Catalog[];
}

export default function CatalogMap({ catalogs }: CatalogMapProps) {
  const t = useTranslations("registry");
  const theme = useResolvedTheme();

  const containerRef = useRef<HTMLDivElement | null>(null);
  const didFit = useRef(false);

  const [view, setView] = useState<Coords>(INITIAL_VIEW);
  // When set, deck animates to `view` over this many ms; cleared when the
  // transition ends. Gating the transition props in state (rather than storing
  // them with the view) is what keeps flyTo/zoom transitions from stuttering.
  const [transitionMs, setTransitionMs] = useState<number | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [infoOpen, setInfoOpen] = useState(false);

  const { located, unlocatedCount } = useMemo(() => {
    const located: LocatedCatalog[] = [];
    let unlocatedCount = 0;

    for (const catalog of catalogs) {
      if (!catalog.bbox) {
        unlocatedCount++;
        continue;
      }
      const [west, south, east, north] = catalog.bbox;
      const crossesAntimeridian = west > east;
      const widthDeg = crossesAntimeridian ? east + 360 - west : east - west;
      const heightDeg = north - south;
      const rawMidLon = crossesAntimeridian
        ? west + widthDeg / 2
        : (west + east) / 2;
      const centroid: [number, number] = [
        normalizeLon(rawMidLon),
        (south + north) / 2,
      ];
      const isDegenerate =
        widthDeg <= DEGENERATE_EPS || heightDeg <= DEGENERATE_EPS;
      const ring: [number, number][] = [
        [west, south],
        [east, south],
        [east, north],
        [west, north],
        [west, south],
      ];
      located.push({
        catalog,
        west,
        south,
        east,
        north,
        crossesAntimeridian,
        widthDeg,
        heightDeg,
        centroid,
        isDegenerate,
        ring,
      });
    }

    return { located, unlocatedCount };
  }, [catalogs]);

  // Derived so a selection that filtering has removed simply resolves to null.
  const selected = useMemo(
    () => catalogs.find((c) => c.id === selectedId) ?? null,
    [catalogs, selectedId],
  );

  const { dots, rects } = useMemo(() => {
    const dots: LocatedCatalog[] = [];
    const rects: LocatedCatalog[] = [];
    for (const lc of located) {
      if (showsRectangle(lc, view.zoom)) rects.push(lc);
      else dots.push(lc);
    }
    return { dots, rects };
  }, [located, view.zoom]);

  // Map feature colors pulled from the active theme's tokens.
  const colors = useMemo(() => {
    const primary = readThemeColor("--p-primary", [65, 99, 204]);
    const accent = readThemeColor("--p-accent", [244, 184, 96]);
    const stroke: RGB = theme === "dark" ? [22, 30, 71] : [255, 255, 255]; // --p-paper-ish
    return {
      dotFill: [...primary, 235] as [number, number, number, number],
      dotSelected: [...accent, 255] as [number, number, number, number],
      dotStroke: [...stroke, 255] as [number, number, number, number],
      bboxFill: [...primary, 40] as [number, number, number, number],
      bboxLine: [...primary, 255] as [number, number, number, number],
    };
  }, [theme]);

  const layers = useMemo(
    () => [
      new PolygonLayer<LocatedCatalog>({
        id: "catalog-bboxes",
        data: rects,
        getPolygon: (d) => d.ring,
        filled: true,
        getFillColor: colors.bboxFill,
        stroked: true,
        getLineColor: colors.bboxLine,
        lineWidthUnits: "pixels",
        getLineWidth: 2,
        pickable: true,
        updateTriggers: {
          getFillColor: colors.bboxFill,
          getLineColor: colors.bboxLine,
        },
      }),
      new ScatterplotLayer<LocatedCatalog>({
        id: "catalog-dots",
        data: dots,
        getPosition: (d) => d.centroid,
        getFillColor: (d) =>
          d.catalog.id === selectedId ? colors.dotSelected : colors.dotFill,
        filled: true,
        stroked: true,
        getLineColor: colors.dotStroke,
        lineWidthUnits: "pixels",
        getLineWidth: 1.5,
        getRadius: 1500,
        radiusMinPixels: 6,
        radiusMaxPixels: 10,
        pickable: true,
        updateTriggers: {
          getFillColor: [selectedId, colors.dotFill, colors.dotSelected],
          getLineColor: colors.dotStroke,
        },
      }),
    ],
    [dots, rects, selectedId, colors],
  );

  const flyTo = useCallback((target: Coords, ms = 700) => {
    setView({
      longitude: target.longitude,
      latitude: target.latitude,
      zoom: clampZoom(target.zoom),
    });
    setTransitionMs(ms);
  }, []);

  const handleZoom = useCallback(
    (delta: number) => {
      setView((prev) => ({ ...prev, zoom: clampZoom(prev.zoom + delta) }));
      setTransitionMs(300);
    },
    [],
  );

  // Fit view to the union of all located bboxes (null if nothing to fit).
  const computeFitView = useCallback(
    (el: HTMLElement | null): Coords | null => {
    if (!el || el.clientWidth === 0 || located.length === 0) return null;

    let w = 180;
    let s = 90;
    let e = -180;
    let n = -90;
    for (const lc of located) {
      // Antimeridian-crossing extents are accumulated by their normalized
      // centroid so they don't blow the union out to the whole globe.
      if (lc.crossesAntimeridian) {
        w = Math.min(w, lc.centroid[0]);
        e = Math.max(e, lc.centroid[0]);
      } else {
        w = Math.min(w, lc.west);
        e = Math.max(e, lc.east);
      }
      s = Math.min(s, lc.south);
      n = Math.max(n, lc.north);
    }

    const vp = new WebMercatorViewport({
      width: el.clientWidth,
      height: el.clientHeight,
    });
    const { longitude, latitude, zoom } = vp.fitBounds(
      [
        [w, s],
        [e, n],
      ],
      { padding: FIT_PADDING },
    );
      return {
        longitude,
        latitude,
        zoom: Math.min(Math.max(zoom, 1.3), FIT_MAX_ZOOM),
      };
    },
    [located],
  );

  // Callback ref: measure the container and auto-fit once, on mount. Doing this
  // here (not in an effect) avoids set-state-in-effect and the layout flash.
  const setContainer = useCallback(
    (node: HTMLDivElement | null) => {
      containerRef.current = node;
      if (node && !didFit.current) {
        const fit = computeFitView(node);
        if (fit) {
          setView(fit);
          didFit.current = true;
        }
      }
    },
    [computeFitView],
  );

  const handleReset = useCallback(() => {
    flyTo(computeFitView(containerRef.current) ?? INITIAL_VIEW, 600);
  }, [flyTo, computeFitView]);

  const handleGeocode = useCallback(
    (sug: GeocodeSuggestion) => {
      const el = containerRef.current;
      if (sug.bbox && el && el.clientWidth > 0) {
        const [west, south, east, north] = sug.bbox;
        const vp = new WebMercatorViewport({
          width: el.clientWidth,
          height: el.clientHeight,
        });
        const { longitude, latitude, zoom } = vp.fitBounds(
          [
            [west, south],
            [east, north],
          ],
          { padding: FIT_PADDING },
        );
        flyTo({ longitude, latitude, zoom: clampZoom(zoom, 14) });
      } else {
        flyTo({ longitude: sug.lng, latitude: sug.lat, zoom: 10 });
      }
    },
    [flyTo],
  );

  const deckViewState = useMemo(
    () =>
      transitionMs != null
        ? { ...view, transitionDuration: transitionMs, transitionInterpolator: FLY }
        : view,
    [view, transitionMs],
  );

  const mapStyle = theme === "dark" ? CARTO_STYLE.dark : CARTO_STYLE.light;

  return (
    <>
      <div
        ref={setContainer}
        dir="ltr"
        className="relative h-[520px] md:h-[600px] rounded-[var(--p-r-lg)] border border-p-line overflow-hidden"
        role="application"
        aria-label={t("map.searchLabel")}
      >
        <DeckGL
          viewState={deckViewState}
          onViewStateChange={({ viewState: vs, interactionState }) => {
            const v = vs as Coords;
            // While a programmatic transition runs, leave `view` at its target
            // and only commit/clear when the animation finishes — committing
            // intermediate frames would cancel deck's own transition.
            if (transitionMs != null) {
              if (interactionState && !interactionState.inTransition) {
                setView({ longitude: v.longitude, latitude: v.latitude, zoom: v.zoom });
                setTransitionMs(null);
              }
              return;
            }
            setView({ longitude: v.longitude, latitude: v.latitude, zoom: v.zoom });
          }}
          controller={{
            dragRotate: false,
            touchRotate: false,
            scrollZoom: { smooth: true },
            inertia: 250,
          }}
          layers={layers}
          getCursor={({ isDragging, isHovering }) =>
            isDragging ? "grabbing" : isHovering ? "pointer" : "grab"
          }
          getTooltip={({ object }) =>
            object
              ? {
                  text: (object as LocatedCatalog).catalog.title,
                  style: {
                    fontFamily: "var(--p-mono)",
                    fontSize: "11px",
                    background: "var(--p-paper)",
                    color: "var(--p-ink)",
                    borderRadius: "var(--p-r-sm)",
                    padding: "4px 8px",
                  },
                }
              : null
          }
          onClick={(info) =>
            setSelectedId(
              (info.object as LocatedCatalog | undefined)?.catalog.id ?? null,
            )
          }
          style={{ position: "absolute", inset: "0" }}
        >
          <Map mapStyle={mapStyle} attributionControl={false} />
        </DeckGL>

        {/* Geocoder (top-left) */}
        <div className="absolute top-3 start-3 z-10">
          <MapGeocoder onSelect={handleGeocode} />
        </div>

        {/* Zoom + reset stack (top-right) */}
        <div className="absolute top-3 end-3 z-10 flex flex-col rounded-[var(--p-r-md)] overflow-hidden border border-p-line shadow-[var(--p-shadow-md)]">
          <button
            type="button"
            onClick={() => handleZoom(1)}
            aria-label={t("map.zoomIn")}
            className="flex items-center justify-center w-9 h-9 bg-p-paper text-p-ink-2 hover:text-p-ink hover:bg-p-bg-soft transition-colors border-b border-p-line"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
          </button>
          <button
            type="button"
            onClick={() => handleZoom(-1)}
            aria-label={t("map.zoomOut")}
            className="flex items-center justify-center w-9 h-9 bg-p-paper text-p-ink-2 hover:text-p-ink hover:bg-p-bg-soft transition-colors border-b border-p-line"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
          </button>
          <button
            type="button"
            onClick={handleReset}
            aria-label={t("map.reset")}
            className="flex items-center justify-center w-9 h-9 bg-p-paper text-p-ink-2 hover:text-p-ink hover:bg-p-bg-soft transition-colors"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3" />
              <line x1="12" y1="2" x2="12" y2="5" />
              <line x1="12" y1="19" x2="12" y2="22" />
              <line x1="2" y1="12" x2="5" y2="12" />
              <line x1="19" y1="12" x2="22" y2="12" />
            </svg>
          </button>
        </div>

        {/* Detail panel (bottom-left) */}
        {selected && (
          <div className="absolute bottom-3 start-3 z-10 w-[340px] max-w-[calc(100%-1.5rem)] bg-p-paper border border-p-line rounded-[var(--p-r-md)] p-4 shadow-[var(--p-shadow-lg)]">
            <div className="flex items-start justify-between gap-2">
              <h3 className="text-card-title font-semibold line-clamp-2">
                {selected.title}
              </h3>
              <button
                type="button"
                onClick={() => setSelectedId(null)}
                aria-label={t("map.closeDetails")}
                className="shrink-0 text-p-ink-3 hover:text-p-ink transition-colors"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
            <div className="mt-2">
              {(() => {
                const tier = getValidationTier(selected.validation);
                return (
                  <Tag
                    tone={tier === "full" ? "accent" : tier === "basic" ? "primary" : "default"}
                  >
                    {t(`validation.${tier}`)}
                  </Tag>
                );
              })()}
            </div>
            <p className="mt-3 text-body text-p-ink-2 line-clamp-2">
              {selected.description}
            </p>
            <a
              href={selected.url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-3 inline-block text-small text-p-primary hover:underline"
            >
              {t("card.viewCatalog")} <DirArrow />
            </a>
          </div>
        )}

        {/* Attribution + info (bottom-right) */}
        <div className="absolute bottom-3 end-3 z-10 flex items-center gap-2">
          {infoOpen && (
            <div className="w-[260px] max-w-[calc(100vw-2rem)] bg-p-paper border border-p-line rounded-[var(--p-r-md)] p-3 shadow-[var(--p-shadow-md)] text-micro text-p-ink-2 leading-relaxed">
              {t("map.infoBody")}
            </div>
          )}
          <div className="flex items-center gap-2 bg-p-paper/90 backdrop-blur-sm border border-p-line rounded-[var(--p-r-md)] px-2.5 py-1">
            <span className="text-micro text-p-ink-3 font-mono">
              {"© "}
              <a
                href="https://carto.com/attributions"
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-p-ink-2 underline underline-offset-2"
              >
                CARTO
              </a>
              {" © "}
              <a
                href="https://www.openstreetmap.org/copyright"
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-p-ink-2 underline underline-offset-2"
              >
                OpenStreetMap
              </a>
              {" contributors"}
            </span>
            <button
              type="button"
              onClick={() => setInfoOpen((v) => !v)}
              aria-label={t("map.info")}
              aria-expanded={infoOpen}
              className="shrink-0 flex items-center justify-center w-5 h-5 rounded-full border border-p-line text-p-ink-3 hover:text-p-ink hover:border-p-ink-3 transition-colors text-micro font-mono"
            >
              i
            </button>
          </div>
        </div>
      </div>

      {unlocatedCount > 0 && (
        <p className="mt-3 text-micro text-p-ink-3 font-mono">
          {t("map.noLocation", { count: unlocatedCount })}
        </p>
      )}
    </>
  );
}
