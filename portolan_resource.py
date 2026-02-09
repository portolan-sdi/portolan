"""
Resource model for Portolan.

This module defines the resource lifecycle model.

States are detected by the presence of assets:
- origin only → REGISTERED (reference, discoverable but not SQL-queryable)
- origin + assets.iceberg or assets.snapshot → READY (queryable via Iceberg)

The data location (local vs remote) is orthogonal to the state:
- is_local: data is cached locally (assets.snapshot present)
- is_linked: Iceberg points to remote data (assets.iceberg without snapshot)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# =============================================================================
# Origin - Where the resource comes from
# =============================================================================


@dataclass
class Origin:
    """Describes where the resource originally comes from."""

    type: str  # file, wfs, arcgis_featureserver, arcgis_imageserver, stac, oracle, postgres
    url: str | None = None
    layer: str | None = None
    connection_ref: str | None = None  # Reference to stored connection config

    # For STAC imports
    stac_collection: str | None = None
    stac_item_id: str | None = None

    def to_dict(self) -> dict:
        result = {"type": self.type}
        if self.url:
            result["url"] = self.url
        if self.layer:
            result["layer"] = self.layer
        if self.connection_ref:
            result["connection_ref"] = self.connection_ref
        if self.stac_collection:
            result["stac_collection"] = self.stac_collection
        if self.stac_item_id:
            result["stac_item_id"] = self.stac_item_id
        return result

    @classmethod
    def from_dict(cls, data: dict) -> Origin:
        return cls(
            type=data.get("type", "file"),
            url=data.get("url"),
            layer=data.get("layer"),
            connection_ref=data.get("connection_ref"),
            stac_collection=data.get("stac_collection"),
            stac_item_id=data.get("stac_item_id"),
        )


# =============================================================================
# Assets - Data at different lifecycle stages
# =============================================================================


@dataclass
class SnapshotAsset:
    """A cached snapshot of the data in managed storage."""

    href: str  # e.g., "data/raw/ns/name/data.parquet"
    type: str  # MIME type
    taken_at: str  # ISO timestamp
    format: str  # geoparquet, cog, etc.
    source_fingerprint: dict | None = None  # For change detection (mtime, size, etag, etc.)

    def to_dict(self) -> dict:
        result = {
            "href": self.href,
            "type": self.type,
            "taken_at": self.taken_at,
            "format": self.format,
        }
        if self.source_fingerprint:
            result["source_fingerprint"] = self.source_fingerprint
        return result

    @classmethod
    def from_dict(cls, data: dict) -> SnapshotAsset:
        return cls(
            href=data["href"],
            type=data["type"],
            taken_at=data["taken_at"],
            format=data["format"],
            source_fingerprint=data.get("source_fingerprint"),
        )


@dataclass
class IcebergAsset:
    """Iceberg table metadata location."""

    metadata: str  # e.g., "data/ns/name/metadata/v1.metadata.json"

    def to_dict(self) -> dict:
        return {"metadata": self.metadata}

    @classmethod
    def from_dict(cls, data: dict) -> IcebergAsset:
        return cls(metadata=data["metadata"])


@dataclass
class Assets:
    """All assets associated with a resource."""

    snapshot: SnapshotAsset | None = None  # Present in CACHED state
    iceberg: IcebergAsset | None = None  # Present in MATERIALIZED state

    def to_dict(self) -> dict:
        result = {}
        if self.snapshot:
            result["snapshot"] = self.snapshot.to_dict()
        if self.iceberg:
            result["iceberg"] = self.iceberg.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict) -> Assets:
        snapshot = None
        iceberg = None

        if "snapshot" in data:
            snapshot = SnapshotAsset.from_dict(data["snapshot"])
        if "iceberg" in data:
            iceberg = IcebergAsset.from_dict(data["iceberg"])

        return cls(snapshot=snapshot, iceberg=iceberg)


# =============================================================================
# Metadata - Layered metadata structure
# =============================================================================


@dataclass
class UserMetadata:
    """User-provided metadata (authoritative overrides).

    Well-known fields (title, description, tags, license, attribution) are typed
    for convenience. The open `properties` dict stores everything else — ISO 19115
    fields, STAC extensions, OSI metadata, custom fields, etc.
    """

    title: str | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    license: str | None = None
    attribution: str | None = None
    properties: dict = field(default_factory=dict)

    WELL_KNOWN = {"title", "description", "tags", "license", "attribution"}

    def to_dict(self) -> dict:
        result = {}
        if self.title:
            result["title"] = self.title
        if self.description:
            result["description"] = self.description
        if self.tags:
            result["tags"] = self.tags
        if self.license:
            result["license"] = self.license
        if self.attribution:
            result["attribution"] = self.attribution
        if self.properties:
            result["properties"] = self.properties
        return result

    @classmethod
    def from_dict(cls, data: dict) -> UserMetadata:
        return cls(
            title=data.get("title"),
            description=data.get("description"),
            tags=data.get("tags", []),
            license=data.get("license"),
            attribution=data.get("attribution"),
            properties=data.get("properties", {}),
        )


@dataclass
class SourceMetadata:
    """Metadata fetched from external source."""

    provider: str  # stac, arcgis, wfs, etc.
    ref: dict = field(default_factory=dict)  # Provider-specific reference info
    fetched_at: str | None = None
    hash: str | None = None  # Hash of source metadata for change detection
    data: dict = field(default_factory=dict)  # Normalized metadata from source

    def to_dict(self) -> dict:
        result = {"provider": self.provider}
        if self.ref:
            result["ref"] = self.ref
        if self.fetched_at:
            result["fetched_at"] = self.fetched_at
        if self.hash:
            result["hash"] = self.hash
        if self.data:
            result["data"] = self.data
        return result

    @classmethod
    def from_dict(cls, data: dict) -> SourceMetadata:
        return cls(
            provider=data.get("provider", "unknown"),
            ref=data.get("ref", {}),
            fetched_at=data.get("fetched_at"),
            hash=data.get("hash"),
            data=data.get("data", {}),
        )


@dataclass
class DerivedMetadata:
    """Metadata computed from actual data."""

    schema_hash: str | None = None
    previous_schema_hash: str | None = None  # For drift detection
    schema_changed_at: str | None = None  # When schema drift was detected
    row_count: int | None = None
    bbox: list[float] | None = None  # [west, south, east, north]
    geometry_type: str | None = None
    crs: str | None = None
    files: dict = field(default_factory=dict)  # {"count": N, "bytes": M}

    def to_dict(self) -> dict:
        result = {}
        if self.schema_hash:
            result["schema_hash"] = self.schema_hash
        if self.previous_schema_hash:
            result["previous_schema_hash"] = self.previous_schema_hash
        if self.schema_changed_at:
            result["schema_changed_at"] = self.schema_changed_at
        if self.row_count is not None:
            result["row_count"] = self.row_count
        if self.bbox:
            result["bbox"] = self.bbox
        if self.geometry_type:
            result["geometry_type"] = self.geometry_type
        if self.crs:
            result["crs"] = self.crs
        if self.files:
            result["files"] = self.files
        return result

    @classmethod
    def from_dict(cls, data: dict) -> DerivedMetadata:
        return cls(
            schema_hash=data.get("schema_hash"),
            previous_schema_hash=data.get("previous_schema_hash"),
            schema_changed_at=data.get("schema_changed_at"),
            row_count=data.get("row_count"),
            bbox=data.get("bbox"),
            geometry_type=data.get("geometry_type"),
            crs=data.get("crs"),
            files=data.get("files", {}),
        )


@dataclass
class SyncConfig:
    """Configuration for metadata synchronization."""

    mode: str = "manual"  # manual, auto
    strategy: str = "update_source_only"  # update_source_only, update_missing_fields

    def to_dict(self) -> dict:
        return {"mode": self.mode, "strategy": self.strategy}

    @classmethod
    def from_dict(cls, data: dict) -> SyncConfig:
        return cls(
            mode=data.get("mode", "manual"),
            strategy=data.get("strategy", "update_source_only"),
        )


@dataclass
class ResourceMetadata:
    """Layered metadata structure."""

    user: UserMetadata = field(default_factory=UserMetadata)
    source: SourceMetadata | None = None
    derived: DerivedMetadata | None = None
    sync: SyncConfig = field(default_factory=SyncConfig)

    def to_dict(self) -> dict:
        result = {"user": self.user.to_dict()}
        if self.source:
            result["source"] = self.source.to_dict()
        if self.derived:
            result["derived"] = self.derived.to_dict()
        result["sync"] = self.sync.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict) -> ResourceMetadata:
        return cls(
            user=UserMetadata.from_dict(data.get("user", {})),
            source=SourceMetadata.from_dict(data["source"]) if "source" in data else None,
            derived=DerivedMetadata.from_dict(data["derived"]) if "derived" in data else None,
            sync=SyncConfig.from_dict(data.get("sync", {})),
        )

    def get_effective(self, key: str) -> Any:
        """Get a metadata value with precedence: user.properties > user well-known > source.data > None."""
        if key in self.user.properties:
            return self.user.properties[key]
        if key in UserMetadata.WELL_KNOWN:
            val = getattr(self.user, key, None)
            if val:
                return val
        if self.source and self.source.data.get(key):
            return self.source.data[key]
        return None

    def get_effective_title(self) -> str | None:
        """Get title with precedence: user > source > None."""
        return self.get_effective("title")

    def get_effective_description(self) -> str | None:
        """Get description with precedence: user > source > None."""
        return self.get_effective("description")


# =============================================================================
# Upstream - For federated catalogs
# =============================================================================


@dataclass
class Upstream:
    """For federated catalogs - reference to upstream catalog."""

    catalog: str  # Catalog identifier
    type: str  # stac, arcgis, wfs, portolan
    id: str  # Item/table ID in upstream

    def to_dict(self) -> dict:
        return {"catalog": self.catalog, "type": self.type, "id": self.id}

    @classmethod
    def from_dict(cls, data: dict) -> Upstream:
        return cls(
            catalog=data["catalog"],
            type=data["type"],
            id=data["id"],
        )


# =============================================================================
# Resource - The main resource model
# =============================================================================


@dataclass
class Resource:
    """
    The unified resource model with lifecycle states.

    States are indicated by presence of fields:
    - REGISTERED: origin present, no assets (discoverable, not queryable)
    - READY: has assets.iceberg or assets.snapshot (queryable)
    """

    name: str
    kind: str  # vector, raster, table, collection

    # Source information
    origin: Origin | None = None

    # Assets at different lifecycle stages
    assets: Assets = field(default_factory=Assets)

    # Layered metadata
    metadata: ResourceMetadata = field(default_factory=ResourceMetadata)

    # Federation support
    upstream: Upstream | None = None

    # Timestamps
    created_at: str | None = None
    updated_at: str | None = None

    @property
    def state(self) -> str:
        """Determine lifecycle state from assets."""
        if self.assets.iceberg or self.assets.snapshot:
            return "ready"
        if self.origin:
            return "registered"
        return "unknown"

    @property
    def is_local(self) -> bool:
        """Whether data is stored locally in the catalog."""
        return self.assets.snapshot is not None

    @property
    def is_linked(self) -> bool:
        """Whether Iceberg points to remote data (no local copy)."""
        return self.assets.iceberg is not None and self.assets.snapshot is None

    @property
    def title(self) -> str:
        """Get effective title."""
        return self.metadata.get_effective_title() or self.name

    @property
    def description(self) -> str | None:
        """Get effective description."""
        return self.metadata.get_effective_description()

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        result = {
            "name": self.name,
            "kind": self.kind,
        }
        if self.origin:
            result["origin"] = self.origin.to_dict()
        result["assets"] = self.assets.to_dict()
        result["metadata"] = self.metadata.to_dict()
        if self.upstream:
            result["upstream"] = self.upstream.to_dict()
        if self.created_at:
            result["created_at"] = self.created_at
        if self.updated_at:
            result["updated_at"] = self.updated_at
        return result

    @classmethod
    def from_dict(cls, data: dict) -> Resource:
        """Create from JSON dict."""
        return cls(
            name=data["name"],
            kind=data.get("kind", "vector"),
            origin=Origin.from_dict(data["origin"]) if "origin" in data else None,
            assets=Assets.from_dict(data.get("assets", {})),
            metadata=ResourceMetadata.from_dict(data.get("metadata", {})),
            upstream=Upstream.from_dict(data["upstream"]) if "upstream" in data else None,
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


# =============================================================================
# Helper functions
# =============================================================================


def load_resource(path: Path) -> Resource:
    """Load a resource from a JSON file."""
    import json

    with open(path) as f:
        data = json.load(f)
    return Resource.from_dict(data)


def save_resource(resource: Resource, path: Path) -> None:
    """Save a resource to a JSON file."""
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(resource.to_dict(), f, indent=2)


def compute_derived_metadata(parquet_path: Path) -> DerivedMetadata:
    """Compute derived metadata from a parquet file."""
    import hashlib

    import pyarrow.parquet as pq

    # Read parquet metadata
    pf = pq.ParquetFile(parquet_path)
    metadata = pf.metadata
    schema = pf.schema_arrow

    # Compute schema hash
    schema_str = str(schema)
    schema_hash = hashlib.sha256(schema_str.encode()).hexdigest()[:16]

    # Get row count
    row_count = metadata.num_rows

    # Get file size
    file_size = parquet_path.stat().st_size

    # Try to get bbox from GeoParquet metadata
    bbox = None
    geometry_type = None
    crs = None

    geo_meta = pf.schema_arrow.metadata
    if geo_meta and b"geo" in geo_meta:
        import json

        geo_info = json.loads(geo_meta[b"geo"])
        if "columns" in geo_info:
            for col_name, col_info in geo_info["columns"].items():
                if "bbox" in col_info:
                    bbox = col_info["bbox"]
                if "geometry_types" in col_info:
                    types = col_info["geometry_types"]
                    geometry_type = types[0] if len(types) == 1 else "mixed"
                if "crs" in col_info:
                    crs_info = col_info["crs"]
                    if isinstance(crs_info, dict):
                        crs = crs_info.get("id", {}).get("code")
                        if crs:
                            crs = f"EPSG:{crs}"

    return DerivedMetadata(
        schema_hash=schema_hash,
        row_count=row_count,
        bbox=bbox,
        geometry_type=geometry_type,
        crs=crs,
        files={"count": 1, "bytes": file_size},
    )
