"""
CatalogSource model for federated catalog tracking.

This module enables tracking and syncing with upstream catalogs like STAC, ArcGIS, etc.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class CatalogSource:
    """An upstream catalog that can be synced."""

    name: str  # Unique identifier (e.g., "earth-search")
    type: str  # stac, arcgis, wfs, portolan
    url: str  # Catalog URL
    last_sync: str | None = None  # ISO timestamp of last sync
    sync_hash: str | None = None  # Hash of last synced state
    filters: dict = field(default_factory=dict)  # Optional filters (collections, bbox, etc.)
    created_at: str | None = None

    def to_dict(self) -> dict:
        result = {
            "name": self.name,
            "type": self.type,
            "url": self.url,
        }
        if self.last_sync:
            result["last_sync"] = self.last_sync
        if self.sync_hash:
            result["sync_hash"] = self.sync_hash
        if self.filters:
            result["filters"] = self.filters
        if self.created_at:
            result["created_at"] = self.created_at
        return result

    @classmethod
    def from_dict(cls, data: dict) -> CatalogSource:
        return cls(
            name=data["name"],
            type=data["type"],
            url=data["url"],
            last_sync=data.get("last_sync"),
            sync_hash=data.get("sync_hash"),
            filters=data.get("filters", {}),
            created_at=data.get("created_at"),
        )


class CatalogSourceStore:
    """Manages catalog source storage in .portolan/sources.json."""

    def __init__(self, portolan_dir: Path):
        self.portolan_dir = portolan_dir
        self.sources_file = portolan_dir / "sources.json"

    def _load(self) -> dict:
        if not self.sources_file.exists():
            return {"sources": {}}
        with open(self.sources_file) as f:
            return json.load(f)

    def _save(self, data: dict) -> None:
        with open(self.sources_file, "w") as f:
            json.dump(data, f, indent=2)

    def list_sources(self) -> list[CatalogSource]:
        """List all registered catalog sources."""
        data = self._load()
        return [
            CatalogSource.from_dict(s)
            for s in data.get("sources", {}).values()
        ]

    def get_source(self, name: str) -> CatalogSource | None:
        """Get a specific catalog source by name."""
        data = self._load()
        source_data = data.get("sources", {}).get(name)
        if source_data:
            return CatalogSource.from_dict(source_data)
        return None

    def add_source(self, source: CatalogSource) -> None:
        """Add or update a catalog source."""
        data = self._load()
        data["sources"][source.name] = source.to_dict()
        self._save(data)

    def remove_source(self, name: str) -> bool:
        """Remove a catalog source. Returns True if removed."""
        data = self._load()
        if name in data.get("sources", {}):
            del data["sources"][name]
            self._save(data)
            return True
        return False

    def update_sync_state(self, name: str, sync_hash: str) -> None:
        """Update the sync state after a successful sync."""
        data = self._load()
        if name in data.get("sources", {}):
            data["sources"][name]["last_sync"] = datetime.now(timezone.utc).isoformat()
            data["sources"][name]["sync_hash"] = sync_hash
            self._save(data)


# =============================================================================
# Sync Logic
# =============================================================================


def compute_catalog_hash(items: list[dict]) -> str:
    """Compute a hash of catalog items for change detection."""
    # Sort by ID for consistent hashing
    sorted_items = sorted(items, key=lambda x: x.get("id", x.get("name", "")))
    content = json.dumps(sorted_items, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def fetch_json(url: str) -> dict:
    """Fetch JSON from a URL."""
    import httpx

    response = httpx.get(url, follow_redirects=True, timeout=30)
    response.raise_for_status()
    return response.json()


def get_stac_links(stac_obj: dict, rel: str) -> list[dict]:
    """Get links with a specific rel from a STAC object."""
    return [link for link in stac_obj.get("links", []) if link.get("rel") == rel]


def resolve_url(base_url: str, href: str) -> str:
    """Resolve a relative URL against a base URL."""
    from urllib.parse import urljoin
    return urljoin(base_url, href)


def sync_stac_catalog(
    source: CatalogSource,
    resources_dir: Path,
    max_items: int = 100,
    verbose: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Sync a STAC catalog and return sync results.

    Returns:
        dict with keys: added, updated, unchanged, errors, new_hash
    """
    from portolan_resource import (
        Origin,
        Resource,
        ResourceMetadata,
        SourceMetadata,
        Upstream,
        UserMetadata,
        save_resource,
    )

    results = {
        "added": [],
        "updated": [],
        "unchanged": [],
        "errors": [],
        "new_hash": None,
    }

    # Fetch the catalog
    try:
        root = fetch_json(source.url)
    except Exception as e:
        results["errors"].append(f"Failed to fetch catalog: {e}")
        return results

    # Collect items
    items = []
    collections_filter = source.filters.get("collections", [])

    def crawl_catalog(catalog_url: str, catalog_obj: dict, depth: int = 0):
        """Recursively crawl a STAC catalog."""
        if max_items > 0 and len(items) >= max_items:
            return

        # Process child catalogs/collections
        child_links = get_stac_links(catalog_obj, "child")
        for link in child_links:
            if max_items > 0 and len(items) >= max_items:
                break

            child_url = resolve_url(catalog_url, link["href"])

            try:
                child = fetch_json(child_url)
                child_type = child.get("type", "Catalog")
                child_id = child.get("id", "unknown")

                # Check collection filter
                if collections_filter and child_type == "Collection" and child_id not in collections_filter:
                    continue

                crawl_catalog(child_url, child, depth + 1)

            except Exception as e:
                if verbose:
                    results["errors"].append(f"Error fetching {child_url}: {e}")

        # Process items
        item_links = get_stac_links(catalog_obj, "item")
        for link in item_links:
            if max_items > 0 and len(items) >= max_items:
                break

            item_url = resolve_url(catalog_url, link["href"])

            try:
                item = fetch_json(item_url)
                item["_stac_url"] = item_url
                items.append(item)
            except Exception as e:
                if verbose:
                    results["errors"].append(f"Error fetching item {item_url}: {e}")

        # Check for items link (STAC API style)
        items_links = get_stac_links(catalog_obj, "items")
        for link in items_links:
            if max_items > 0 and len(items) >= max_items:
                break

            items_url = resolve_url(catalog_url, link["href"])

            try:
                items_response = fetch_json(items_url)
                features = items_response.get("features", [])

                for item in features:
                    if max_items > 0 and len(items) >= max_items:
                        break
                    item["_stac_url"] = items_url
                    items.append(item)

            except Exception as e:
                if verbose:
                    results["errors"].append(f"Error fetching items {items_url}: {e}")

    # Crawl the catalog
    crawl_catalog(source.url, root)

    # Compute new hash
    results["new_hash"] = compute_catalog_hash(items)

    # Check if anything changed
    if source.sync_hash == results["new_hash"]:
        results["unchanged"] = [item.get("id", "unknown") for item in items]
        return results

    if dry_run:
        results["added"] = [item.get("id", "unknown") for item in items]
        return results

    # Create resources directory for this source
    namespace = f"federated_{source.name}"
    source_resources_dir = resources_dir / namespace
    source_resources_dir.mkdir(parents=True, exist_ok=True)

    # Process each item
    for item in items:
        item_id = item.get("id", "unknown")
        stac_url = item.pop("_stac_url", source.url)

        # Sanitize name
        name = item_id.lower().replace(" ", "_").replace("-", "_")
        name = "".join(c for c in name if c.isalnum() or c == "_")
        if not name or not name[0].isalpha():
            name = f"item_{name}"

        # Extract metadata from STAC item
        properties = item.get("properties", {})
        bbox = item.get("bbox", [])
        assets = item.get("assets", {})

        # Find primary asset URL
        primary_asset = None
        for key in ["data", "visual", "image", "default"]:
            if key in assets:
                primary_asset = assets[key]
                break
        if not primary_asset and assets:
            primary_asset = next(iter(assets.values()))

        asset_url = primary_asset.get("href") if primary_asset else None

        # Check if resource already exists
        resource_path = source_resources_dir / f"{name}.json"
        is_update = resource_path.exists()

        # Create or update resource
        resource = Resource(
            name=name,
            kind="vector",  # Default, could be detected from asset type
            origin=Origin(
                type="stac",
                url=stac_url,
                stac_collection=item.get("collection"),
                stac_item_id=item_id,
            ),
            metadata=ResourceMetadata(
                user=UserMetadata(
                    title=properties.get("title") or item_id,
                    description=properties.get("description", ""),
                ),
                source=SourceMetadata(
                    provider="stac",
                    ref={"stac_url": stac_url, "item_id": item_id},
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    data={
                        "bbox": bbox,
                        "properties": properties,
                        "assets": {k: {"href": v.get("href"), "type": v.get("type")} for k, v in assets.items()},
                    },
                ),
            ),
            upstream=Upstream(
                catalog=source.name,
                type="stac",
                id=item_id,
            ),
            created_at=datetime.now(timezone.utc).isoformat() if not is_update else None,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

        try:
            save_resource(resource, resource_path)
            if is_update:
                results["updated"].append(name)
            else:
                results["added"].append(name)
        except Exception as e:
            results["errors"].append(f"Error saving {name}: {e}")

    return results


def sync_arcgis_server(
    source: CatalogSource,
    resources_dir: Path,
    verbose: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Sync an ArcGIS FeatureServer/MapServer and return sync results.

    Returns:
        dict with keys: added, updated, unchanged, errors, new_hash
    """
    from portolan_resource import (
        Origin,
        Resource,
        ResourceMetadata,
        SourceMetadata,
        Upstream,
        UserMetadata,
        save_resource,
    )

    results = {
        "added": [],
        "updated": [],
        "unchanged": [],
        "errors": [],
        "new_hash": None,
    }

    # Fetch the server metadata
    try:
        server_info = fetch_json(f"{source.url}?f=json")
    except Exception as e:
        results["errors"].append(f"Failed to fetch server info: {e}")
        return results

    # Get layers from the server
    layers = server_info.get("layers", [])
    if not layers:
        results["errors"].append("No layers found in server")
        return results

    # Compute hash of layers for change detection
    results["new_hash"] = compute_catalog_hash(layers)

    # Check if anything changed
    if source.sync_hash == results["new_hash"]:
        results["unchanged"] = [layer.get("name", f"layer_{layer.get('id')}") for layer in layers]
        return results

    if dry_run:
        results["added"] = [layer.get("name", f"layer_{layer.get('id')}") for layer in layers]
        return results

    # Create resources directory for this source
    namespace = f"federated_{source.name}"
    source_resources_dir = resources_dir / namespace
    source_resources_dir.mkdir(parents=True, exist_ok=True)

    # Determine server type
    server_type = "arcgis_featureserver"
    if "ImageServer" in source.url:
        server_type = "arcgis_imageserver"

    # Process each layer
    for layer in layers:
        layer_id = layer.get("id")
        layer_name = layer.get("name", f"layer_{layer_id}")
        layer_url = f"{source.url}/{layer_id}"

        # Fetch layer metadata
        layer_meta = {}
        try:
            layer_meta = fetch_json(f"{layer_url}?f=json")
        except Exception as e:
            if verbose:
                results["errors"].append(f"Error fetching layer {layer_id}: {e}")

        # Sanitize name
        name = layer_name.lower().replace(" ", "_").replace("-", "_")
        name = "".join(c for c in name if c.isalnum() or c == "_")
        if not name or not name[0].isalpha():
            name = f"layer_{name}"

        # Check if resource already exists
        resource_path = source_resources_dir / f"{name}.json"
        is_update = resource_path.exists()

        # Determine kind
        kind = "vector"
        geometry_type = layer_meta.get("geometryType", "")
        if server_type == "arcgis_imageserver":
            kind = "raster"

        # Create or update resource
        resource = Resource(
            name=name,
            kind=kind,
            origin=Origin(
                type=server_type,
                url=layer_url,
                layer=layer_name,
            ),
            metadata=ResourceMetadata(
                user=UserMetadata(
                    title=layer_name,
                    description=layer_meta.get("description", ""),
                ),
                source=SourceMetadata(
                    provider="arcgis",
                    ref={"server_url": source.url, "layer_id": layer_id},
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    data={
                        "name": layer_name,
                        "description": layer_meta.get("description", ""),
                        "geometryType": geometry_type,
                        "extent": layer_meta.get("extent"),
                        "fields": [
                            {"name": f.get("name"), "type": f.get("type")}
                            for f in layer_meta.get("fields", [])
                        ],
                    },
                ),
            ),
            upstream=Upstream(
                catalog=source.name,
                type="arcgis",
                id=str(layer_id),
            ),
            created_at=datetime.now(timezone.utc).isoformat() if not is_update else None,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

        try:
            save_resource(resource, resource_path)
            if is_update:
                results["updated"].append(name)
            else:
                results["added"].append(name)
        except Exception as e:
            results["errors"].append(f"Error saving {name}: {e}")

    return results
