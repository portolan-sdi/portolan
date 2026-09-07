"use client";

import { useEffect, useRef, useState } from "react";
import { createGlyphScene, createGlyphOrthographicCamera } from "glyphcss";

interface GlyphMapCanvasProps {
  className?: string;
  /** Drift speed in CSS pixels per second. Ignored when `still` is set. */
  pxPerSecond?: number;
  /**
   * Hold the map still. The page header band uses this: the homepage carries
   * the one moving element on the site, and repeating that drift above every
   * other page would make the motion ordinary rather than a moment.
   */
  still?: boolean;
}

/** The baked elevation grid written by scripts/bake-world-map.mjs. */
interface WorldRelief {
  n: number;
  x: number[];
  y: number[];
  z: number[];
  b: number[];
}

type Vec3 = [number, number, number];

/**
 * Elevation ramp. The band index is a height.
 *
 * Band 0 alone is water. It holds 67.8 percent of the cells and its mean
 * elevation is 0.0002, against 0.0016 and up for every other band. Bands 1 to
 * 8 are land and together they hold 32.2 percent, which matches the real land
 * fraction. Bands 1 and 2 are lowland and they alone carry 58 percent of the
 * land, so painting them as water erases most of every continent.
 *
 * Water sits just off the page colour, the way the reference map sets its sea
 * just off its own near-black page. Land then darkens with height.
 *
 * The ramp runs the full range on purpose. A band set of mid tints gives the
 * map nothing to anchor on and it reads as flat. Lowland starts at a clear
 * blue and the peaks land near navy, so the coastline has an edge and the
 * relief has somewhere to travel.
 */
const BAND_COLORS = [
  "#dfe6f5",
  "#93a6e4",
  "#7b8fdb",
  "#6478d2",
  "#5064c6",
  "#3f53b6",
  "#3244a1",
  "#26358a",
  "#1b2870",
];

/**
 * Camera and light settings, from the reference glyphcss flat map.
 *
 * These match the reference exactly. The shaded render carries almost no glyph
 * variety, and it is not supposed to: a capture of the reference returns 30,770
 * `@` out of about 34,000 cells and only six distinct characters in total.
 * Colour carries the shading and the glyph is a uniform fill. Driving the light
 * down to spread the character ramp instead only adds noise.
 */
const ROT_X = 40;
const ROT_Y = 0;
const RELIEF = 0.2;
const DENSITY = 2;
const LIGHT_AZ = 50;
const LIGHT_EL = 50;
const LIGHT_INTENSITY = 1.15;
const AMBIENT_INTENSITY = 0.4;

/**
 * Nominal width of one world unit, in CSS pixels.
 *
 * The orthographic camera projects one world unit to `zoom` pixels and the
 * plane spans -1 to 1, so a whole world is twice this figure. The value is a
 * target. `build` rounds the world to a whole number of glyph cells and derives
 * the camera zoom from that count, so the raster repeats on a cell boundary.
 */
const ZOOM = 550;

/** Glyph cell size in pixels before the density divisor. */
const BASE_FONT_PX = 13;

/**
 * Drift speed.
 *
 * The supporter logo marquee below the hero moves a 1405 px track in 42 s, so
 * 33.45 px/s. The map ran at that same rate and the two strips then read as one
 * coupled mechanism, because nothing separated them. The map is the layer
 * behind, so it travels slower. The ratio is deliberately not a simple
 * fraction, so the two never settle into step.
 */
const MARQUEE_PX_PER_SECOND = 1405 / 42;
const DEFAULT_PX_PER_SECOND = MARQUEE_PX_PER_SECOND * 0.38;

/** Unit vector toward the light, from azimuth and elevation in degrees. */
function lightDirection(azDeg: number, elDeg: number): Vec3 {
  const az = (azDeg * Math.PI) / 180;
  const el = (elDeg * Math.PI) / 180;
  return [
    Math.cos(el) * Math.cos(az),
    Math.cos(el) * Math.sin(az),
    Math.sin(el),
  ];
}

/**
 * Expand the grid into one quad per cell.
 *
 * The `y` axis carries longitude from -1 to 1. `lonOffset` shifts a copy of
 * the world along it, so a whole number of worlds sit side by side in one
 * scene. The elevation at -1 equals the elevation at 1 to the last digit, so
 * two copies meet with no step.
 */
function buildPolygons(grid: WorldRelief, lonOffset = 0) {
  const { n, x, y, z, b } = grid;
  const w = n + 1;
  const polygons = new Array(n * n);
  for (let iy = 0; iy < n; iy++) {
    const y0 = y[iy] + lonOffset;
    const y1 = y[iy + 1] + lonOffset;
    for (let ix = 0; ix < n; ix++) {
      polygons[iy * n + ix] = {
        vertices: [
          [x[ix], y0, z[iy * w + ix]],
          [x[ix + 1], y0, z[iy * w + ix + 1]],
          [x[ix + 1], y1, z[(iy + 1) * w + ix + 1]],
          [x[ix], y1, z[(iy + 1) * w + ix]],
        ] as Vec3[],
        color: BAND_COLORS[b[iy * n + ix]] ?? BAND_COLORS[0],
      };
    }
  }
  return polygons;
}

/** Type settings of the glyph raster. The cell probe carries the same ones. */
function styleOutput(el: HTMLElement) {
  el.style.fontSize = `${BASE_FONT_PX / DENSITY}px`;
  el.style.fontFamily = "var(--p-mono)";
  // Cells butt against each other, so any leading between rows shows up as
  // banding across the map.
  el.style.lineHeight = "1";
}

/** One glyph cell, in CSS pixels. */
interface CellMetrics {
  w: number;
  h: number;
}

/**
 * Measure one glyph cell the way glyphcss does: a hidden `pre` of twenty `M`
 * rows, one per line, in the raster's own type settings.
 *
 * The probe is the first text on the page in the mono web font at this size,
 * so it starts the font request. The first box read forces layout, which puts
 * that request in flight, and `fonts.ready` then waits for it. A cell measured
 * in the fallback font would set a column count that the real font renders at
 * a different width, and the raster would no longer fill its tile.
 */
async function measureCell(host: HTMLElement): Promise<CellMetrics> {
  const probe = document.createElement("pre");
  probe.textContent = Array(20).fill("M").join("\n");
  styleOutput(probe);
  probe.style.cssText +=
    ";position:absolute;visibility:hidden;white-space:pre;" +
    "padding:0;margin:0;pointer-events:none";
  host.appendChild(probe);
  try {
    probe.getBoundingClientRect();
    await document.fonts?.ready;
    const rect = probe.getBoundingClientRect();
    return { w: rect.width || 8, h: rect.height ? rect.height / 20 : 16 };
  } finally {
    probe.remove();
  }
}

export default function GlyphMapCanvas({
  className = "",
  pxPerSecond = DEFAULT_PX_PER_SECOND,
  still = false,
}: GlyphMapCanvasProps) {
  const frameRef = useRef<HTMLDivElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const frame = frameRef.current;
    const track = trackRef.current;
    if (!frame || !track) return;

    let disposed = false;
    let scene: ReturnType<typeof createGlyphScene> | null = null;
    let resizeTimer: number | undefined;
    let buildToken = 0;
    let stopObserving = () => {};

    const reducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;

    /**
     * Rasterize one continuous strip of worlds, then drift it by one world.
     *
     * The map never re-rasterizes while it drifts. A character cell is about
     * 3.9 px wide and the drift covers about 13 px per second, so a re-render
     * loop would advance the image only a few times a second whatever the
     * frame rate. Translating the finished raster keeps the motion on the
     * compositor and off the main thread.
     *
     * The strip holds the frame width plus one extra world, and the worlds in
     * it are one mesh, so no join exists between them. The loop then moves the
     * strip by exactly one world and snaps back. One world is a whole number
     * of columns by construction, so the glyph under any pixel is the same
     * before and after the snap.
     *
     * An earlier version tiled copies of a one-world raster in boxes that were
     * `2 * zoom` pixels wide. The raster was a whole number of cells and the
     * box was not, so every join left a blank column at the antimeridian.
     */
    async function build(grid: WorldRelief, token: number) {
      if (disposed || !frame || !track) return;

      scene?.destroy();
      scene = null;
      track.replaceChildren();

      const box = frame.getBoundingClientRect();
      const frameWidth = box.width || 1;
      const height = box.height || 1;

      const cell = await measureCell(frame);
      if (disposed || token !== buildToken) return;

      // One world is a whole number of columns. The camera projects with the
      // same measured cell, so the zoom below lands each world edge on a cell
      // boundary.
      const worldCols = Math.max(1, Math.round((ZOOM * 2) / cell.w));
      const zoom = (worldCols * cell.w) / 2;

      // Columns the strip needs: the frame, plus one world to travel through.
      // glyphcss floors the integer host width over the cell, so the stage is
      // one pixel wider than the need to keep the floor at or above it.
      const frameCols = Math.ceil(frameWidth / cell.w);
      const neededCols = frameCols + (still ? 0 : worldCols);
      const stageWidth = Math.ceil(neededCols * cell.w) + 1;

      const stage = document.createElement("div");
      stage.style.cssText =
        `position:absolute;left:0;top:0;width:${stageWidth}px;` +
        `height:${height}px;visibility:hidden`;
      frame.appendChild(stage);

      const camera = createGlyphOrthographicCamera({
        rotX: ROT_X,
        rotY: ROT_Y,
        zoom,
      });
      camera.target = [0, 0, 0];

      scene = createGlyphScene(stage, {
        camera,
        autoSize: true,
        mode: "solid",
        charMode: "ascii",
        useColors: true,
        glyphPalette: "default",
        // Rasterize at 2x and average down. The map is drawn once and then
        // translated, so the documented N-squared cost lands on a single
        // frame at load and buys smoother coastlines for the whole session.
        supersample: 2,
        directionalLight: {
          direction: lightDirection(LIGHT_AZ, LIGHT_EL),
          intensity: LIGHT_INTENSITY,
        },
        ambientLight: { intensity: AMBIENT_INTENSITY },
      });
      styleOutput(scene.output);
      scene.fit();
      const cols = scene.getOptions().cols ?? neededCols;

      // World copy `j` is centred on column `centre + j * worldCols`. Add the
      // copies that touch the raster, with a one column margin on each side.
      const centre = cols / 2;
      const margin = 1;
      const first = Math.floor((-margin - centre) / worldCols - 0.5) + 1;
      const last = Math.ceil((cols + margin - centre) / worldCols + 0.5) - 1;
      const polygons = [];
      for (let j = first; j <= last; j++) {
        polygons.push(...buildPolygons(grid, 2 * j));
      }
      scene.add(polygons, { scale: [1, 1, RELIEF] });
      scene.rerender();

      // The rendered cell can differ from the measured one by a fraction of a
      // pixel, so the drift distance comes from the raster itself.
      const source = scene.output;
      const renderedWidth = source.getBoundingClientRect().width;
      const worldPx = (renderedWidth / cols) * worldCols;

      stage.remove();
      source.style.margin = "0";
      track.appendChild(source);

      track.style.setProperty("--glyph-drift-distance", `${worldPx}px`);
      track.style.setProperty(
        "--glyph-drift-duration",
        `${(worldPx / pxPerSecond).toFixed(2)}s`
      );
      track.dataset.drifting = reducedMotion || still ? "false" : "true";
    }

    async function start() {
      let grid: WorldRelief;
      try {
        const res = await fetch("/data/world-relief.json");
        if (!res.ok) throw new Error(`relief fetch failed: ${res.status}`);
        grid = await res.json();
      } catch (err) {
        console.error("Glyph map terrain failed to load:", err);
        if (!disposed) setFailed(true);
        return;
      }
      if (disposed || !frame) return;

      try {
        await build(grid, ++buildToken);
      } catch (err) {
        console.error("Glyph map failed to start:", err);
        if (!disposed) setFailed(true);
        return;
      }
      if (!disposed) setReady(true);

      // The rail collapse resizes the column without a window resize event, so
      // the frame is observed directly. Only the column count and the raster
      // height depend on the frame, so a rebuild is cheap and rare.
      let last = frame.getBoundingClientRect();
      const observer = new ResizeObserver(() => {
        const now = frame.getBoundingClientRect();
        if (
          Math.abs(now.width - last.width) < 8 &&
          Math.abs(now.height - last.height) < 8
        ) {
          return;
        }
        last = now;
        window.clearTimeout(resizeTimer);
        resizeTimer = window.setTimeout(() => {
          if (disposed) return;
          build(grid, ++buildToken).catch((err) => {
            console.error("Glyph map failed to rebuild:", err);
          });
        }, 220);
      });
      observer.observe(frame);
      stopObserving = () => observer.disconnect();
    }

    void start();

    return () => {
      disposed = true;
      buildToken++;
      window.clearTimeout(resizeTimer);
      stopObserving();
      scene?.destroy();
    };
  }, [pxPerSecond, still]);

  if (failed) return null;

  // The map is a raster of text glyphs, so a right-to-left page reverses every
  // glyph row and flips the tile order. The frame stays LTR in every locale,
  // the same way a terminal block does.
  return (
    <div
      ref={frameRef}
      dir="ltr"
      className={`relative overflow-hidden pointer-events-none transition-opacity duration-700 ${
        ready ? "opacity-100" : "opacity-0"
      } ${className}`}
      aria-hidden="true"
    >
      <div ref={trackRef} className="glyph-drift" />
    </div>
  );
}
