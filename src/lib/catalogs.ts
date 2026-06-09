export interface CatalogValidation {
  stac_valid: boolean;
  has_versions_json: boolean;
  has_portolan_dir: boolean;
  has_llms_txt?: boolean;
}

export interface Catalog {
  id: string;
  url: string;
  title: string;
  description: string;
  stac_version: string;
  providers: unknown;
  keywords: string[] | null;
  bbox: [number, number, number, number] | null;
  license: string;
  collection_count: number;
  feature_count: number;
  last_crawled: string;
  validation: CatalogValidation;
}

export interface CatalogsResponse {
  generated: string;
  count: number;
  catalogs: Catalog[];
}

const CATALOGS_URL =
  "https://raw.githubusercontent.com/portolan-sdi/portolan-registry/main/exports/catalogs.json";

export async function getCatalogs(): Promise<CatalogsResponse> {
  const res = await fetch(CATALOGS_URL, {
    next: { revalidate: 3600 },
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch catalogs: ${res.status}`);
  }

  return res.json();
}

export function getValidationTier(validation: CatalogValidation): "unvalidated" | "basic" | "full" {
  const { stac_valid, has_versions_json, has_portolan_dir } = validation;

  if (stac_valid && has_versions_json && has_portolan_dir) {
    return "full";
  }
  if (stac_valid) {
    return "basic";
  }
  return "unvalidated";
}
