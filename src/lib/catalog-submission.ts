type FetchCatalog = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

const CATALOG_FETCH_TIMEOUT_MS = 10_000;
const MAX_REGISTRY_ID_LENGTH = 80;

export function registryIdFromCatalogId(catalogId: unknown): string {
  if (typeof catalogId !== "string") {
    throw new Error("The root catalog has no string id");
  }

  const registryId = catalogId
    .trim()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, MAX_REGISTRY_ID_LENGTH)
    .replace(/-+$/g, "");

  if (!registryId) {
    throw new Error("The root catalog id cannot form a registry id");
  }

  return registryId;
}

export async function registryIdFromCatalog(
  url: string,
  fetchCatalog: FetchCatalog = fetch,
): Promise<string> {
  const response = await fetchCatalog(url, {
    cache: "no-store",
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(CATALOG_FETCH_TIMEOUT_MS),
  });

  if (!response.ok) {
    throw new Error(`The root catalog returned HTTP ${response.status}`);
  }

  const catalog: unknown = await response.json();
  if (!catalog || typeof catalog !== "object") {
    throw new Error("The root catalog is not a JSON object");
  }

  return registryIdFromCatalogId((catalog as { id?: unknown }).id);
}

export async function registryEntryExists(
  entryUrl: string,
  token: string,
  fetchEntry: FetchCatalog = fetch,
): Promise<boolean> {
  const response = await fetchEntry(entryUrl, {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
    },
  });

  if (response.ok) return true;
  if (response.status === 404) return false;

  throw new Error(`Failed to check registry id: HTTP ${response.status}`);
}
