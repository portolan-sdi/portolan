"use client";

import { useTranslations } from "next-intl";
import { Card, Tag, DirArrow } from "../ui";
import type { Catalog } from "@/lib/catalogs";
import { getValidationTier } from "@/lib/catalogs";

interface CatalogCardProps {
  catalog: Catalog;
  onTagClick?: (tag: string) => void;
}

function getRegionFromBbox(bbox: [number, number, number, number] | null) {
  if (!bbox) return null;
  const [west, south, east, north] = bbox;
  const centerLat = (south + north) / 2;
  const centerLon = (west + east) / 2;

  return {
    lat: Math.abs(centerLat).toFixed(0),
    latDir: centerLat >= 0 ? ("north" as const) : ("south" as const),
    lon: Math.abs(centerLon).toFixed(0),
    lonDir: centerLon >= 0 ? ("east" as const) : ("west" as const),
  };
}

export function CatalogCard({ catalog, onTagClick }: CatalogCardProps) {
  const t = useTranslations("registry");
  const tier = getValidationTier(catalog.validation);
  const region = getRegionFromBbox(catalog.bbox);

  return (
    <Card className="flex flex-col gap-3">
      <div className="flex justify-between items-start gap-2">
        <h3 className="text-card-title font-semibold line-clamp-2">{catalog.title}</h3>
        <Tag
          tone={tier === "full" ? "accent" : tier === "basic" ? "primary" : "default"}
          className="shrink-0"
        >
          {t(`validation.${tier}`)}
        </Tag>
      </div>

      <p className="text-body text-p-ink-2 line-clamp-2">{catalog.description}</p>

      <div className="flex flex-wrap gap-2 text-micro text-p-ink-3 font-mono">
        <span>{t("card.collections", { count: catalog.collection_count })}</span>
        <span>·</span>
        <span>STAC {catalog.stac_version}</span>
        {region && (
          <>
            <span>·</span>
            <span>
              {region.lat}
              {t(`compass.${region.latDir}`)}, {region.lon}
              {t(`compass.${region.lonDir}`)}
            </span>
          </>
        )}
      </div>

      {catalog.keywords && catalog.keywords.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-1">
          {catalog.keywords.slice(0, 3).map((keyword) => (
            <button
              key={keyword}
              type="button"
              onClick={() => onTagClick?.(keyword)}
              className="text-micro font-mono px-2 py-1 rounded-[var(--p-r-sm)] bg-p-bg-soft border border-p-line-soft text-p-ink-3 hover:text-p-ink-2 hover:bg-p-line transition-colors"
            >
              {keyword}
            </button>
          ))}
        </div>
      )}

      <a
        href={catalog.url}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-auto text-small text-p-primary hover:underline"
      >
        {t("card.viewCatalog")} <DirArrow />
      </a>
    </Card>
  );
}
