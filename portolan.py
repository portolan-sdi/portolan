#!/usr/bin/env python3
"""
Portolan CLI - Manage geospatial data infrastructure with cloud-native formats.

Local-first workflow:
    portolan init [path] [--remote URL]     # Initialize a local catalog
    portolan dataset add <file> [options]   # Add dataset to local catalog
    portolan dataset list                   # List local datasets
    portolan status                         # Show catalog status
    portolan sync                           # Sync local catalog to remote storage
    portolan clone <url> [path]             # Clone a remote catalog
    portolan pull                           # Pull updates from remote
    portolan rebuild                        # Rebuild all output formats

Supported storage backends:
    - s3://bucket/path          (AWS S3 and S3-compatible: R2, MinIO, OVH, Wasabi, etc.)
    - gs://bucket/path          (Google Cloud Storage)
    - az://container/path       (Azure Blob Storage)
    - file:///local/path        (Local filesystem)
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import click

# ============== CONFIGURATION ==============


@dataclass
class RemoteConfig:
    """Configuration for a remote storage backend."""
    name: str
    url: str  # e.g., s3://bucket/path, gs://bucket/path, file:///path
    options: dict = field(default_factory=dict)  # Backend-specific options (credentials, region, etc.)

    def to_dict(self) -> dict:
        return {"name": self.name, "url": self.url, "options": self.options}

    @classmethod
    def from_dict(cls, data: dict) -> RemoteConfig:
        return cls(name=data["name"], url=data["url"], options=data.get("options", {}))


@dataclass
class OutputsConfig:
    """Configuration for catalog output targets.

    Outputs are split into two categories:
    - metadata: Discovery catalogs of ALL resources (including registered-only).
    - data: Queryable data tables. Only for READY resources with Parquet data.

    Each value can be True/False or a dict with "enabled" + format-specific config.
    """
    metadata: dict[str, bool | dict] = field(default_factory=lambda: {
        "stac": False,
        "iso19139": False,
        "web": False,
        "iceberg": True,
    })
    data: dict[str, bool | dict] = field(default_factory=lambda: {
        "iceberg": True,
        "ducklake": False,
    })

    def is_enabled(self, category: str, name: str) -> bool:
        """Check if an output is enabled."""
        section = self.metadata if category == "metadata" else self.data
        val = section.get(name, False)
        return val.get("enabled", False) if isinstance(val, dict) else bool(val)

    def to_dict(self) -> dict:
        return {"metadata": dict(self.metadata), "data": dict(self.data)}

    @classmethod
    def from_dict(cls, data: dict) -> OutputsConfig:
        defaults = cls()
        return cls(
            metadata={**defaults.metadata, **data.get("metadata", {})},
            data={**defaults.data, **data.get("data", {})},
        )



@dataclass
class CatalogConfig:
    """Configuration for a Portolan catalog."""
    path: Path
    default_remote: str | None = None
    remotes: dict[str, RemoteConfig] = field(default_factory=dict)
    outputs: OutputsConfig = field(default_factory=OutputsConfig)

    @property
    def config_file(self) -> Path:
        return self.path / "config.json"

    @property
    def data_dir(self) -> Path:
        return self.path / "data"

    @property
    def metadata_dir(self) -> Path:
        return self.path / "v1"

    @property
    def stac_dir(self) -> Path:
        return self.path / "stac"

    @property
    def iso_dir(self) -> Path:
        return self.path / "iso19139"

    def save(self):
        """Save catalog configuration."""
        self.path.mkdir(parents=True, exist_ok=True)
        data = {
            "default_remote": self.default_remote,
            "remotes": {name: r.to_dict() for name, r in self.remotes.items()},
            "outputs": self.outputs.to_dict(),
        }
        with open(self.config_file, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: Path) -> CatalogConfig:
        """Load catalog configuration from path."""
        config_file = path / "config.json"
        if config_file.exists():
            with open(config_file) as f:
                data = json.load(f)
            remotes = {
                name: RemoteConfig.from_dict(r)
                for name, r in data.get("remotes", {}).items()
            }
            outputs = OutputsConfig.from_dict(data.get("outputs", {}))
            return cls(
                path=path,
                default_remote=data.get("default_remote"),
                remotes=remotes,
                outputs=outputs,
            )
        return cls(path=path)


def find_catalog(start_path: Path | None = None) -> CatalogConfig | None:
    """Find the nearest Portolan catalog by walking up the directory tree."""
    if start_path is None:
        start_path = Path.cwd()

    current = start_path.resolve()
    while current != current.parent:
        catalog_dir = current / ".portolan"
        if catalog_dir.is_dir() and (catalog_dir / "config.json").exists():
            return CatalogConfig.load(catalog_dir)
        current = current.parent

    # Check if .portolan exists in cwd even without config
    default_dir = start_path / ".portolan"
    if default_dir.is_dir():
        return CatalogConfig.load(default_dir)

    return None


def get_catalog(ctx: click.Context) -> CatalogConfig:
    """Get the current catalog, raising an error if not found."""
    catalog = find_catalog()
    if catalog is None:
        raise click.ClickException(
            "No Portolan catalog found. Run 'portolan init' to create one."
        )
    return catalog


# ============== REMOTE PARQUET HELPERS ==============


def _parse_remote_url(url: str) -> tuple[str, str]:
    """
    Parse a remote URL into (scheme, path) for filesystem resolution.

    Supports:
    - s3://bucket/path
    - gs://bucket/path
    - az://container/path
    - https://host/path (including S3/GCS public URLs)

    Returns:
        Tuple of (scheme, path_for_filesystem)
    """
    if url.startswith("s3://"):
        return "s3", url[5:]
    if url.startswith("gs://"):
        return "gs", url[5:]
    if url.startswith("az://"):
        return "az", url[5:]
    if url.startswith("https://") or url.startswith("http://"):
        # Detect S3 public URLs: https://bucket.s3.amazonaws.com/path
        # or https://bucket.s3.region.amazonaws.com/path
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = parsed.hostname or ""

        if ".s3." in host and ".amazonaws.com" in host:
            # S3-style URL: extract bucket and key
            bucket = host.split(".s3.")[0]
            key = parsed.path.lstrip("/")
            return "s3", f"{bucket}/{key}"

        if "storage.googleapis.com" in host:
            # GCS-style URL
            key = parsed.path.lstrip("/")
            return "gs", key

        return "https", url
    return "file", url


def _get_obstore_fsspec(scheme: str, region: str | None = None):
    """Create an obstore FsspecStore for anonymous read access.

    Returns an fsspec-compatible filesystem backed by obstore.
    """
    import os

    from obstore.fsspec import FsspecStore

    if scheme == "s3":
        s3_region = region or os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
        return FsspecStore("s3", skip_signature=True, region=s3_region)
    if scheme == "gs":
        return FsspecStore("gcs", skip_signature=True)
    if scheme == "az":
        return FsspecStore("az", skip_signature=True)
    raise ValueError(f"Unsupported scheme for obstore filesystem: {scheme}")


def _open_remote_parquet(url: str, region: str | None = None):
    """
    Open a remote Parquet file and return a ParquetFile object.

    Only reads the metadata footer (range request), not the full file.
    Supports s3://, gs://, az://, and https:// URLs.
    """
    import pyarrow.parquet as pq

    scheme, path = _parse_remote_url(url)

    if scheme in ("s3", "gs", "az"):
        fs = _get_obstore_fsspec(scheme, region=region)
        return pq.ParquetFile(path, filesystem=fs)

    if scheme == "https":
        import fsspec
        f = fsspec.open(url, "rb").open()
        return pq.ParquetFile(f)

    # Local file fallback
    return pq.ParquetFile(path)


def _list_remote_files(glob_url: str, region: str | None = None, verbose: bool = False) -> list[dict]:
    """List remote files matching a glob pattern (e.g., s3://bucket/path/*).

    Returns list of dicts with {path, size, record_count} for each Parquet file.
    Only reads file metadata (HEAD requests), not file contents.
    """
    import os

    import obstore as obs
    import pyarrow.parquet as pq

    scheme, path = _parse_remote_url(glob_url)

    # Strip the glob suffix to get the directory prefix
    if path.endswith("/*"):
        prefix = path[:-2]
    elif "*" in path:
        prefix = path[:path.index("*")]
    else:
        prefix = path

    files = []
    scheme_prefix_map = {"s3": "s3://", "gs": "gs://", "az": "az://"}

    if scheme in ("s3", "gs", "az"):
        from obstore.store import AzureStore as ObAzure
        from obstore.store import GCSStore as ObGCS
        from obstore.store import S3Store as ObS3

        bucket, obj_prefix = prefix.split("/", 1) if "/" in prefix else (prefix, "")

        if scheme == "s3":
            s3_region = region or os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
            store = ObS3(bucket, skip_signature=True, region=s3_region)
        elif scheme == "gs":
            store = ObGCS(bucket, skip_signature=True)
        else:
            store = ObAzure(bucket, skip_signature=True)

        fs = _get_obstore_fsspec(scheme, region=region)

        for chunk in obs.list(store, prefix=obj_prefix):
            for meta in chunk:
                obj_path = meta["path"]
                if not obj_path.endswith(".parquet"):
                    continue
                full_path = f"{bucket}/{obj_path}"
                entry = {
                    "path": f"{scheme_prefix_map[scheme]}{full_path}",
                    "size": meta["size"],
                }
                try:
                    pf = pq.ParquetFile(full_path, filesystem=fs)
                    entry["record_count"] = pf.metadata.num_rows
                except Exception:
                    entry["record_count"] = 0
                files.append(entry)
                if verbose:
                    name = obj_path.split("/")[-1]
                    print(f"    {name}: {meta['size'] / 1024 / 1024:.0f} MB, "
                          f"{entry['record_count']:,} rows")

    return files


def _get_remote_file_size(url: str, region: str | None = None) -> int:
    """Get the file size of a remote file via HEAD request or filesystem info."""
    import os

    import obstore as obs

    scheme, path = _parse_remote_url(url)

    if scheme in ("s3", "gs", "az"):
        from obstore.store import AzureStore as ObAzure
        from obstore.store import GCSStore as ObGCS
        from obstore.store import S3Store as ObS3

        bucket, key = path.split("/", 1) if "/" in path else (path, "")

        if scheme == "s3":
            s3_region = region or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
            store = ObS3(bucket, skip_signature=True, region=s3_region)
        elif scheme == "gs":
            store = ObGCS(bucket, skip_signature=True)
        else:
            store = ObAzure(bucket, skip_signature=True)

        meta = obs.head(store, key)
        return meta["size"]

    if scheme == "https":
        import httpx
        response = httpx.head(url, follow_redirects=True, timeout=10)
        content_length = response.headers.get("content-length")
        return int(content_length) if content_length else 0

    # Local file
    return Path(path).stat().st_size


# ============== CHANGE DETECTION ==============


def _get_source_fingerprint(origin_type: str, url: str) -> dict | None:
    """Get a fingerprint of the source for change detection.

    Returns a dict with keys like mtime, size, etag — depends on source type.
    Returns None if the source type doesn't support cheap change detection.
    """
    if origin_type == "file":
        p = Path(url)
        if p.exists():
            stat = p.stat()
            return {
                "mtime": stat.st_mtime,
                "size": stat.st_size,
            }
        return None

    # Remote Parquet: check file size (cheap HEAD request)
    if url and url.startswith(("s3://", "gs://", "https://", "http://")):
        try:
            size = _get_remote_file_size(url)
            fingerprint = {"size": size}

            # For HTTPS, also try to get ETag or Last-Modified
            if url.startswith(("https://", "http://")):
                import httpx
                response = httpx.head(url, follow_redirects=True, timeout=10)
                etag = response.headers.get("etag")
                last_modified = response.headers.get("last-modified")
                if etag:
                    fingerprint["etag"] = etag
                if last_modified:
                    fingerprint["last_modified"] = last_modified

            return fingerprint
        except Exception:
            return None

    # API sources (WFS, ArcGIS, DB) — no cheap change detection
    return None


def _source_changed(old_fingerprint: dict | None, new_fingerprint: dict | None) -> bool:
    """Compare two source fingerprints. Returns True if changed or unknown."""
    if old_fingerprint is None or new_fingerprint is None:
        return True  # Can't tell — assume changed

    # Check ETag first (most reliable)
    if "etag" in old_fingerprint and "etag" in new_fingerprint:
        return old_fingerprint["etag"] != new_fingerprint["etag"]

    # Check mtime (for local files)
    if "mtime" in old_fingerprint and "mtime" in new_fingerprint:
        if old_fingerprint["mtime"] != new_fingerprint["mtime"]:
            return True
        if old_fingerprint.get("size") != new_fingerprint.get("size"):
            return True
        return False

    # Check last-modified (for HTTP)
    if "last_modified" in old_fingerprint and "last_modified" in new_fingerprint:
        return old_fingerprint["last_modified"] != new_fingerprint["last_modified"]

    # Fall back to size comparison
    if "size" in old_fingerprint and "size" in new_fingerprint:
        return old_fingerprint["size"] != new_fingerprint["size"]

    return True  # Can't compare — assume changed


# ============== NAMESPACE VALIDATION ==============


def _validate_namespace_or_raise(namespace: str):
    """Validate namespace and raise ClickException if invalid."""
    from namespace_utils import validate_namespace

    error = validate_namespace(namespace)
    if error:
        raise click.ClickException(f"Invalid namespace '{namespace}': {error}")


# ============== ICEBERG METADATA HELPER ==============


def _create_iceberg_metadata(resource, resource_name, catalog, namespace,
                              parquet_path=None, table=None,
                              data_file_url=None, data_files=None,
                              verbose=False):
    """Create Iceberg metadata for a resource.

    Either parquet_path (reads schema from local file) or table (pre-built
    IcebergTable) must be provided.  data_file_url overrides the URL stored
    in the manifest (e.g., for remote data that stays at source).
    data_files is a list of {path, size, record_count} for multi-file datasets.

    Returns the Path to the written v1.metadata.json.
    """
    import json
    import uuid

    from iceberg_catalog import (
        create_table_metadata,
        generate_manifest_files,
        parquet_to_iceberg_table,
    )
    from portolan_resource import IcebergAsset

    if verbose:
        click.echo("  Creating Iceberg metadata...")

    if table is None:
        if parquet_path is None:
            raise ValueError("Either parquet_path or table must be provided")
        table = parquet_to_iceberg_table(str(parquet_path), table_name=resource_name)

    from namespace_utils import namespace_to_iceberg

    iceberg_ns = namespace_to_iceberg(namespace)
    metadata_dir = catalog.path / "data" / iceberg_ns / resource_name / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)

    table_uuid = str(uuid.uuid4())
    data_base_url = f"file://{catalog.path.absolute()}"
    table_path = f"{iceberg_ns}/{resource_name}"
    file_url = data_file_url or (f"file://{Path(parquet_path).absolute()}" if parquet_path else None)

    generate_manifest_files(
        table=table,
        data_base_url=data_base_url,
        metadata_dir=metadata_dir,
        arrow_schema=table.arrow_schema,
        snapshot_id=1,
        sequence_number=1,
        table_path=table_path,
        data_file_path=file_url,
        data_files=data_files,
    )

    metadata = create_table_metadata(table, data_base_url, table_uuid, table_path=table_path)
    metadata_path = metadata_dir / "v1.metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    resource.assets.iceberg = IcebergAsset(
        metadata=str(metadata_path.relative_to(catalog.path)),
    )

    return metadata_path


# ============== RESOURCE LIFECYCLE HELPERS ==============


def _sanitize_name(name: str) -> str:
    """Sanitize a string for use as a resource name."""
    name = name.lower().replace(" ", "_").replace("-", "_")
    return "".join(c for c in name if c.isalnum() or c == "_")


def _derive_name(origin_type: str, source: str, layer: str | None = None) -> str:
    """Derive a resource name from the source URL/path."""
    if origin_type in ("file", "pointcloud") or origin_type == "geoparquet":
        name = Path(source).stem
    elif origin_type in ("postgres", "oracle"):
        name = layer or source
    else:
        from urllib.parse import urlparse
        parsed = urlparse(source)
        path_parts = [p for p in parsed.path.split("/") if p]
        name = path_parts[-1] if path_parts else f"resource_{hash(source) % 10000}"
    return _sanitize_name(name)


def _detect_source_type(source: str) -> str:
    """Auto-detect source type from the source string."""
    source_lower = source.lower()

    # Local file
    if Path(source).exists():
        ext = Path(source).suffix.lower()
        if ext in (".laz", ".las", ".copc"):
            return "pointcloud"
        if ext in (".pmtiles", ".mbtiles"):
            return "tiles"
        return "file"

    # Tile formats (PMTiles, MBTiles)
    if source_lower.endswith((".pmtiles", ".mbtiles")):
        return "tiles"

    # Remote GeoParquet / Parquet
    if source_lower.endswith((".parquet", ".geoparquet")):
        return "geoparquet"
    if source_lower.startswith(("s3://", "gs://")) and "parquet" not in source_lower:
        # Cloud path without parquet extension — could be anything, default to geoparquet
        return "geoparquet"

    # ArcGIS FeatureServer / ImageServer
    if "featureserver" in source_lower or "/rest/services/" in source_lower:
        if "imageserver" in source_lower:
            return "arcgis_imageserver"
        return "arcgis_featureserver"

    # WFS
    if "wfs" in source_lower and ("service=" in source_lower or "request=" in source_lower):
        return "wfs"

    # STAC
    if "stac" in source_lower or "/items/" in source_lower or "/collections/" in source_lower:
        return "stac"

    # Remote files
    if source_lower.startswith(("https://", "http://")):
        if source_lower.endswith((".parquet", ".geoparquet")):
            return "geoparquet"
        if source_lower.endswith((".tif", ".tiff")):
            return "stac"
        return "file"

    # Database table name pattern (schema.table or just table_name)
    if "." in source and not source.startswith(("http", "s3://", "gs://", "/")):
        return "postgres"

    return "file"


def _is_parquet_or_copc(url: str) -> bool:
    """Check if a URL points to a Parquet or COPC file."""
    lower = url.lower().rstrip("/")
    # Glob patterns
    if lower.endswith("/*"):
        return True
    return lower.endswith((".parquet", ".geoparquet", ".copc.laz"))


def _detect_default_action(origin_type: str, source_url: str, catalog_only: bool, cache_data: bool) -> str:
    """Determine the default action based on source type and flags.

    Returns one of: "download", "remote", "catalog_only"
    """
    if catalog_only:
        return "catalog_only"

    # Remote tiles are catalog-only by default (too large to download)
    # Local tiles go through tilequet-io extraction
    # 3D Tiles are always remote and go through tilequet-io conversion
    if origin_type == "tiles":
        is_remote = source_url.startswith(("s3://", "gs://", "http://", "https://")) if source_url else False
        if is_remote and not cache_data:
            return "catalog_only"

    is_remote = source_url.startswith(("s3://", "gs://", "http://", "https://")) if source_url else False
    is_cloud_native = is_remote and _is_parquet_or_copc(source_url)

    from extractors import EXTRACTORS
    has_extractor = origin_type in EXTRACTORS

    if is_cloud_native:
        return "download" if cache_data else "remote"

    if has_extractor:
        return "download"

    # No extractor available — catalog only
    return "catalog_only"


def _normalize_origin_type(origin_type: str) -> str:
    """Map unified type names to internal origin types."""
    if origin_type == "geoparquet":
        return "file"
    return origin_type


def _register_resource(catalog, origin_type, url, name, namespace,
                        layer=None, connection_ref=None, title=None,
                        description=None, verbose=False):
    """Create and save a resource in REGISTERED state.

    Returns (resource, resource_path).
    """
    from portolan_resource import (
        Origin,
        Resource,
        ResourceMetadata,
        UserMetadata,
        save_resource,
    )
    from schemas import validate_resource

    # Detect kind based on origin type (before normalization)
    kind = "vector"
    if origin_type == "arcgis_imageserver":
        kind = "raster"
    elif origin_type == "pointcloud":
        kind = "pointcloud"
    elif origin_type in ("tiles", "tiles3d"):
        kind = "tiles"

    # Normalize origin type for internal storage
    internal_type = _normalize_origin_type(origin_type)

    # For database types, layer is the table name, URL is optional
    if internal_type in ("postgres", "oracle"):
        table_name = url
        if not layer:
            layer = table_name
        url = None

    # Resolve path for local files
    if internal_type in ("file", "pointcloud", "tiles", "tiles3d") and url and not any(url.startswith(p) for p in ("s3://", "gs://", "https://", "http://")):
        resolved_url = str(Path(url).resolve())
    elif internal_type in ("postgres", "oracle"):
        resolved_url = None
    else:
        resolved_url = url

    origin = Origin(
        type=internal_type,
        url=resolved_url,
        layer=layer,
        connection_ref=connection_ref,
    )

    resource = Resource(
        name=name,
        kind=kind,
        origin=origin,
        metadata=ResourceMetadata(
            user=UserMetadata(title=title, description=description),
        ),
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    errors = validate_resource(resource.to_dict())
    if errors:
        click.echo(click.style("Validation errors:", fg="red"))
        for error in errors:
            click.echo(f"  - {error}")
        raise click.ClickException("Resource validation failed")

    resources_dir = catalog.path / "resources" / namespace
    resource_path = resources_dir / f"{name}.json"
    save_resource(resource, resource_path)

    return resource, resource_path


def _extract_to_parquet(resource, resource_name, catalog, namespace, bbox=None, verbose=False):
    """Run extractor, return output path and derived metadata.

    Returns (output_path, derived_metadata).
    """
    from extractors import run_extractor
    from portolan_resource import compute_derived_metadata

    snapshot_dir = catalog.path / "data" / "raw" / namespace / resource_name
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    output_path = snapshot_dir / f"{resource_name}.parquet"

    run_extractor(resource, output_path, catalog_path=catalog.path, bbox=bbox, verbose=verbose)

    if verbose:
        click.echo("  Computing derived metadata...")
    derived = compute_derived_metadata(output_path)

    return output_path, derived


def _create_remote_iceberg(resource, resource_name, catalog, namespace, verbose=False):
    """Create Iceberg metadata pointing to remote data (no download).

    Reads schema via range request only. Supports single files and glob patterns.
    Returns metadata_path.
    """
    import pyarrow.parquet as pq

    from iceberg_catalog import IcebergTable, _arrow_schema_to_iceberg
    from portolan_resource import DerivedMetadata

    remote_url = resource.origin.url

    # Check if URL is a glob pattern (multi-file dataset)
    is_glob = remote_url.rstrip("/").endswith("/*") or "*" in remote_url
    data_files_list = None

    if is_glob:
        click.echo("  Listing remote files...")
        remote_files = _list_remote_files(remote_url, verbose=verbose)

        if not remote_files:
            raise click.ClickException(f"No files found matching: {remote_url}")

        click.echo(f"  Found {len(remote_files)} files")

        first_file = remote_files[0]
        if verbose:
            click.echo(f"  Reading schema from {first_file['path'].split('/')[-1]}...")

        try:
            remote_pf = _open_remote_parquet(first_file["path"])
        except Exception as e:
            raise click.ClickException(f"Failed to read remote Parquet schema: {e}")

        arrow_schema = remote_pf.schema_arrow
        num_rows = sum(f.get("record_count", 0) for f in remote_files)
        file_size = sum(f.get("size", 0) for f in remote_files)
        data_files_list = remote_files
    else:
        if verbose:
            click.echo("  Reading Parquet schema from remote (range request only)...")

        try:
            remote_pf = _open_remote_parquet(remote_url)
        except Exception as e:
            raise click.ClickException(f"Failed to read remote Parquet schema: {e}")

        arrow_schema = remote_pf.schema_arrow
        num_rows = remote_pf.metadata.num_rows

        try:
            file_size = _get_remote_file_size(remote_url)
        except Exception:
            file_size = 0

    if verbose:
        click.echo(f"  Schema: {len(arrow_schema)} fields")
        click.echo(f"  Rows: {num_rows:,}" if num_rows else "  Rows: unknown")
        click.echo(f"  Size: {file_size / 1024 / 1024 / 1024:.1f} GB" if file_size > 1024**3 else f"  Size: {file_size / 1024 / 1024:.1f} MB")

    iceberg_schema = _arrow_schema_to_iceberg(arrow_schema)
    table = IcebergTable(
        name=resource_name,
        parquet_path=remote_url,
        schema=iceberg_schema,
        arrow_schema=arrow_schema,
        num_rows=num_rows,
        file_size_bytes=file_size,
    )

    metadata_path = _create_iceberg_metadata(
        resource, resource_name, catalog, namespace,
        table=table, data_file_url=remote_url if not is_glob else None,
        data_files=data_files_list,
        verbose=verbose,
    )

    # Store derived metadata
    n_files = len(data_files_list) if data_files_list else 1
    resource.metadata.derived = DerivedMetadata(
        row_count=num_rows,
        files={"count": n_files, "bytes": file_size},
    )

    return metadata_path


# ============== CLI ==============

@click.group()
@click.version_option(version="0.2.0")
@click.pass_context
def cli(ctx):
    """Portolan - Geospatial data infrastructure with cloud-native formats.

    Local-first workflow: add datasets locally, then sync to remote storage.

    \b
    Quick start:
        portolan init                    # Create a catalog
        portolan dataset add data.parquet --public
        portolan sync                    # Push to remote
    """
    ctx.ensure_object(dict)


# ============== INIT ==============

@cli.command()
@click.argument("path", type=click.Path(), default=".", required=False)
@click.option("--remote", "-r", help="Remote storage URL (e.g., gs://bucket/path)")
def init(path: str, remote: str | None):
    """Initialize a new Portolan catalog.

    Creates a .portolan directory in the specified PATH (default: current directory).

    \b
    Examples:
        portolan init                           # Initialize in current directory
        portolan init ./my-catalog              # Initialize in specific directory
        portolan init -r gs://my-bucket/data    # Initialize with remote
    """
    from catalog_state import LocalState

    catalog_path = Path(path).resolve() / ".portolan"

    if catalog_path.exists():
        click.echo(f"Catalog already exists at {catalog_path}")
        return

    # Create catalog structure
    catalog = CatalogConfig(path=catalog_path)
    catalog.path.mkdir(parents=True, exist_ok=True)
    catalog.data_dir.mkdir(exist_ok=True)
    catalog.metadata_dir.mkdir(exist_ok=True)

    # Create resources directory
    resources_dir = catalog.path / "resources"
    resources_dir.mkdir(exist_ok=True)

    # Initialize state.json for git-like workflow
    state = LocalState(remote_url=remote)
    state.save(catalog.path / "state.json")

    catalog.save()

    click.echo(f"Initialized Portolan catalog at {catalog_path}")
    if remote:
        click.echo(f"Remote: {remote}")

    click.echo()
    click.echo("Next steps:")
    click.echo("  portolan dataset add <file.parquet> --public")
    if not remote:
        click.echo("  # Edit .portolan/state.json to set remote_url")
    click.echo("  portolan sync")
    click.echo()
    click.echo("Configure outputs in .portolan/config.json:")
    click.echo("  metadata: stac, iso19139, web, iceberg")
    click.echo("  data: iceberg, ducklake")


# ============== CONNECTION MANAGEMENT ==============


def load_connection(catalog_path: Path, name: str | None) -> dict | None:
    """Load a connection configuration by name."""
    if not name:
        return None

    connections_file = catalog_path / "connections.json"
    if not connections_file.exists():
        return None

    with open(connections_file) as f:
        connections = json.load(f)

    return connections.get("connections", {}).get(name)


def save_connection(catalog_path: Path, name: str, config: dict) -> None:
    """Save a connection configuration."""
    connections_file = catalog_path / "connections.json"

    if connections_file.exists():
        with open(connections_file) as f:
            connections = json.load(f)
    else:
        connections = {"connections": {}}

    connections["connections"][name] = config

    with open(connections_file, "w") as f:
        json.dump(connections, f, indent=2)


def delete_connection(catalog_path: Path, name: str) -> bool:
    """Delete a connection configuration. Returns True if deleted."""
    connections_file = catalog_path / "connections.json"

    if not connections_file.exists():
        return False

    with open(connections_file) as f:
        connections = json.load(f)

    if name not in connections.get("connections", {}):
        return False

    del connections["connections"][name]

    with open(connections_file, "w") as f:
        json.dump(connections, f, indent=2)

    return True


# ============== RESOURCE LIFECYCLE COMMANDS ==============


@cli.command("add")
@click.argument("source")
@click.option("--type", "origin_type", help="Source type (auto-detected if omitted)")
@click.option("--name", "-n", help="Resource name (default: derived from source)")
@click.option("--namespace", "-ns", default="default", help="Namespace")
@click.option("--layer", "-l", help="Layer name (for multi-layer sources or database tables)")
@click.option("--connection-ref", help="Connection reference for database sources")
@click.option("--title", help="Human-readable title")
@click.option("--description", help="Description")
@click.option("--public", is_flag=True, help="Make public (sets namespace to 'public')")
@click.option("--catalog-only", is_flag=True, help="Just register for discovery, no processing")
@click.option("--cache-data", is_flag=True, help="Force local download for remote cloud-native formats (SLA/offline)")
@click.option("--bbox", help="Bounding box filter: xmin,ymin,xmax,ymax (WGS84)")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def add_resource(ctx, source: str, origin_type: str | None, name: str | None,
                 namespace: str, layer: str | None, connection_ref: str | None,
                 title: str | None, description: str | None, public: bool,
                 catalog_only: bool, cache_data: bool, bbox: str | None, verbose: bool):
    """Add a resource to the catalog.

    Smart defaults based on source type — does the right thing automatically.

    \b
    Local files:
        portolan add ./cities.shp
        portolan add /data/parcels.parquet --public

    Remote cloud-native (no download):
        portolan add s3://bucket/data.parquet
        portolan add s3://overturemaps/theme=buildings/*

    Remote APIs (download + convert):
        portolan add https://services.arcgis.com/.../FeatureServer/0
        portolan add https://example.com/wfs --type wfs --layer boundaries

    Databases:
        portolan add public.buildings --type postgres --connection-ref mydb

    Point clouds:
        portolan add scan.laz --type pointcloud --name lidar

    \b
    Control flags:
        --catalog-only    Just register for discovery, no processing
        --cache-data      Force local copy of remote cloud-native data (SLA/offline)
    """
    from portolan_resource import (
        SnapshotAsset,
        save_resource,
    )
    from schemas import validate_resource

    if public:
        namespace = "public"
    _validate_namespace_or_raise(namespace)
    catalog = get_catalog(ctx)

    # -- Step 1: Auto-detect source type --
    if origin_type is None:
        origin_type = _detect_source_type(source)
    if verbose:
        click.echo(f"  Detected type: {origin_type}")

    # -- Step 2: Derive name --
    if not name:
        name = _derive_name(origin_type, source, layer)
    else:
        name = _sanitize_name(name)

    # -- Step 3: Determine action --
    url = source
    action = _detect_default_action(origin_type, url, catalog_only, cache_data)

    if verbose:
        click.echo(f"  Action: {action}")

    # -- Step 4: Register resource --
    click.echo(f"Adding {origin_type} resource: {name}...")
    resource, resource_path = _register_resource(
        catalog, origin_type, url, name, namespace,
        layer=layer, connection_ref=connection_ref,
        title=title, description=description, verbose=verbose,
    )

    # -- Step 5: Execute action --
    if action == "catalog_only":
        if not catalog_only:
            # Auto-detected catalog_only (no extractor)
            click.echo(f"  No converter available for this format — registering for discovery only.")
        save_resource(resource, resource_path)
        click.echo(f"  State: {resource.state.upper()}")
        click.echo()
        click.echo(click.style("Resource registered for discovery.", fg="green"))
        return

    if action == "remote":
        if catalog.outputs.is_enabled("data", "iceberg"):
            click.echo(f"  Creating remote Iceberg (no download)...")
            metadata_path = _create_remote_iceberg(resource, name, catalog, namespace, verbose=verbose)
        resource.updated_at = datetime.now(timezone.utc).isoformat()

        errors = validate_resource(resource.to_dict())
        if errors:
            click.echo(click.style("Validation errors:", fg="red"))
            for error in errors:
                click.echo(f"  - {error}")
            raise click.ClickException("Resource validation failed")

        save_resource(resource, resource_path)

        n_files = resource.metadata.derived.files.get("count", 1) if resource.metadata.derived else 1
        click.echo(f"  State: {resource.state.upper()} (linked)")
        click.echo(f"  Files: {n_files}")
        click.echo(f"  Data: stays remote (not downloaded)")
        click.echo()
        click.echo("Query with DuckDB:")
        iceberg_meta = catalog.path / resource.assets.iceberg.metadata
        click.echo(f"  duckdb -c \"SELECT * FROM iceberg_scan('{iceberg_meta}')\"")
        click.echo()
        click.echo(click.style("Resource added successfully!", fg="green"))
        return

    if action == "download":
        # Download + convert + Iceberg
        output_path, derived = _extract_to_parquet(resource, name, catalog, namespace,
                                                     bbox=bbox, verbose=verbose)

        # Check for schema drift
        old_derived = resource.metadata.derived
        if old_derived and old_derived.schema_hash:
            if old_derived.schema_hash != derived.schema_hash:
                click.echo(click.style(f"  Schema drift detected", fg="yellow"))
                derived.previous_schema_hash = old_derived.schema_hash
                derived.schema_changed_at = datetime.now(timezone.utc).isoformat()

        # Capture source fingerprint for future change detection
        source_fp = _get_source_fingerprint(origin_type, url)

        # Determine snapshot format based on kind
        snapshot_format = {
            "raster": "raquet",
            "tiles": "tilequet",
            "pointcloud": "parquet",
        }.get(resource.kind, "geoparquet")

        # Update resource with snapshot
        resource.assets.snapshot = SnapshotAsset(
            href=str(output_path.relative_to(catalog.path)),
            type="application/vnd.apache.parquet",
            taken_at=datetime.now(timezone.utc).isoformat(),
            format=snapshot_format,
            source_fingerprint=source_fp,
        )
        resource.metadata.derived = derived
        resource.updated_at = datetime.now(timezone.utc).isoformat()

        # Auto-create Iceberg data table if enabled
        parquet_formats = {"geoparquet", "raquet", "parquet", "tilequet"}
        if catalog.outputs.is_enabled("data", "iceberg") and resource.assets.snapshot.format in parquet_formats:
            _create_iceberg_metadata(resource, name, catalog, namespace,
                                      parquet_path=output_path, verbose=verbose)

        errors = validate_resource(resource.to_dict())
        if errors:
            click.echo(click.style("Validation errors:", fg="red"))
            for error in errors:
                click.echo(f"  - {error}")
            raise click.ClickException("Resource validation failed")

        save_resource(resource, resource_path)

        click.echo(f"  Snapshot: {output_path}")
        click.echo(f"  State: {resource.state.upper()} (local)")
        click.echo(f"  Size: {output_path.stat().st_size / 1024:.1f} KB")
        if derived.row_count:
            click.echo(f"  Rows: {derived.row_count}")

        if resource.assets.iceberg:
            click.echo()
            click.echo("Query with DuckDB:")
            iceberg_meta = catalog.path / resource.assets.iceberg.metadata
            click.echo(f"  duckdb -c \"SELECT * FROM iceberg_scan('{iceberg_meta}')\"")

        click.echo()
        click.echo(click.style("Resource added successfully!", fg="green"))


@cli.command("refresh")
@click.argument("resource_name", required=False)
@click.option("--namespace", "-ns", default="default", help="Namespace")
@click.option("--all", "all_resources", is_flag=True, help="Refresh all resources in namespace")
@click.option("--force", is_flag=True, help="Force refresh even if already up to date")
@click.option("--bbox", help="Bounding box filter: xmin,ymin,xmax,ymax (WGS84)")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def refresh_resource(ctx, resource_name: str | None, namespace: str, all_resources: bool, force: bool, bbox: str | None, verbose: bool):
    """Re-fetch and update resources from their origins.

    Downloads fresh data from the original source, detects schema drift,
    and re-creates Iceberg metadata. For catalog-only resources, re-reads
    source metadata.

    \b
    Examples:
        portolan refresh cities
        portolan refresh --all
        portolan refresh --all --namespace imagery
    """
    from portolan_resource import load_resource, save_resource
    from schemas import validate_resource

    catalog = get_catalog(ctx)
    _validate_namespace_or_raise(namespace)

    # Handle --all flag
    if all_resources:
        namespace_dir = catalog.path / "resources" / namespace
        if not namespace_dir.exists():
            raise click.ClickException(f"Namespace not found: {namespace}")

        # Find resources with origins
        resource_files = list(namespace_dir.glob("*.json"))
        if not resource_files:
            click.echo(f"No resources found in namespace: {namespace}")
            return

        updatable = []
        for rf in resource_files:
            if rf.name.startswith("_"):
                continue
            res = load_resource(rf)
            if res.origin:
                updatable.append(rf.stem)

        if not updatable:
            click.echo(f"No updatable resources in namespace: {namespace}")
            return

        click.echo(f"Refreshing {len(updatable)} resources in {namespace}...")
        click.echo()

        succeeded = 0
        failed = 0
        for res_name in updatable:
            try:
                ctx.invoke(refresh_resource, resource_name=res_name,
                           namespace=namespace, all_resources=False,
                           force=force, bbox=bbox, verbose=verbose)
                succeeded += 1
            except click.ClickException as e:
                click.echo(click.style(f"  Failed: {res_name} - {e.message}", fg="red"))
                failed += 1
            click.echo()

        click.echo(f"Refresh complete: {succeeded} succeeded, {failed} failed")
        return

    # Single resource mode
    if not resource_name:
        raise click.ClickException("Resource name required (or use --all)")

    resource_path = catalog.path / "resources" / namespace / f"{resource_name}.json"
    if not resource_path.exists():
        raise click.ClickException(f"Resource not found: {resource_name} in namespace {namespace}")

    resource = load_resource(resource_path)

    if not resource.origin:
        raise click.ClickException(f"Resource '{resource_name}' has no origin — nothing to refresh from.")

    click.echo(f"Refreshing {resource_name} from {resource.origin.type}...")

    # Determine action based on current resource state
    url = resource.origin.url or ""
    action = _detect_default_action(resource.origin.type, url, False, False)

    if action == "remote":
        # Change detection for remote resources
        if not force and resource.assets.snapshot and resource.assets.snapshot.source_fingerprint:
            new_fp = _get_source_fingerprint(resource.origin.type, url)
            if new_fp and not _source_changed(resource.assets.snapshot.source_fingerprint, new_fp):
                click.echo(click.style(f"  {resource_name}: source unchanged, skipping (use --force to override)", dim=True))
                return

        # Re-read remote schema and update Iceberg (if data.iceberg enabled)
        if catalog.outputs.is_enabled("data", "iceberg"):
            _create_remote_iceberg(resource, resource_name, catalog, namespace, verbose=verbose)

        # Store fingerprint for future change detection
        new_fp = _get_source_fingerprint(resource.origin.type, url)
        if resource.assets.snapshot:
            resource.assets.snapshot.source_fingerprint = new_fp

        resource.updated_at = datetime.now(timezone.utc).isoformat()
        save_resource(resource, resource_path)
        click.echo(click.style(f"Refreshed {resource_name} (remote Iceberg updated)", fg="green"))
    elif action == "download":
        # Change detection: check if source has changed before re-extracting
        if not force:
            old_fp = resource.assets.snapshot.source_fingerprint if resource.assets.snapshot else None
            new_fp = _get_source_fingerprint(resource.origin.type, url)
            if old_fp and new_fp and not _source_changed(old_fp, new_fp):
                click.echo(click.style(f"  {resource_name}: source unchanged, skipping (use --force to override)", dim=True))
                return
            if new_fp is None and old_fp is None and resource.state == "ready":
                # API sources — no cheap check, always refresh but inform user
                if verbose:
                    click.echo(f"  No change detection available for {resource.origin.type}, re-extracting...")

        # Re-extract from origin
        from portolan_resource import SnapshotAsset
        output_path, derived = _extract_to_parquet(resource, resource_name, catalog, namespace,
                                                     bbox=bbox, verbose=verbose)

        # Schema drift detection
        old_derived = resource.metadata.derived
        if old_derived and old_derived.schema_hash and old_derived.schema_hash != derived.schema_hash:
            click.echo(click.style(f"  Schema drift detected", fg="yellow"))
            derived.previous_schema_hash = old_derived.schema_hash
            derived.schema_changed_at = datetime.now(timezone.utc).isoformat()

        # Store fingerprint for future change detection
        new_fp = _get_source_fingerprint(resource.origin.type, url)

        snapshot_format = {
            "raster": "raquet",
            "tiles": "tilequet",
            "pointcloud": "parquet",
        }.get(resource.kind, "geoparquet")

        resource.assets.snapshot = SnapshotAsset(
            href=str(output_path.relative_to(catalog.path)),
            type="application/vnd.apache.parquet",
            taken_at=datetime.now(timezone.utc).isoformat(),
            format=snapshot_format,
            source_fingerprint=new_fp,
        )
        resource.metadata.derived = derived
        resource.updated_at = datetime.now(timezone.utc).isoformat()

        parquet_formats = {"geoparquet", "raquet", "parquet", "tilequet"}
        if catalog.outputs.is_enabled("data", "iceberg") and resource.assets.snapshot.format in parquet_formats:
            _create_iceberg_metadata(resource, resource_name, catalog, namespace,
                                      parquet_path=output_path, verbose=verbose)

        save_resource(resource, resource_path)
        click.echo(click.style(f"Refreshed {resource_name}", fg="green"))
    else:
        click.echo(f"  Resource is catalog-only, nothing to refresh.")


# ============== DATASET ==============

@cli.group()
def dataset():
    """Manage datasets in the catalog."""
    pass


@dataset.command("add")
@click.argument("file", type=click.Path(exists=True))
@click.option("--id", "dataset_id", help="Dataset ID (default: filename)")
@click.option("--title", help="Dataset title")
@click.option("--description", help="Dataset description")
@click.option("--collection", "-c", default="datasets", help="Collection name")
@click.option("--public", "is_public", is_flag=True, help="Make dataset publicly accessible")
@click.option("--tenant", "-t", default="default", help="Tenant (for private datasets)")
@click.option("--topic", default="imageryBaseMapsEarthCover", help="ISO topic category")
@click.option("--license", "license_", default="CC-BY-4.0", help="License")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def dataset_add(ctx, file: str, dataset_id: str | None, title: str | None,
                description: str | None, collection: str, is_public: bool,
                tenant: str, topic: str, license_: str, verbose: bool):
    """Add a dataset to the local catalog.

    Supports GeoParquet (vector) and Raquet (raster) files.
    The dataset is added locally - use 'portolan sync' to push to remote.

    This command delegates to the new resource lifecycle (register + snapshot + materialize).

    \b
    Examples:
        portolan dataset add countries.parquet --public --title "World Countries"
        portolan dataset add imagery.parquet -c imagery --tenant acme
    """
    file_path = Path(file).resolve()

    # Determine dataset ID
    if dataset_id is None:
        dataset_id = file_path.stem

    # Sanitize dataset ID
    dataset_id = dataset_id.lower().replace(" ", "_").replace("-", "_")
    dataset_id = "".join(c for c in dataset_id if c.isalnum() or c == "_")

    # Determine namespace from public/collection
    namespace = "public" if is_public else collection

    # Delegate to the unified `add` command (register + snapshot + materialize)
    ctx.invoke(
        add_resource,
        source=file,
        name=dataset_id,
        namespace=namespace,
        title=title,
        description=description,
        public=is_public,
        verbose=verbose,
    )


@dataset.command("list")
@click.option("--namespace", "-ns", default=None, help="Filter by namespace")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed information")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def dataset_list(ctx, namespace: str | None, verbose: bool, as_json: bool):
    """List all resources with their state and sync status."""
    from portolan_resource import load_resource

    catalog = get_catalog(ctx)
    resources_dir = catalog.path / "resources"

    if not resources_dir.exists():
        click.echo("No resources found. Add one with:")
        click.echo("  portolan add <file.parquet> --public")
        return

    # Collect all resources grouped by namespace
    namespaces: dict[str, list] = {}
    target_namespaces = [namespace] if namespace else sorted(
        d.name for d in resources_dir.iterdir() if d.is_dir()
    )

    for ns in target_namespaces:
        ns_dir = resources_dir / ns
        if not ns_dir.exists():
            if namespace:
                raise click.ClickException(f"Namespace not found: {namespace}")
            continue

        resources = []
        for rf in sorted(ns_dir.glob("*.json")):
            if rf.name.startswith("_"):
                continue
            res = load_resource(rf)
            resources.append(res)

        if resources:
            namespaces[ns] = resources

    if not namespaces:
        click.echo("No resources found. Add one with:")
        click.echo("  portolan add <file.parquet> --public")
        return

    # Try to get last sync events from control plane
    last_events: dict[str, dict] = {}
    controller = _get_controller(catalog)
    if controller:
        try:
            for ns, resources in namespaces.items():
                for res in resources:
                    event = controller.store.get_last_event("snapshot", f"{ns}/{res.name}")
                    if event:
                        last_events[f"{ns}/{res.name}"] = event
        except Exception:
            pass  # Control plane is optional
        finally:
            controller.close()

    # JSON output
    if as_json:
        import json as json_mod
        output = []
        for ns, resources in namespaces.items():
            for res in resources:
                key = f"{ns}/{res.name}"
                entry = {
                    "namespace": ns,
                    "name": res.name,
                    "kind": res.kind,
                    "state": res.state,
                    "origin_type": res.origin.type if res.origin else None,
                    "updated_at": res.updated_at,
                }
                if key in last_events:
                    evt = last_events[key]
                    entry["last_sync"] = {
                        "status": evt.get("status"),
                        "at": str(evt.get("started_at", "")),
                    }
                output.append(entry)
        click.echo(json_mod.dumps(output, indent=2, default=str))
        return

    # State indicators
    state_icons = {
        "ready":      click.style("●", fg="green"),
        "registered": click.style("○", fg="white"),
        "unknown":    click.style("?", fg="red"),
    }

    def _state_label(res):
        if res.state == "ready":
            loc = "local" if res.is_local else "linked"
            return click.style(f"ready ({loc})", fg="green")
        if res.state == "registered":
            return click.style("registered", dim=True)
        return click.style("unknown", fg="red")

    total = sum(len(r) for r in namespaces.values())
    click.echo(click.style(f"Resources ({total})", bold=True))
    click.echo()

    # Build tree from namespace names and render recursively
    from namespace_utils import build_namespace_tree

    tree = build_namespace_tree(list(namespaces.keys()))

    def _render_resource(res, ns, depth):
        key = f"{ns}/{res.name}"
        icon = state_icons.get(res.state, "?")
        state_label = _state_label(res)
        indent = "  " * (depth + 1)

        line = f"{indent}{icon} {res.name}"
        line += f"  {click.style(f'[{res.kind}]', dim=True)}"
        line += f"  {state_label}"

        event = last_events.get(key)
        if event:
            sync_status = event.get("status", "")
            started = event.get("started_at", "")
            if hasattr(started, "strftime"):
                time_str = started.strftime("%Y-%m-%d %H:%M")
            else:
                time_str = str(started)[:16]

            if sync_status == "completed":
                sync_icon = click.style("✓", fg="green")
            elif sync_status == "failed":
                sync_icon = click.style("✗", fg="red")
            else:
                sync_icon = click.style("…", fg="yellow")

            line += f"  {sync_icon} {time_str}"

        click.echo(line)

        if verbose:
            v_indent = indent + "  "
            if res.origin:
                origin_str = res.origin.type
                if res.origin.url:
                    url = res.origin.url
                    if len(url) > 60:
                        url = url[:57] + "..."
                    origin_str += f" ({url})"
                click.echo(click.style(f"{v_indent}origin: {origin_str}", dim=True))

            if res.assets.snapshot:
                snap = res.assets.snapshot
                click.echo(click.style(f"{v_indent}snapshot: {snap.format}  taken {snap.taken_at[:10]}", dim=True))

            if res.updated_at:
                click.echo(click.style(f"{v_indent}updated: {res.updated_at[:10]}", dim=True))

            if event and event.get("status") == "failed" and event.get("error_message"):
                click.echo(click.style(f"{v_indent}error: {event['error_message'][:80]}", fg="red"))

    def _render_tree(node, depth, accumulated_ns):
        for name, children in sorted(node.items()):
            current_ns = f"{accumulated_ns}.{name}" if accumulated_ns else name
            indent = "  " * (depth + 1)
            click.echo(click.style(f"{indent}{name}/", bold=True))

            # Render resources at this namespace level
            if current_ns in namespaces:
                for res in namespaces[current_ns]:
                    _render_resource(res, current_ns, depth + 1)

            # Recurse into children
            if children:
                _render_tree(children, depth + 1, current_ns)

    _render_tree(tree, 0, "")
    click.echo()


@dataset.command("remove")
@click.argument("dataset_path")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation")
@click.pass_context
def dataset_remove(ctx, dataset_path: str, force: bool):
    """Remove a dataset from the local catalog.

    DATASET_PATH should be in the format: visibility/collection/dataset
    (e.g., public/datasets/countries or private/acme/imagery/satellite)
    """
    catalog = get_catalog(ctx)

    # Parse the dataset path
    parts = dataset_path.split("/")
    if len(parts) < 3:
        raise click.ClickException(
            "Invalid path. Use format: visibility/collection/dataset\n"
            "Example: public/datasets/countries"
        )

    target_dir = catalog.path / dataset_path

    if not target_dir.exists():
        raise click.ClickException(f"Dataset not found: {dataset_path}")

    if not force:
        click.confirm(f"Remove dataset '{dataset_path}'?", abort=True)

    shutil.rmtree(target_dir)
    click.echo(f"Removed dataset: {dataset_path}")


# ============== METADATA ==============


@cli.group()
def metadata():
    """View and manage resource metadata."""
    pass


@metadata.command("show")
@click.argument("name")
@click.option("--namespace", "-ns", default="default", help="Resource namespace")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def metadata_show(ctx, name: str, namespace: str, as_json: bool):
    """Show all metadata for a resource.

    Displays user metadata, source metadata (if fetched from an external catalog),
    and derived metadata (computed from the data).

    \b
    Examples:
        portolan metadata show cities
        portolan metadata show cities --json
        portolan metadata show sentinel --namespace imagery
    """
    from portolan_resource import load_resource

    catalog = get_catalog(ctx)
    resource_path = catalog.path / "resources" / namespace / f"{name}.json"

    if not resource_path.exists():
        raise click.ClickException(f"Resource not found: {namespace}/{name}")

    resource = load_resource(resource_path)

    if as_json:
        click.echo(json.dumps(resource.metadata.to_dict(), indent=2))
        return

    click.echo(click.style(f"Metadata for {namespace}/{name}", bold=True))
    click.echo()

    # User metadata
    click.echo(click.style("User metadata:", bold=True))
    user = resource.metadata.user
    has_user = False
    for field_name in ("title", "description", "license", "attribution"):
        val = getattr(user, field_name)
        if val:
            click.echo(f"  {field_name}: {val}")
            has_user = True
    if user.tags:
        click.echo(f"  tags: {', '.join(user.tags)}")
        has_user = True
    for k, v in sorted(user.properties.items()):
        val_str = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
        click.echo(f"  {k}: {val_str}")
        has_user = True
    if not has_user:
        click.echo(click.style("  (none)", dim=True))

    # Source metadata
    if resource.metadata.source:
        click.echo()
        click.echo(click.style("Source metadata:", bold=True))
        src = resource.metadata.source
        click.echo(f"  provider: {src.provider}")
        if src.fetched_at:
            click.echo(f"  fetched_at: {src.fetched_at}")
        for k, v in sorted(src.data.items()):
            val_str = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
            if len(val_str) > 120:
                val_str = val_str[:117] + "..."
            click.echo(f"  {k}: {val_str}")

    # Derived metadata
    if resource.metadata.derived:
        click.echo()
        click.echo(click.style("Derived metadata:", bold=True))
        d = resource.metadata.derived
        if d.row_count is not None:
            click.echo(f"  row_count: {d.row_count:,}")
        if d.bbox:
            click.echo(f"  bbox: {d.bbox}")
        if d.geometry_type:
            click.echo(f"  geometry_type: {d.geometry_type}")
        if d.crs:
            click.echo(f"  crs: {d.crs}")
        if d.columns:
            click.echo(f"  columns ({len(d.columns)}):")
            for col in d.columns:
                ctype = col["type"]
                if col.get("geometry_type"):
                    ctype = f'{ctype} ({col["geometry_type"]})'
                if col.get("crs"):
                    ctype += f' [{col["crs"]}]'
                null_str = ", nullable" if col.get("nullable") else ""
                click.echo(f"    {col['name']}: {ctype}{null_str}")
        if d.schema_hash:
            click.echo(f"  schema_hash: {d.schema_hash}")
        if d.files:
            click.echo(f"  files: {d.files}")


@metadata.command("set")
@click.argument("name")
@click.argument("key", required=False)
@click.argument("value", required=False)
@click.option("--namespace", "-ns", default="default", help="Resource namespace")
@click.option("--json", "json_str", help="Bulk set via JSON string")
@click.pass_context
def metadata_set(ctx, name: str, key: str | None, value: str | None,
                 namespace: str, json_str: str | None):
    """Set metadata on a resource.

    Well-known fields (title, description, tags, license, attribution) are stored
    as typed fields. Everything else goes into the open properties bag.

    \b
    Single property:
        portolan metadata set cities license "CC-BY-4.0"
        portolan metadata set cities contact_organization "National Survey"
        portolan metadata set cities tags '["admin", "boundaries"]'

    \b
    Bulk set via JSON:
        portolan metadata set cities --json '{"license": "CC-BY-4.0", "topic_category": "boundaries"}'
    """
    from portolan_resource import UserMetadata, load_resource, save_resource

    catalog = get_catalog(ctx)
    resource_path = catalog.path / "resources" / namespace / f"{name}.json"

    if not resource_path.exists():
        raise click.ClickException(f"Resource not found: {namespace}/{name}")

    resource = load_resource(resource_path)

    updates = {}
    if json_str:
        try:
            updates = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise click.ClickException(f"Invalid JSON: {e}")
    elif key and value is not None:
        try:
            updates[key] = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            updates[key] = value
    else:
        raise click.ClickException("Provide KEY VALUE or --json '{...}'")

    for k, v in updates.items():
        if k in UserMetadata.WELL_KNOWN:
            setattr(resource.metadata.user, k, v)
        else:
            resource.metadata.user.properties[k] = v

    resource.updated_at = datetime.now(timezone.utc).isoformat()
    save_resource(resource, resource_path)

    click.echo(f"Updated {len(updates)} field(s) on {namespace}/{name}")


@metadata.command("unset")
@click.argument("name")
@click.argument("key")
@click.option("--namespace", "-ns", default="default", help="Resource namespace")
@click.pass_context
def metadata_unset(ctx, name: str, key: str, namespace: str):
    """Remove a metadata property from a resource.

    \b
    Examples:
        portolan metadata unset cities license
        portolan metadata unset cities contact_email
    """
    from portolan_resource import UserMetadata, load_resource, save_resource

    catalog = get_catalog(ctx)
    resource_path = catalog.path / "resources" / namespace / f"{name}.json"

    if not resource_path.exists():
        raise click.ClickException(f"Resource not found: {namespace}/{name}")

    resource = load_resource(resource_path)

    if key in UserMetadata.WELL_KNOWN:
        if key == "tags":
            resource.metadata.user.tags = []
        else:
            setattr(resource.metadata.user, key, None)
    elif key in resource.metadata.user.properties:
        del resource.metadata.user.properties[key]
    else:
        raise click.ClickException(f"Property '{key}' not found on {namespace}/{name}")

    resource.updated_at = datetime.now(timezone.utc).isoformat()
    save_resource(resource, resource_path)
    click.echo(f"Removed '{key}' from {namespace}/{name}")


# ============== CONNECTION MANAGEMENT CLI ==============


@cli.group()
def connection():
    """Manage database connections for extractors."""
    pass


@connection.command("add")
@click.argument("name")
@click.argument("connection_string")
@click.option("--geometry-column", "-g", default="geom", help="Geometry column name")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def connection_add(ctx, name: str, connection_string: str, geometry_column: str, verbose: bool):
    """Add a database connection.

    Stores connection configuration for use with postgres/oracle extractors.
    Connection strings are stored locally in .portolan/connections.json.

    \b
    Examples:
        portolan connection add mydb "postgresql://user:pass@host:5432/dbname"
        portolan connection add oracle_prod "oracle://user:pass@host:1521/service" -g GEOMETRY
    """
    catalog = get_catalog(ctx)

    config = {
        "connection_string": connection_string,
        "geometry_column": geometry_column,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    save_connection(catalog.path, name, config)

    click.echo(f"Added connection: {name}")
    if verbose:
        click.echo(f"  Geometry column: {geometry_column}")


@connection.command("list")
@click.option("--verbose", "-v", is_flag=True, help="Show connection details")
@click.pass_context
def connection_list(ctx, verbose: bool):
    """List configured database connections."""
    catalog = get_catalog(ctx)

    connections_file = catalog.path / "connections.json"
    if not connections_file.exists():
        click.echo("No connections configured.")
        click.echo("Add one with: portolan connection add <name> <connection_string>")
        return

    with open(connections_file) as f:
        connections = json.load(f)

    conns = connections.get("connections", {})
    if not conns:
        click.echo("No connections configured.")
        return

    click.echo(f"Configured connections ({len(conns)}):")
    for name, config in conns.items():
        if verbose:
            # Mask password in connection string
            conn_str = config.get("connection_string", "")
            masked = conn_str
            if "://" in conn_str:
                # Basic password masking
                import re
                masked = re.sub(r":([^:@]+)@", r":****@", conn_str)
            click.echo(f"  {name}:")
            click.echo(f"    Connection: {masked}")
            click.echo(f"    Geometry column: {config.get('geometry_column', 'geom')}")
        else:
            click.echo(f"  {name}")


@connection.command("remove")
@click.argument("name")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation")
@click.pass_context
def connection_remove(ctx, name: str, force: bool):
    """Remove a database connection."""
    catalog = get_catalog(ctx)

    if not force:
        click.confirm(f"Remove connection '{name}'?", abort=True)

    if delete_connection(catalog.path, name):
        click.echo(f"Removed connection: {name}")
    else:
        raise click.ClickException(f"Connection not found: {name}")


# ============== CONTROL PLANE ==============


def _get_controller(catalog):
    """Get a SyncController for the given catalog, or None if DuckDB unavailable."""
    try:
        from sync_controller import SyncController
        return SyncController(catalog.path)
    except ImportError:
        return None


@cli.group("control")
def control_cmd():
    """Sync control plane — history, health, and export."""
    pass


@control_cmd.command("history")
@click.option("--type", "sync_type", help="Filter by type: remote_push, remote_pull, catalog_sync, snapshot")
@click.option("--target", help="Filter by target name or URL")
@click.option("--limit", "-n", default=20, help="Number of events to show")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def control_history(ctx, sync_type: str | None, target: str | None, limit: int, as_json: bool):
    """Show sync event history.

    \b
    Examples:
        portolan control history
        portolan control history --type catalog_sync
        portolan control history --target earth-search --limit 5
        portolan control history --json
    """
    catalog = get_catalog(ctx)
    controller = _get_controller(catalog)
    if controller is None:
        raise click.ClickException("sync_controller not available (is duckdb installed?)")

    try:
        events = controller.history(sync_type=sync_type, target=target, limit=limit)
    finally:
        controller.close()

    if not events:
        click.echo("No sync events recorded yet.")
        return

    if as_json:
        click.echo(json.dumps(events, indent=2, default=str))
        return

    click.echo(click.style("Sync History", bold=True))
    click.echo("=" * 80)

    for event in events:
        status = event["status"]
        if status == "completed":
            status_str = click.style("OK", fg="green")
        elif status == "failed":
            status_str = click.style("FAIL", fg="red")
        else:
            status_str = click.style(status.upper(), fg="yellow")

        started = event["started_at"]
        if hasattr(started, "strftime"):
            started = started.strftime("%Y-%m-%d %H:%M:%S")

        duration = event.get("duration_ms")
        duration_str = f" ({duration}ms)" if duration else ""

        changes_parts = []
        if event.get("changes_added"):
            changes_parts.append(f"+{event['changes_added']}")
        if event.get("changes_modified"):
            changes_parts.append(f"~{event['changes_modified']}")
        if event.get("changes_deleted"):
            changes_parts.append(f"-{event['changes_deleted']}")
        changes_str = f" [{', '.join(changes_parts)}]" if changes_parts else ""

        click.echo(f"  {started}  {status_str}  {event['type']:15s}  {event['target']}{duration_str}{changes_str}")

        if event.get("error_message") and status == "failed":
            click.echo(click.style(f"    Error: {event['error_message'][:120]}", fg="red"))


@control_cmd.command("health")
@click.option("--hours", default=24, help="Look back period in hours")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.pass_context
def control_health(ctx, hours: int, as_json: bool):
    """Show sync health summary.

    \b
    Examples:
        portolan control health
        portolan control health --hours 72
        portolan control health --json
    """
    catalog = get_catalog(ctx)
    controller = _get_controller(catalog)
    if controller is None:
        raise click.ClickException("sync_controller not available (is duckdb installed?)")

    try:
        summary = controller.health(hours=hours)
    finally:
        controller.close()

    if as_json:
        click.echo(json.dumps(summary, indent=2, default=str))
        return

    click.echo(click.style(f"Sync Health (last {hours}h)", bold=True))
    click.echo("=" * 70)

    if not summary["by_type"]:
        click.echo("No sync activity in this period.")
        return

    for row in summary["by_type"]:
        total = row["total_runs"]
        succeeded = row["succeeded"]
        failed = row["failed"]
        avg_ms = row.get("avg_duration_ms")

        if failed == 0:
            health = click.style("HEALTHY", fg="green")
        elif failed < succeeded:
            health = click.style("DEGRADED", fg="yellow")
        else:
            health = click.style("FAILING", fg="red")

        avg_str = f"  avg {avg_ms:.0f}ms" if avg_ms else ""
        click.echo(f"  {row['type']:15s}  {health}  {succeeded}/{total} succeeded  {failed} failed{avg_str}")

        if row.get("last_failure"):
            last_fail = row["last_failure"]
            if hasattr(last_fail, "strftime"):
                last_fail = last_fail.strftime("%Y-%m-%d %H:%M:%S")
            click.echo(click.style(f"    Last failure: {last_fail}", dim=True))


@control_cmd.command("export")
@click.option("--output", "-o", default="control.duckdb", help="Output file path")
@click.pass_context
def control_export(ctx, output: str):
    """Export control plane DuckDB for use with DuckDB-WASM dashboard.

    Copies the control.duckdb file so it can be uploaded alongside the catalog
    for browser-based visualization with DuckDB-WASM.

    \b
    Examples:
        portolan control export
        portolan control export -o /tmp/status.duckdb
    """
    catalog = get_catalog(ctx)
    db_path = catalog.path / "control.duckdb"

    if not db_path.exists():
        raise click.ClickException("No control.duckdb found. Run some sync operations first.")

    output_path = Path(output)
    if output_path.resolve() == db_path.resolve():
        click.echo(f"Control DB is at: {db_path}")
        click.echo(f"  Size: {db_path.stat().st_size / 1024:.1f} KB")
        return

    shutil.copy2(db_path, output_path)
    click.echo(f"Exported control DB to: {output_path}")
    click.echo(f"  Size: {output_path.stat().st_size / 1024:.1f} KB")
    click.echo()
    click.echo("Use with DuckDB-WASM to query sync history in the browser.")


# ============== CATALOG SOURCE FEDERATION ==============


# ============== CORS HELPER ==============

def _aws_sigv4_sign(method: str, url: str, headers: dict, payload: bytes,
                     region: str, access_key: str, secret_key: str, service: str = "s3") -> dict:
    """Sign an HTTP request using AWS Signature V4.

    Returns dict of authorization headers to merge into the request.
    """
    import hmac
    from datetime import datetime, timezone
    from urllib.parse import urlparse

    now = datetime.now(timezone.utc)
    datestamp = now.strftime("%Y%m%d")
    amzdate = now.strftime("%Y%m%dT%H%M%SZ")

    parsed = urlparse(url)
    host = parsed.hostname
    canonical_uri = parsed.path or "/"
    canonical_querystring = parsed.query or ""

    payload_hash = hashlib.sha256(payload).hexdigest()

    # Build canonical headers
    sign_headers = {
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amzdate,
    }
    for k, v in headers.items():
        sign_headers[k.lower()] = v

    sorted_header_keys = sorted(sign_headers.keys())
    canonical_headers = "".join(f"{k}:{sign_headers[k]}\n" for k in sorted_header_keys)
    signed_headers = ";".join(sorted_header_keys)

    canonical_request = "\n".join([
        method, canonical_uri, canonical_querystring,
        canonical_headers, signed_headers, payload_hash,
    ])

    credential_scope = f"{datestamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amzdate, credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    def _sign(key, msg):
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    signing_key = _sign(
        _sign(_sign(_sign(f"AWS4{secret_key}".encode("utf-8"), datestamp), region), service),
        "aws4_request",
    )
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    return {
        "Authorization": authorization,
        "x-amz-date": amzdate,
        "x-amz-content-sha256": payload_hash,
    }


def setup_cors_for_url(url: str, options: dict | None = None):
    """Configure CORS for a storage URL to enable browser access.

    For S3-compatible services (AWS S3, R2, MinIO, OVH, etc.), uses the S3
    PutBucketCors API via httpx with AWS SigV4 signing.
    For GCS, uses the GCS JSON API via httpx.
    For Azure, skips (CORS is configured at the storage account level).
    """
    import base64
    import os

    import httpx

    opts = options or {}

    if url.startswith("gs://"):
        # Google Cloud Storage — use GCS JSON API
        bucket = url[5:].split("/")[0]
        cors_config = {
            "cors": [{
                "origin": ["*"],
                "method": ["GET", "HEAD", "OPTIONS"],
                "responseHeader": [
                    "Content-Type", "Content-Length", "Content-Range",
                    "Access-Control-Allow-Origin",
                ],
                "maxAgeSeconds": 3600,
            }]
        }
        # Try to get an access token from gcloud
        import subprocess
        result = subprocess.run(
            ["gcloud", "auth", "print-access-token"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            # Fallback to gsutil if gcloud not available
            import tempfile
            gcs_cors = [{
                "origin": ["*"],
                "method": ["GET", "HEAD", "OPTIONS"],
                "responseHeader": [
                    "Content-Type", "Content-Length", "Content-Range",
                    "Access-Control-Allow-Origin",
                ],
                "maxAgeSeconds": 3600,
            }]
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(gcs_cors, f)
                cors_file = f.name
            try:
                subprocess.run(
                    ["gsutil", "cors", "set", cors_file, f"gs://{bucket}"],
                    capture_output=True, text=True, check=True,
                )
            finally:
                Path(cors_file).unlink()
            return

        token = result.stdout.strip()
        api_url = f"https://storage.googleapis.com/storage/v1/b/{bucket}"
        response = httpx.patch(
            api_url,
            json=cors_config,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        response.raise_for_status()

    elif url.startswith("s3://"):
        # S3-compatible (AWS S3, R2, MinIO, OVH, Wasabi, etc.)
        bucket = url[5:].split("/")[0]

        # Compatible XML body — explicit headers, no ID element, single origin per rule
        cors_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<CORSConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
  <CORSRule>
    <AllowedOrigin>*</AllowedOrigin>
    <AllowedMethod>GET</AllowedMethod>
    <AllowedMethod>HEAD</AllowedMethod>
    <AllowedMethod>OPTIONS</AllowedMethod>
    <AllowedHeader>content-type</AllowedHeader>
    <AllowedHeader>range</AllowedHeader>
    <ExposeHeader>ETag</ExposeHeader>
    <ExposeHeader>Content-Length</ExposeHeader>
    <ExposeHeader>Content-Range</ExposeHeader>
    <MaxAgeSeconds>3600</MaxAgeSeconds>
  </CORSRule>
</CORSConfiguration>"""

        # Get credentials from options or environment
        access_key = opts.get("access_key_id") or os.environ.get("AWS_ACCESS_KEY_ID", "")
        secret_key = opts.get("secret_access_key") or os.environ.get("AWS_SECRET_ACCESS_KEY", "")
        region = opts.get("region") or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        endpoint_url = opts.get("endpoint_url")

        if not access_key or not secret_key:
            return  # Can't sign without credentials

        content_md5 = base64.b64encode(hashlib.md5(cors_xml).digest()).decode()

        # Build the request URL
        if endpoint_url:
            # S3-compatible: use path-style
            req_url = f"{endpoint_url.rstrip('/')}/{bucket}/?cors"
        else:
            # AWS S3: use virtual-hosted style
            req_url = f"https://{bucket}.s3.{region}.amazonaws.com/?cors"

        headers = {"Content-MD5": content_md5, "Content-Type": "application/xml"}
        auth_headers = _aws_sigv4_sign(
            "PUT", req_url, headers, cors_xml, region, access_key, secret_key,
        )
        headers.update(auth_headers)

        response = httpx.put(req_url, headers=headers, content=cors_xml, timeout=30)
        response.raise_for_status()

    elif url.startswith("az://"):
        # Azure — CORS is configured at storage account level, not per-container
        pass

    # Local/file URLs don't need CORS


def _get_remote_options(catalog: CatalogConfig, remote_url: str) -> dict:
    """Find options for a remote URL from catalog config."""
    for remote in catalog.remotes.values():
        if remote.url == remote_url:
            return remote.options
    return {}


# ============== SYNC ==============

@cli.command()
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.option("--dry-run", is_flag=True, help="Show what would be synced without uploading")
@click.option("--force-with-lease", is_flag=True, help="Force push even if behind remote")
@click.pass_context
def sync(ctx, verbose: bool, dry_run: bool, force_with_lease: bool):
    """Sync local changes to remote catalog.

    Uploads new and modified resources to remote storage. Uses force-with-lease
    semantics to ensure safe concurrent updates.

    The sync will fail if:
    - Remote has changes you don't have (use 'portolan pull' first)
    - Remote manifest changed while uploading (concurrent modification)

    Use --force-with-lease to push even when behind remote.

    \b
    Examples:
        portolan sync                    # Sync local changes to remote
        portolan sync --dry-run          # Preview what would be synced
        portolan sync --force-with-lease # Force push even if behind
    """
    from catalog_state import (
        LocalState,
        Manifest,
        ResourceEntry,
        compute_status,
        get_remote_store,
        scan_local_resources,
    )

    catalog = get_catalog(ctx)
    state = LocalState.load(catalog.path / "state.json")

    if not state.remote_url:
        raise click.ClickException(
            "No remote configured. Add one with:\n"
            "  portolan remote add origin gs://your-bucket/path"
        )

    remote_options = _get_remote_options(catalog, state.remote_url)
    store = get_remote_store(state.remote_url, remote_options)
    status = compute_status(catalog.path, state, store)

    if status.error:
        raise click.ClickException(status.error)

    # Check if behind remote
    if status.is_behind and not force_with_lease:
        click.echo(click.style("Error: Remote has changes you don't have.", fg="red"))
        click.echo()
        click.echo("Options:")
        click.echo("  portolan pull              # Get remote changes first")
        click.echo("  portolan sync --force-with-lease  # Push anyway (may lose remote changes)")
        raise click.ClickException("Sync aborted. Pull remote changes first.")

    # Check if we have changes to push
    if not status.is_ahead:
        click.echo("Nothing to sync. Local catalog matches remote.")
        return

    click.echo(f"Syncing to {state.remote_url}...")
    click.echo(f"  {len(status.diff.added)} added, {len(status.diff.modified)} modified, {len(status.diff.deleted)} deleted")

    if dry_run:
        click.echo()
        click.echo("Dry run - would sync:")
        for path in status.diff.added[:10]:
            click.echo(click.style(f"  + {path}", fg="green"))
        for path in status.diff.modified[:10]:
            click.echo(click.style(f"  ~ {path}", fg="yellow"))
        for path in status.diff.deleted[:10]:
            click.echo(click.style(f"  - {path}", fg="red"))
        total = status.diff.total_changes
        shown = min(10, len(status.diff.added)) + min(10, len(status.diff.modified)) + min(10, len(status.diff.deleted))
        if total > shown:
            click.echo(f"  ... and {total - shown} more")
        return

    # Wrap the sync operation with the control plane
    controller = _get_controller(catalog)

    def _do_sync():
        from sync_controller import SyncResult

        uploaded = 0
        errors = 0
        resources_dir = catalog.path / "resources"

        # Upload added and modified files
        for path in status.diff.added + status.diff.modified:
            local_path = catalog.path / path
            if not local_path.exists():
                if verbose:
                    click.echo(f"  Warning: File not found: {path}")
                errors += 1
                continue

            try:
                data = local_path.read_bytes()
                store.put_resource(path, data)
                uploaded += 1

                if verbose:
                    action = "Added" if path in status.diff.added else "Updated"
                    click.echo(f"  {action}: {path}")
            except Exception as e:
                if verbose:
                    click.echo(f"  Error uploading {path}: {e}")
                errors += 1

        # Delete removed files
        deleted = 0
        for path in status.diff.deleted:
            try:
                store.delete_resource(path)
                deleted += 1
                if verbose:
                    click.echo(f"  Deleted: {path}")
            except Exception as e:
                if verbose:
                    click.echo(f"  Error deleting {path}: {e}")

        # Create new manifest
        local_resources = scan_local_resources(resources_dir)
        new_manifest = Manifest(
            resources=[
                ResourceEntry(path=p, sha256=h)
                for p, h in sorted(local_resources.items())
            ]
        )

        # Force-with-lease check: verify remote hasn't changed during upload
        current_remote_manifest, current_remote_hash = store.get_manifest()
        expected_hash = status.remote_manifest_hash

        if current_remote_hash != expected_hash:
            return SyncResult(
                success=False,
                error_message="Concurrent modification detected. Run 'portolan pull' first.",
                changes_added=len(status.diff.added),
                changes_modified=len(status.diff.modified),
                changes_deleted=len(status.diff.deleted),
            )

        # Upload new manifest
        new_hash = store.put_manifest(new_manifest)

        # Update local state
        state.base_manifest_hash = new_hash
        state.save(catalog.path / "state.json")

        # Save new base manifest locally
        base_manifest_path = catalog.path / "base_manifest.json"
        base_manifest_path.write_text(new_manifest.to_json())

        # Setup CORS automatically for cloud storage
        if state.remote_url and (state.remote_url.startswith("gs://") or state.remote_url.startswith("s3://")):
            try:
                setup_cors_for_url(state.remote_url, remote_options)
            except Exception:
                pass  # CORS setup is best-effort

        return SyncResult(
            success=True,
            changes_added=len(status.diff.added),
            changes_modified=len(status.diff.modified),
            changes_deleted=deleted,
            metadata={"uploaded": uploaded, "errors": errors},
        )

    if controller:
        result = controller.execute("remote_push", state.remote_url, _do_sync)
        controller.close()
    else:
        result = _do_sync()

    if not result.success:
        click.echo()
        click.echo(click.style(f"Error: {result.error_message}", fg="red"))
        raise click.ClickException("Sync failed.")

    click.echo()
    click.echo(click.style("Sync complete!", fg="green"))
    click.echo(f"  Uploaded: {result.metadata.get('uploaded', 0)}")
    click.echo(f"  Deleted: {result.changes_deleted}")
    if result.metadata.get("errors"):
        click.echo(click.style(f"  Errors: {result.metadata['errors']}", fg="yellow"))
    click.echo(f"\nRemote: {state.remote_url}")


# ============== STATUS ==============

@cli.command()
@click.option("--verbose", "-v", is_flag=True, help="Show detailed change list")
@click.pass_context
def status(ctx, verbose: bool):
    """Show catalog status and sync state."""
    from catalog_state import LocalState, compute_status, get_remote_store

    catalog = find_catalog()

    if catalog is None:
        click.echo("No Portolan catalog found in current directory.")
        click.echo("Run 'portolan init' to create one.")
        return

    click.echo(click.style("Portolan Catalog Status", bold=True))
    click.echo("=" * 40)
    click.echo(f"Location: {catalog.path}")

    # Load state and compute status
    state = LocalState.load(catalog.path / "state.json")

    # Show remote info
    click.echo()
    if state.remote_url:
        click.echo(f"Remote: {state.remote_url}")

        # Compute status with remote
        try:
            remote_options = _get_remote_options(catalog, state.remote_url)
            store = get_remote_store(state.remote_url, remote_options)
            cat_status = compute_status(catalog.path, state, store)

            # Show sync status like git
            if cat_status.error:
                click.echo(click.style(f"  Error: {cat_status.error}", fg="red"))
            else:
                status_parts = []
                if cat_status.is_behind:
                    status_parts.append(click.style("behind remote", fg="yellow"))
                if cat_status.is_ahead:
                    status_parts.append(click.style("ahead of remote", fg="green"))
                if not status_parts:
                    status_parts.append(click.style("up to date", fg="green"))

                click.echo(f"Status: {', '.join(status_parts)}")

                # Show changes if dirty
                if cat_status.is_dirty:
                    click.echo()
                    click.echo("Local changes:")
                    if cat_status.diff.added:
                        click.echo(click.style(f"  {len(cat_status.diff.added)} added", fg="green"))
                        if verbose:
                            for p in cat_status.diff.added[:10]:
                                click.echo(f"    + {p}")
                            if len(cat_status.diff.added) > 10:
                                click.echo(f"    ... and {len(cat_status.diff.added) - 10} more")

                    if cat_status.diff.modified:
                        click.echo(click.style(f"  {len(cat_status.diff.modified)} modified", fg="yellow"))
                        if verbose:
                            for p in cat_status.diff.modified[:10]:
                                click.echo(f"    ~ {p}")
                            if len(cat_status.diff.modified) > 10:
                                click.echo(f"    ... and {len(cat_status.diff.modified) - 10} more")

                    if cat_status.diff.deleted:
                        click.echo(click.style(f"  {len(cat_status.diff.deleted)} deleted", fg="red"))
                        if verbose:
                            for p in cat_status.diff.deleted[:10]:
                                click.echo(f"    - {p}")
                            if len(cat_status.diff.deleted) > 10:
                                click.echo(f"    ... and {len(cat_status.diff.deleted) - 10} more")

                    click.echo()
                    click.echo("Use 'portolan sync' to push changes")

                if cat_status.is_behind:
                    click.echo()
                    click.echo("Use 'portolan pull' to get remote changes")

        except Exception as e:
            click.echo(click.style(f"  Could not check remote: {e}", fg="yellow"))
    else:
        click.echo("Remote: " + click.style("not configured", dim=True))
        click.echo("  Run 'portolan remote add origin <url>' to set up remote")

    # Count resources
    resources_dir = catalog.path / "resources"
    resource_count = len(list(resources_dir.rglob("*.json"))) if resources_dir.exists() else 0
    click.echo()
    click.echo(f"Resources: {resource_count}")

    # Show outputs
    click.echo()
    click.echo("Outputs:")
    click.echo("  Metadata:")
    for name, val in catalog.outputs.metadata.items():
        enabled = val.get("enabled", False) if isinstance(val, dict) else bool(val)
        out_status = click.style("enabled", fg="green") if enabled else click.style("disabled", dim=True)
        click.echo(f"    {name}: {out_status}")
    click.echo("  Data:")
    for name, val in catalog.outputs.data.items():
        enabled = val.get("enabled", False) if isinstance(val, dict) else bool(val)
        out_status = click.style("enabled", fg="green") if enabled else click.style("disabled", dim=True)
        click.echo(f"    {name}: {out_status}")




# ============== VALIDATE ==============

@cli.command()
@click.argument("target", required=False)
@click.option("--resources-only", is_flag=True, help="Only validate resources, not config/state")
@click.option("--verbose", "-v", is_flag=True, help="Show all validation details")
@click.pass_context
def validate(ctx, target: str | None, resources_only: bool, verbose: bool):
    """Validate catalog configuration and resources against schemas.

    Checks JSON files for schema compliance and reports errors.

    \b
    Examples:
        portolan validate                    # Validate entire catalog
        portolan validate --resources-only   # Only validate resources
        portolan validate default/cities     # Validate specific resource
    """
    from schemas import (
        validate_catalog,
        validate_config_file,
        validate_resource_file,
        validate_state_file,
    )

    catalog = find_catalog()
    if catalog is None:
        click.echo("No Portolan catalog found. Run 'portolan init' to create one.")
        return

    all_errors: dict[str, list[str]] = {}

    if target:
        # Validate specific resource
        parts = target.split("/")
        if len(parts) == 2:
            namespace, name = parts
        else:
            namespace = "default"
            name = target

        resource_path = catalog.path / "resources" / namespace / f"{name}.json"
        if not resource_path.exists():
            raise click.ClickException(f"Resource not found: {resource_path}")

        errors = validate_resource_file(resource_path)
        if errors:
            all_errors[str(resource_path)] = errors
    else:
        # Validate entire catalog
        if not resources_only:
            # Validate config
            config_path = catalog.path / "config.json"
            if config_path.exists():
                errors = validate_config_file(config_path)
                if errors:
                    all_errors[str(config_path)] = errors
                elif verbose:
                    click.echo(f"✓ {config_path}")

            # Validate state
            state_path = catalog.path / "state.json"
            if state_path.exists():
                errors = validate_state_file(state_path)
                if errors:
                    all_errors[str(state_path)] = errors
                elif verbose:
                    click.echo(f"✓ {state_path}")

        # Validate all resources
        resources_dir = catalog.path / "resources"
        if resources_dir.exists():
            resource_files = list(resources_dir.rglob("*.json"))
            # Skip _index.json files
            resource_files = [f for f in resource_files if not f.name.startswith("_")]

            for resource_file in resource_files:
                errors = validate_resource_file(resource_file)
                if errors:
                    all_errors[str(resource_file)] = errors
                elif verbose:
                    click.echo(f"✓ {resource_file}")

    # Report results
    if all_errors:
        click.echo()
        click.echo(click.style("Validation errors found:", fg="red", bold=True))
        click.echo()
        for path, errors in all_errors.items():
            click.echo(click.style(f"  {path}:", fg="yellow"))
            for error in errors:
                click.echo(f"    - {error}")
        click.echo()
        raise click.ClickException(f"Validation failed: {len(all_errors)} file(s) with errors")
    else:
        file_count = 1 if target else len(list((catalog.path / "resources").rglob("*.json"))) + 2
        click.echo(click.style(f"✓ Validation passed ({file_count} files)", fg="green"))


# ============== CLONE ==============

@cli.command()
@click.argument("url")
@click.argument("path", type=click.Path(), default=".", required=False)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def clone(url: str, path: str, verbose: bool):
    """Clone an existing Portolan catalog from a remote URL.

    Downloads the manifest and all resources to create a local working copy.
    The remote is the source of truth - use 'portolan pull' to get updates.

    \b
    Examples:
        portolan clone gs://my-bucket/catalog
        portolan clone https://storage.googleapis.com/portolan-demo-catalog
        portolan clone gs://my-bucket/catalog ./my-local-copy
    """
    from catalog_state import LocalState, get_remote_store

    catalog_path = Path(path).resolve() / ".portolan"

    if catalog_path.exists():
        raise click.ClickException(f"Catalog already exists at {catalog_path}")

    click.echo(f"Cloning from {url}...")

    # Create remote store
    try:
        store = get_remote_store(url)
    except ValueError as e:
        raise click.ClickException(str(e))

    # Fetch manifest
    manifest, manifest_hash = store.get_manifest()

    if manifest is None:
        raise click.ClickException(f"No manifest found at {url}. Is this a Portolan catalog?")

    click.echo(f"  Found manifest with {len(manifest.resources)} resources")

    # Create local catalog structure
    catalog = CatalogConfig(path=catalog_path)
    catalog.path.mkdir(parents=True, exist_ok=True)
    catalog.data_dir.mkdir(exist_ok=True)
    catalog.metadata_dir.mkdir(exist_ok=True)

    resources_dir = catalog.path / "resources"
    resources_dir.mkdir(exist_ok=True)

    # Download all resources
    downloaded = 0
    errors = 0

    for entry in manifest.resources:
        try:
            data = store.get_resource(entry.path)
            if data is None:
                if verbose:
                    click.echo(f"  Warning: Resource not found: {entry.path}")
                errors += 1
                continue

            # Save locally
            local_path = catalog.path / entry.path
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(data)
            downloaded += 1

            if verbose:
                click.echo(f"  Downloaded: {entry.path}")

        except Exception as e:
            if verbose:
                click.echo(f"  Error downloading {entry.path}: {e}")
            errors += 1

    # Save state
    state = LocalState(remote_url=url, base_manifest_hash=manifest_hash)
    state.save(catalog.path / "state.json")

    # Save base manifest for diff computation
    base_manifest_path = catalog.path / "base_manifest.json"
    base_manifest_path.write_text(manifest.to_json())

    catalog.save()

    click.echo()
    click.echo(click.style("Cloned successfully!", fg="green"))
    click.echo(f"  Location: {catalog_path}")
    click.echo(f"  Remote: {url}")
    click.echo(f"  Resources: {downloaded}")
    if errors:
        click.echo(click.style(f"  Errors: {errors}", fg="yellow"))
    click.echo()
    click.echo("Next steps:")
    click.echo("  portolan status          # View catalog status")
    click.echo("  portolan dataset add ... # Add new data")
    click.echo("  portolan sync            # Push changes to remote")


# ============== PULL ==============

@cli.command()
@click.option("--force", is_flag=True, help="Discard local changes and reset to remote")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def pull(ctx, force: bool, verbose: bool):
    """Pull latest changes from remote catalog.

    Downloads new and updated resources from the remote. If you have local
    changes, pull will refuse unless you use --force (which discards local changes).

    \b
    Examples:
        portolan pull              # Pull from remote
        portolan pull --force      # Discard local changes and reset to remote
    """
    from catalog_state import (
        LocalState,
        Manifest,
        compute_diff,
        compute_status,
        get_remote_store,
    )

    catalog = get_catalog(ctx)
    state = LocalState.load(catalog.path / "state.json")

    if not state.remote_url:
        raise click.ClickException("No remote configured. Run 'portolan clone' or set remote URL.")

    # Compute current status
    remote_options = _get_remote_options(catalog, state.remote_url)
    store = get_remote_store(state.remote_url, remote_options)
    status = compute_status(catalog.path, state, store)

    if status.error:
        raise click.ClickException(status.error)

    # Check if we're behind
    if not status.is_behind:
        click.echo("Already up to date.")
        return

    # Check for local changes
    if status.is_dirty and not force:
        click.echo(click.style("Error: Local changes detected.", fg="red"))
        click.echo(f"  {len(status.diff.added)} added, {len(status.diff.modified)} modified, {len(status.diff.deleted)} deleted")
        click.echo()
        click.echo("Options:")
        click.echo("  portolan sync       # Push your changes first")
        click.echo("  portolan pull --force  # Discard local changes")
        raise click.ClickException("Pull aborted. Local changes would be overwritten.")

    click.echo(f"Pulling from {state.remote_url}...")

    controller = _get_controller(catalog)

    def _do_pull():
        from sync_controller import SyncResult

        # Fetch new manifest
        remote_manifest, remote_hash = store.get_manifest()
        if remote_manifest is None:
            return SyncResult(success=False, error_message="Could not fetch remote manifest")

        # Load base manifest for comparison
        base_manifest_path = catalog.path / "base_manifest.json"
        if base_manifest_path.exists():
            base_manifest = Manifest.from_json(base_manifest_path.read_text())
            base_resources = base_manifest.get_resource_map()
        else:
            base_resources = {}

        remote_resources = remote_manifest.get_resource_map()

        # Compute what changed on remote
        remote_diff = compute_diff(base_resources, remote_resources)

        added = 0
        updated = 0
        deleted = 0

        # Download new and modified files
        for path in remote_diff.added + remote_diff.modified:
            try:
                data = store.get_resource(path)
                if data:
                    local_path = catalog.path / path
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    local_path.write_bytes(data)

                    if path in remote_diff.added:
                        added += 1
                    else:
                        updated += 1

                    if verbose:
                        action = "Added" if path in remote_diff.added else "Updated"
                        click.echo(f"  {action}: {path}")
            except Exception as e:
                if verbose:
                    click.echo(f"  Error: {path}: {e}")

        # Delete removed files
        for path in remote_diff.deleted:
            local_path = catalog.path / path
            if local_path.exists():
                local_path.unlink()
                deleted += 1
                if verbose:
                    click.echo(f"  Deleted: {path}")

        # Update state
        state.base_manifest_hash = remote_hash
        state.save(catalog.path / "state.json")

        # Save new base manifest
        base_manifest_path.write_text(remote_manifest.to_json())

        return SyncResult(
            success=True,
            changes_added=added,
            changes_modified=updated,
            changes_deleted=deleted,
        )

    if controller:
        result = controller.execute("remote_pull", state.remote_url, _do_pull)
        controller.close()
    else:
        result = _do_pull()

    if not result.success:
        raise click.ClickException(result.error_message)

    click.echo()
    click.echo(click.style("Pull complete!", fg="green"))
    click.echo(f"  Added: {result.changes_added}")
    click.echo(f"  Updated: {result.changes_modified}")
    click.echo(f"  Deleted: {result.changes_deleted}")


# ============== DISCOVERY HELPERS ==============


def fetch_json(url: str) -> dict:
    """Fetch JSON from a URL."""
    import httpx

    response = httpx.get(url, follow_redirects=True, timeout=30)
    response.raise_for_status()
    return response.json()


def discover_arcgis_services(
    services_url: str, verbose: bool = False
) -> tuple[list[dict], list[dict]]:
    """Discover FeatureServers and ImageServers from an ArcGIS REST endpoint.

    Recursively crawls folders to find services in subdirectories.

    Args:
        services_url: ArcGIS REST services URL (e.g. https://...arcgis.com/.../rest/services)
        verbose: Print discovery progress

    Returns:
        (feature_servers, image_servers) where each is a list of dicts:
          feature_server: {name, url, layers: [{id, name, geometryType}], _folder_path}
          image_server: {name, url, pixel_type, band_count, extent, _folder_path}
    """
    import httpx

    services_url = services_url.rstrip("/")

    feature_servers = []
    image_servers = []

    def _crawl_folder(folder_url: str, folder_path: str):
        if verbose:
            label = folder_path or "(root)"
            click.echo(f"Discovering services in {label}...")

        try:
            response = httpx.get(f"{folder_url}?f=json", timeout=30)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            if verbose:
                click.echo(f"  Failed to fetch {folder_url}: {e}")
            return

        for service in data.get("services", []):
            service_type = service.get("type")
            name = service.get("name", "unknown")
            # ArcGIS returns names like "FolderA/ServiceName" — strip the folder prefix
            short_name = name.split("/")[-1] if "/" in name else name

            if service_type == "FeatureServer":
                url = service.get("url") or f"{services_url}/{name}/FeatureServer"
                try:
                    fs_response = httpx.get(f"{url}?f=json", timeout=30)
                    fs_response.raise_for_status()
                    fs_data = fs_response.json()
                    layers = fs_data.get("layers", [])
                    feature_servers.append({
                        "name": short_name, "url": url, "layers": layers,
                        "_folder_path": folder_path,
                    })
                    if verbose:
                        click.echo(f"  FeatureServer: {name} ({len(layers)} layers)")
                except Exception as e:
                    if verbose:
                        click.echo(f"  Skipping FeatureServer {name}: {e}")

            elif service_type == "ImageServer":
                url = service.get("url") or f"{services_url}/{name}/ImageServer"
                try:
                    is_response = httpx.get(f"{url}?f=json", timeout=30)
                    is_response.raise_for_status()
                    is_data = is_response.json()
                    image_servers.append({
                        "name": short_name,
                        "url": url,
                        "pixel_type": is_data.get("pixelType"),
                        "band_count": is_data.get("bandCount"),
                        "extent": is_data.get("extent"),
                        "_folder_path": folder_path,
                    })
                    if verbose:
                        bands = is_data.get("bandCount", "?")
                        pixel_type = is_data.get("pixelType", "?")
                        click.echo(f"  ImageServer: {name} ({bands} bands, {pixel_type})")
                except Exception as e:
                    if verbose:
                        click.echo(f"  Skipping ImageServer {name}: {e}")

        # Recursively crawl subfolders
        for folder_name in data.get("folders", []):
            sub_path = f"{folder_path}/{folder_name}" if folder_path else folder_name
            _crawl_folder(f"{services_url}/{folder_name}", sub_path)

    _crawl_folder(services_url, "")

    return feature_servers, image_servers


def get_stac_links(stac_obj: dict, rel: str) -> list[dict]:
    """Get links with a specific rel from a STAC object."""
    return [link for link in stac_obj.get("links", []) if link.get("rel") == rel]


def resolve_url(base_url: str, href: str) -> str:
    """Resolve a relative URL against a base URL."""
    from urllib.parse import urljoin
    return urljoin(base_url, href)


def extract_asset_format(asset: dict) -> str:
    """Determine the format of a STAC asset."""
    media_type = asset.get("type", "")
    href = asset.get("href", "").lower()

    # Check media type first
    if "geotiff" in media_type or "tiff" in media_type:
        return "cog"
    if "geoparquet" in media_type or "parquet" in media_type:
        return "geoparquet"
    if "zarr" in media_type:
        return "zarr"
    if "pmtiles" in media_type:
        return "pmtiles"
    if "json" in media_type and "3dtiles" in href:
        return "3dtiles"
    if "las" in media_type or "copc" in media_type:
        return "copc"

    # Fall back to extension
    if href.endswith(".tif") or href.endswith(".tiff"):
        return "cog"
    if href.endswith(".parquet") or href.endswith(".geoparquet"):
        return "geoparquet"
    if href.endswith(".zarr") or "zarr" in href:
        return "zarr"
    if href.endswith(".pmtiles"):
        return "pmtiles"
    if href.endswith(".copc.laz"):
        return "copc"

    return "unknown"



def _stac_item_to_load_entry(item: dict, item_url: str) -> dict | None:
    """Convert a STAC item to a load entry dict for the load command."""
    properties = item.get("properties", {})
    bbox = item.get("bbox", [])

    # Find the primary asset
    assets = item.get("assets", {})
    primary_asset = None
    for key in ["data", "visual", "image", "default", "asset"]:
        if key in assets:
            primary_asset = assets[key]
            break
    if not primary_asset and assets:
        primary_asset = next(iter(assets.values()))
    if not primary_asset:
        return None

    asset_format = extract_asset_format(primary_asset)
    asset_href = primary_asset.get("href", "")

    # Determine kind from format
    raster_formats = {"cog", "zarr", "3dtiles"}
    vector_formats = {"geoparquet"}
    pointcloud_formats = {"copc"}
    if asset_format in raster_formats:
        kind = "raster"
    elif asset_format in vector_formats:
        kind = "vector"
    elif asset_format in pointcloud_formats:
        kind = "pointcloud"
    else:
        kind = "other"

    # Determine origin type
    origin_type = "stac"

    return {
        "name": item.get("id", "unknown"),
        "kind": kind,
        "origin_type": origin_type,
        "url": asset_href or item_url,
        "title": properties.get("title") or item.get("id"),
        "description": properties.get("description", ""),
        "stac_collection": item.get("collection"),
        "stac_item_id": item.get("id"),
    }

@cli.command("rebuild")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.option("--base-url", help="Base URL where catalog will be hosted (e.g., gs://bucket/path)")
@click.option("--outputs-only", is_flag=True, help="Only rebuild STAC/ISO outputs, not Iceberg")
@click.pass_context
def rebuild(ctx, verbose: bool, base_url: str | None, outputs_only: bool):
    """Rebuild catalog and all enabled outputs from scratch.

    Use this after changing output settings or to regenerate everything.
    For normal workflow, outputs are updated automatically when adding data.

    \b
    Examples:
        portolan rebuild                              # Rebuild everything
        portolan rebuild --outputs-only               # Only rebuild STAC/ISO
        portolan rebuild --base-url gs://my-bucket    # Rebuild with specific base URL
    """
    from output_generators import (
        regenerate_all_outputs,
        regenerate_metadata_outputs,
    )

    catalog = get_catalog(ctx)

    # Show what will be rebuilt
    enabled_meta = [k for k, v in catalog.outputs.metadata.items()
                    if (v.get("enabled", False) if isinstance(v, dict) else v)]
    enabled_data = [k for k, v in catalog.outputs.data.items()
                    if (v.get("enabled", False) if isinstance(v, dict) else v)]
    click.echo(f"Rebuilding metadata: {', '.join(enabled_meta) or 'none'}")
    click.echo(f"Rebuilding data: {', '.join(enabled_data) or 'none'}")

    if outputs_only:
        click.echo("Rebuilding metadata outputs only (--outputs-only)")
        regenerate_metadata_outputs(catalog, verbose=verbose)
        click.echo(click.style("Metadata outputs rebuilt!", fg="green"))
        return

    # Full rebuild — delegate to output generators
    regenerate_all_outputs(catalog, verbose=verbose)

    # Also keep a simple catalog.parquet at root for easy access
    meta_parquet = catalog.path / "data" / "_meta" / "resources" / "resources.parquet"
    simple_parquet = catalog.path / "catalog.parquet"
    if meta_parquet.exists():
        shutil.copy(meta_parquet, simple_parquet)

    click.echo()
    click.echo(click.style("Catalog rebuilt!", fg="green"))
    click.echo(f"  Location: {catalog.path}")

    # Show query hints
    metadata_path = catalog.path / "data" / "_meta" / "resources" / "metadata" / "v1.metadata.json"
    if metadata_path.exists():
        click.echo(f"\nQuery with DuckDB (Iceberg):")
        click.echo(f"  duckdb -c \"SELECT * FROM iceberg_scan('{metadata_path}')\"")

    if simple_parquet.exists():
        click.echo(f"\nQuery with DuckDB (simple Parquet):")
        click.echo(f"  duckdb -c \"SELECT name, format, title FROM '{simple_parquet}'\"")



@cli.command("load")
@click.argument("url")
@click.option("--type", "catalog_type", type=click.Choice(["stac", "arcgis-server"]),
              help="Catalog type (auto-detected if omitted)")
@click.option("--namespace", "-ns", help="Namespace (default: derived from catalog type)")
@click.option("--max-items", type=int, default=100, help="Maximum items to load (0 = all)")
@click.option("--collections", "-c", multiple=True, help="Filter to specific collections (STAC only)")
@click.option("--dry-run", is_flag=True, help="Preview what would be added")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def load_catalog(ctx, url: str, catalog_type: str | None, namespace: str | None,
                 max_items: int, collections: tuple, dry_run: bool, verbose: bool):
    """Discover and add resources from an external catalog or service.

    Auto-detects catalog type from URL. Supports STAC catalogs and ArcGIS REST services.
    Resources are registered for discovery (state: REGISTERED). Use 'portolan refresh'
    to download and process individual resources afterward.

    \b
    Examples:
        portolan load https://earth-search.aws.element84.com/v1
        portolan load https://earth-search.aws.element84.com/v1 -c sentinel-2-l2a --max-items 10
        portolan load https://services.arcgis.com/.../rest/services
        portolan load https://server.com/rest/services --dry-run
    """
    from portolan_resource import save_resource

    catalog = get_catalog(ctx)

    # Auto-detect catalog type
    if not catalog_type:
        if "arcgis" in url.lower() or "/rest/services" in url.lower():
            catalog_type = "arcgis-server"
        else:
            catalog_type = "stac"
        if verbose:
            click.echo(f"  Auto-detected catalog type: {catalog_type}")

    # Default namespace
    if not namespace:
        namespace = "arcgis" if catalog_type == "arcgis-server" else "stac"
    _validate_namespace_or_raise(namespace)

    click.echo(f"Discovering resources from {url}...")

    resources_to_add = []

    if catalog_type == "stac":
        resources_to_add = _load_discover_stac(url, namespace, max_items, collections, verbose)
    elif catalog_type == "arcgis-server":
        resources_to_add = _load_discover_arcgis(url, namespace, verbose)
        # Apply max_items
        if max_items > 0 and len(resources_to_add) > max_items:
            resources_to_add = resources_to_add[:max_items]
    else:
        raise click.ClickException(f"Unsupported catalog type: {catalog_type}")

    if not resources_to_add:
        click.echo("No resources found.")
        return

    click.echo(f"Found {len(resources_to_add)} resources")

    # Show kind breakdown
    kind_counts: dict[str, int] = {}
    for r in resources_to_add:
        kind_counts[r["kind"]] = kind_counts.get(r["kind"], 0) + 1
    for k, c in sorted(kind_counts.items()):
        click.echo(f"  {k}: {c}")

    if dry_run:
        click.echo("\nDry run -- would add:")
        for r in resources_to_add[:15]:
            ns = r.get("_ns", namespace)
            click.echo(f"  [{r['kind']}] {ns}/{r['name']}")
        if len(resources_to_add) > 15:
            click.echo(f"  ... and {len(resources_to_add) - 15} more")
        return

    # Register each resource
    click.echo(f"\nRegistering resources...")
    saved = 0
    errors = 0

    for item in resources_to_add:
        item_ns = item.get("_ns", namespace)
        try:
            resource, resource_path = _register_resource(
                catalog,
                origin_type=item["origin_type"],
                url=item.get("url"),
                name=item["name"],
                namespace=item_ns,
                layer=item.get("layer"),
                title=item.get("title"),
                description=item.get("description"),
                verbose=False,
            )
            # Set STAC-specific origin fields
            if item.get("stac_collection"):
                resource.origin.stac_collection = item["stac_collection"]
            if item.get("stac_item_id"):
                resource.origin.stac_item_id = item["stac_item_id"]

            save_resource(resource, resource_path)
            saved += 1
        except Exception as e:
            errors += 1
            if verbose:
                click.echo(f"  Error adding {item['name']}: {e}")

    click.echo()
    click.echo(click.style(f"Loaded {saved} resources!", fg="green"))
    if errors:
        click.echo(click.style(f"  Errors: {errors}", fg="yellow"))

    # Show namespaces used
    ns_used = sorted({r.get("_ns", namespace) for r in resources_to_add})
    if len(ns_used) > 1:
        click.echo(f"  Namespaces: {", ".join(ns_used)}")
    else:
        click.echo(f"  Namespace: {ns_used[0]}")

    click.echo("\nResources are registered for discovery (state: REGISTERED).")
    click.echo("Use 'portolan refresh <name>' to download and process individual resources.")


def _load_discover_stac(url: str, namespace: str, max_items: int,
                        collections: tuple, verbose: bool) -> list[dict]:
    """Discover resources from a STAC catalog."""
    try:
        root = fetch_json(url)
    except Exception as e:
        raise click.ClickException(f"Failed to fetch STAC catalog: {e}")

    stac_type = root.get("type", "Catalog")
    click.echo(f"Found STAC {stac_type}: {root.get('title', root.get('id', 'Unknown'))}")

    items: list[dict] = []
    collections_found: set[str] = set()

    def process_item(item: dict, item_url: str):
        entry = _stac_item_to_load_entry(item, item_url)
        if entry:
            entry["_ns"] = namespace
            items.append(entry)
            if verbose:
                click.echo(f"  Found: {entry['name']} [{entry['kind']}]")

    def crawl_catalog(catalog_url: str, catalog_obj: dict, depth: int = 0):
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

                if collections and child_type == "Collection" and child_id not in collections:
                    if verbose:
                        click.echo(f"  Skipping collection: {child_id}")
                    continue

                if child_type == "Collection":
                    collections_found.add(child_id)

                if verbose:
                    click.echo(f"  Crawling {child_type}: {child.get('title', child_id)}")

                crawl_catalog(child_url, child, depth + 1)
            except Exception as e:
                if verbose:
                    click.echo(f"  Error fetching {child_url}: {e}")

        # Process items
        item_links = get_stac_links(catalog_obj, "item")
        for link in item_links:
            if max_items > 0 and len(items) >= max_items:
                break
            item_url = resolve_url(catalog_url, link["href"])
            try:
                item = fetch_json(item_url)
                process_item(item, item_url)
            except Exception as e:
                if verbose:
                    click.echo(f"  Error fetching item: {e}")

        # STAC API style items link
        items_links = get_stac_links(catalog_obj, "items")
        for link in items_links:
            if max_items > 0 and len(items) >= max_items:
                break
            items_url = resolve_url(catalog_url, link["href"])
            try:
                items_response = fetch_json(items_url)
                for item in items_response.get("features", []):
                    if max_items > 0 and len(items) >= max_items:
                        break
                    process_item(item, items_url)
            except Exception as e:
                if verbose:
                    click.echo(f"  Error fetching items: {e}")

    crawl_catalog(url, root)

    if collections_found:
        click.echo(f"  Collections found: {len(collections_found)}")

    return items


def _load_discover_arcgis(url: str, namespace: str, verbose: bool) -> list[dict]:
    """Discover resources from an ArcGIS REST services endpoint."""
    if "/rest/services" not in url and not url.rstrip("/").endswith("/services"):
        raise click.ClickException(
            "URL should be an ArcGIS REST services endpoint "
            "(e.g. https://services6.arcgis.com/.../ArcGIS/rest/services)"
        )

    feature_servers, image_servers = discover_arcgis_services(url, verbose=verbose)

    from namespace_utils import arcgis_folder_to_namespace

    resources: list[dict] = []

    for fs in feature_servers:
        folder_path = fs.get("_folder_path", "")
        ns = arcgis_folder_to_namespace(namespace, folder_path)

        for layer in fs["layers"]:
            layer_id = layer.get("id", 0)
            layer_name = layer.get("name", f"layer_{layer_id}")
            geom_type = layer.get("geometryType", "unknown")

            if len(fs["layers"]) > 1:
                name = _sanitize_name(f"{fs['name']}_{layer_name}")
            else:
                name = _sanitize_name(fs["name"])

            layer_url = f"{fs['url']}/{layer_id}"
            resources.append({
                "name": name,
                "kind": "vector",
                "origin_type": "arcgis_featureserver",
                "url": layer_url,
                "layer": str(layer_id),
                "title": layer_name,
                "description": f"FeatureServer layer ({geom_type}) from {fs['name']}",
                "_ns": ns,
            })

    for imgs in image_servers:
        folder_path = imgs.get("_folder_path", "")
        ns = arcgis_folder_to_namespace(namespace, folder_path)
        name = _sanitize_name(imgs["name"])
        bands = imgs.get("band_count", "?")
        pixel_type = imgs.get("pixel_type", "unknown")

        resources.append({
            "name": name,
            "kind": "raster",
            "origin_type": "arcgis_imageserver",
            "url": imgs["url"],
            "title": imgs["name"],
            "description": f"ImageServer ({bands} bands, {pixel_type})",
            "_ns": ns,
        })

    total_layers = sum(len(fs["layers"]) for fs in feature_servers)
    click.echo(
        f"  Found {len(feature_servers)} FeatureServer(s) ({total_layers} layers), "
        f"{len(image_servers)} ImageServer(s)"
    )

    return resources

# ============== MAIN ==============

def main():
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
