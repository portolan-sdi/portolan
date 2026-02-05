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
    - gs://bucket/path          (Google Cloud Storage)
    - s3://bucket/path          (AWS S3)
    - file:///local/path        (Local filesystem)
"""

from __future__ import annotations

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
class CatalogConfig:
    """Configuration for a Portolan catalog."""
    path: Path
    default_remote: str | None = None
    remotes: dict[str, RemoteConfig] = field(default_factory=dict)
    outputs: dict[str, bool] = field(default_factory=lambda: {
        "iceberg": True,   # Always enabled - core Iceberg REST catalog
        "stac": False,     # STAC static catalog
        "iso19139": False, # ISO 19139 XML metadata
        "ducklake": False, # DuckLake catalog for DuckDB
        "web": False,      # Static web UI for browsing
    })

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
            "outputs": self.outputs,
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
            # Load outputs with defaults for missing keys
            default_outputs = {"iceberg": True, "stac": False, "iso19139": False, "ducklake": False, "web": False}
            outputs = {**default_outputs, **data.get("outputs", {})}
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
    - https://host/path (including S3/GCS public URLs)

    Returns:
        Tuple of (scheme, path_for_filesystem)
    """
    if url.startswith("s3://"):
        return "s3", url[5:]
    if url.startswith("gs://"):
        return "gs", url[5:]
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


def _open_remote_parquet(url: str):
    """
    Open a remote Parquet file and return a ParquetFile object.

    Only reads the metadata footer (range request), not the full file.
    Supports s3://, gs://, and https:// URLs.
    """
    import pyarrow.parquet as pq

    scheme, path = _parse_remote_url(url)

    if scheme == "s3":
        from pyarrow.fs import S3FileSystem
        # Extract region from path or use default
        s3fs = S3FileSystem(anonymous=True, region="us-west-2")
        return pq.ParquetFile(path, filesystem=s3fs)

    if scheme == "gs":
        from pyarrow.fs import GcsFileSystem
        gcsfs = GcsFileSystem(anonymous=True)
        return pq.ParquetFile(path, filesystem=gcsfs)

    if scheme == "https":
        import fsspec
        f = fsspec.open(url, "rb").open()
        return pq.ParquetFile(f)

    # Local file fallback
    return pq.ParquetFile(path)


def _get_remote_file_size(url: str) -> int:
    """Get the file size of a remote file via HEAD request or filesystem info."""
    scheme, path = _parse_remote_url(url)

    if scheme == "s3":
        from pyarrow.fs import S3FileSystem
        s3fs = S3FileSystem(anonymous=True, region="us-west-2")
        info = s3fs.get_file_info(path)
        return info.size

    if scheme == "gs":
        from pyarrow.fs import GcsFileSystem
        gcsfs = GcsFileSystem(anonymous=True)
        info = gcsfs.get_file_info(path)
        return info.size

    if scheme == "https":
        import httpx
        response = httpx.head(url, follow_redirects=True, timeout=10)
        content_length = response.headers.get("content-length")
        return int(content_length) if content_length else 0

    # Local file
    return Path(path).stat().st_size


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
    click.echo("  stac, iso19139, web")


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


# ============== RESOURCE LIFECYCLE ==============


@cli.command()
@click.argument("origin_type", type=click.Choice([
    "file", "wfs", "arcgis_featureserver", "arcgis_imageserver", "stac", "postgres", "oracle"
]))
@click.argument("url")
@click.option("--name", "-n", help="Resource name (default: derived from URL)")
@click.option("--namespace", "-ns", default="default", help="Namespace")
@click.option("--layer", "-l", help="Layer name (for multi-layer sources)")
@click.option("--connection-ref", help="Connection reference for database sources (stored in .portolan/connections.json)")
@click.option("--title", help="Human-readable title")
@click.option("--description", help="Description")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def register(ctx, origin_type: str, url: str, name: str | None, namespace: str,
             layer: str | None, connection_ref: str | None, title: str | None,
             description: str | None, verbose: bool):
    """
    Register an external resource (creates EXTERNAL state).

    Creates a pointer to remote data without downloading.
    Use 'portolan snapshot' to download the data locally.

    \b
    Examples:
        portolan register file /path/to/data.parquet --name cities
        portolan register arcgis_featureserver https://services.arcgis.com/.../0 --name boundaries
        portolan register arcgis_imageserver https://services.arcgis.com/.../ImageServer --name dem
        portolan register stac https://earth-search.aws.element84.com/v1/items/xyz
        portolan register postgres "public.buildings" --connection-ref mydb --name buildings
        portolan register wfs https://example.com/wfs --layer boundaries
    """
    from portolan_resource import (
        Origin,
        Resource,
        ResourceMetadata,
        UserMetadata,
        save_resource,
    )
    from schemas import validate_resource

    catalog = get_catalog(ctx)

    # Derive name from URL if not provided
    if not name:
        if origin_type == "file":
            name = Path(url).stem
        else:
            # Extract last path component or use hash
            from urllib.parse import urlparse
            parsed = urlparse(url)
            path_parts = [p for p in parsed.path.split("/") if p]
            name = path_parts[-1] if path_parts else f"resource_{hash(url) % 10000}"

    # Sanitize name
    name = name.lower().replace(" ", "_").replace("-", "_")
    name = "".join(c for c in name if c.isalnum() or c == "_")

    # Detect kind based on origin type
    kind = "vector"  # Default
    if origin_type == "arcgis_imageserver":
        kind = "raster"

    # For database types, layer is the table name, URL is optional
    if origin_type in ("postgres", "oracle"):
        # URL is actually the table name for database sources
        table_name = url
        if not layer:
            layer = table_name
        url = None  # No URL for database sources

    # Create origin
    # For "file" type, detect if it's a remote URL (s3://, gs://, https://) and keep as-is
    if origin_type == "file" and url and not any(url.startswith(p) for p in ("s3://", "gs://", "https://", "http://")):
        resolved_url = str(Path(url).resolve())
    elif origin_type in ("postgres", "oracle"):
        resolved_url = None
    else:
        resolved_url = url

    origin = Origin(
        type=origin_type,
        url=resolved_url,
        layer=layer,
        connection_ref=connection_ref,
    )

    # Create resource in EXTERNAL state
    resource = Resource(
        name=name,
        kind=kind,
        origin=origin,
        metadata=ResourceMetadata(
            user=UserMetadata(title=title, description=description),
        ),
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    # Validate before saving
    errors = validate_resource(resource.to_dict())
    if errors:
        click.echo(click.style("Validation errors:", fg="red"))
        for error in errors:
            click.echo(f"  - {error}")
        raise click.ClickException("Resource validation failed")

    # Save resource
    resources_dir = catalog.path / "resources" / namespace
    resource_path = resources_dir / f"{name}.json"
    save_resource(resource, resource_path)

    click.echo(f"Registered {origin_type} resource: {name}")
    click.echo(f"  State: {resource.state.upper()}")
    click.echo(f"  URL: {url}")
    click.echo(f"  Location: {resource_path}")
    click.echo()
    click.echo(f"Next: portolan snapshot {name} --namespace {namespace}")


@cli.command()
@click.argument("resource_name", required=False)
@click.option("--namespace", "-ns", default="default", help="Namespace")
@click.option("--all", "all_resources", is_flag=True, help="Snapshot all EXTERNAL resources in namespace")
@click.option("--force", "-f", is_flag=True, help="Re-snapshot even if already cached")
@click.option("--bbox", help="Bounding box filter: xmin,ymin,xmax,ymax (WGS84). For ImageServer/raster sources.")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def snapshot(ctx, resource_name: str | None, namespace: str, all_resources: bool, force: bool, bbox: str | None, verbose: bool):
    """
    Create a durable snapshot of an external resource.

    Downloads/extracts data to local storage in cloud-native format.

    For vector resources: creates GeoParquet + auto-registers as Iceberg
    (EXTERNAL -> MATERIALIZED in one step, since Iceberg registration is free).

    For raster resources: creates COG/Zarr cache only (EXTERNAL -> CACHED).
    Use 'portolan materialize' to convert to Raquet and register as Iceberg.

    \b
    Examples:
        portolan snapshot cities
        portolan snapshot boundaries --namespace public
        portolan snapshot mydata --force  # Re-snapshot
        portolan snapshot satellite --bbox "-10,35,5,45"  # Spain bbox
        portolan snapshot --all --namespace federated_wildfire  # Batch snapshot
    """
    from portolan_resource import (
        SnapshotAsset,
        compute_derived_metadata,
        load_resource,
        save_resource,
    )
    from schemas import validate_resource

    catalog = get_catalog(ctx)

    # Handle --all flag for batch operations
    if all_resources:
        namespace_dir = catalog.path / "resources" / namespace
        if not namespace_dir.exists():
            raise click.ClickException(f"Namespace not found: {namespace}")

        # Find all EXTERNAL resources
        resource_files = list(namespace_dir.glob("*.json"))
        if not resource_files:
            click.echo(f"No resources found in namespace: {namespace}")
            return

        external_resources = []
        for rf in resource_files:
            res = load_resource(rf)
            if res.state == "external" or (force and res.state == "cached"):
                external_resources.append(rf.stem)

        if not external_resources:
            click.echo(f"No EXTERNAL resources to snapshot in namespace: {namespace}")
            return

        click.echo(f"Batch snapshotting {len(external_resources)} resources in {namespace}...")
        click.echo()

        success = 0
        failed = 0
        for res_name in external_resources:
            try:
                # Recursively invoke snapshot for each resource
                ctx.invoke(snapshot, resource_name=res_name, namespace=namespace,
                          all_resources=False, force=force, bbox=bbox, verbose=verbose)
                success += 1
            except click.ClickException as e:
                click.echo(click.style(f"  Failed: {res_name} - {e.message}", fg="red"))
                failed += 1
            click.echo()

        click.echo(f"Batch snapshot complete: {success} succeeded, {failed} failed")
        return

    # Single resource mode
    if not resource_name:
        raise click.ClickException("Resource name required (or use --all)")

    # Load resource
    resource_path = catalog.path / "resources" / namespace / f"{resource_name}.json"
    if not resource_path.exists():
        raise click.ClickException(f"Resource not found: {resource_name} in namespace {namespace}")

    resource = load_resource(resource_path)

    if resource.state == "materialized" and not force:
        click.echo("Resource is already materialized. Use --force to re-snapshot.")
        return

    if resource.state == "cached" and not force:
        click.echo("Resource is already cached. Use --force to re-snapshot.")
        return

    if not resource.origin:
        raise click.ClickException("Resource has no origin - cannot snapshot.")

    click.echo(f"Snapshotting {resource_name}...")

    import shutil

    # Output path for snapshot
    snapshot_dir = catalog.path / "data" / "raw" / namespace / resource_name
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    output_path = snapshot_dir / f"{resource_name}.parquet"

    # Extract based on origin type
    if resource.origin.type == "file":
        source_path = Path(resource.origin.url)
        if not source_path.exists():
            raise click.ClickException(f"Source file not found: {source_path}")

        if source_path.suffix in (".parquet", ".geoparquet"):
            # Copy parquet file
            shutil.copy(source_path, output_path)
            if verbose:
                click.echo(f"  Copied {source_path} to {output_path}")
        else:
            # Convert to GeoParquet using geopandas
            import geopandas as gpd
            gdf = gpd.read_file(source_path)
            gdf.to_parquet(output_path)
            if verbose:
                click.echo(f"  Converted {source_path} to GeoParquet")

    elif resource.origin.type == "arcgis_featureserver":
        # Fetch layer metadata from ArcGIS REST API
        import httpx
        import subprocess
        from portolan_resource import SourceMetadata

        metadata_url = f"{resource.origin.url}?f=json"
        if verbose:
            click.echo(f"  Fetching layer metadata from {metadata_url}...")

        layer_meta = {}
        try:
            response = httpx.get(metadata_url, follow_redirects=True, timeout=30)
            response.raise_for_status()
            layer_meta = response.json()
        except Exception as e:
            if verbose:
                click.echo(f"  Warning: Could not fetch layer metadata: {e}")

        # Extract key metadata
        layer_name = layer_meta.get("name", "")
        layer_desc = layer_meta.get("description", "")
        geometry_type = layer_meta.get("geometryType", "")
        extent = layer_meta.get("extent", {})
        fields = layer_meta.get("fields", [])

        if verbose and layer_name:
            click.echo(f"  Layer: {layer_name}")
            click.echo(f"  Geometry: {geometry_type}")

        # Use gpio for extraction
        cmd = ["gpio", "extract", "arcgis", resource.origin.url, str(output_path)]
        if verbose:
            click.echo(f"  Running: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True, capture_output=not verbose)
        except subprocess.CalledProcessError as e:
            raise click.ClickException(f"Failed to extract from ArcGIS: {e}")
        except FileNotFoundError:
            raise click.ClickException(
                "gpio command not found. Install: pip install geoparquet-io"
            )

        # Store ArcGIS metadata
        if layer_meta:
            resource.metadata.source = SourceMetadata(
                provider="arcgis",
                ref={"service_url": resource.origin.url, "layer_id": layer_meta.get("id")},
                fetched_at=datetime.now(timezone.utc).isoformat(),
                data={
                    "name": layer_name,
                    "description": layer_desc,
                    "geometryType": geometry_type,
                    "extent": extent,
                    "fields": [{"name": f.get("name"), "type": f.get("type"), "alias": f.get("alias")} for f in fields],
                    "capabilities": layer_meta.get("capabilities"),
                    "currentVersion": layer_meta.get("currentVersion"),
                },
            )

    elif resource.origin.type == "wfs":
        # Use ogr2ogr for WFS extraction
        import subprocess
        from portolan_resource import SourceMetadata

        wfs_url = f"WFS:{resource.origin.url}"
        cmd = ["ogr2ogr", "-f", "Parquet", str(output_path), wfs_url]
        if resource.origin.layer:
            cmd.append(resource.origin.layer)
        if verbose:
            click.echo(f"  Running: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True, capture_output=not verbose)
        except subprocess.CalledProcessError as e:
            raise click.ClickException(f"Failed to extract from WFS: {e}")

        # Store WFS metadata (basic info - full metadata requires XML parsing)
        resource.metadata.source = SourceMetadata(
            provider="wfs",
            ref={"service_url": resource.origin.url, "layer": resource.origin.layer},
            fetched_at=datetime.now(timezone.utc).isoformat(),
            data={
                "service_type": "WFS",
                "layer": resource.origin.layer,
            },
        )

    elif resource.origin.type == "arcgis_imageserver":
        # Fetch service metadata from ArcGIS REST API
        import httpx
        import subprocess
        from portolan_resource import SourceMetadata

        metadata_url = f"{resource.origin.url}?f=json"
        if verbose:
            click.echo(f"  Fetching service metadata from {metadata_url}...")

        service_meta = {}
        try:
            response = httpx.get(metadata_url, follow_redirects=True, timeout=30)
            response.raise_for_status()
            service_meta = response.json()
        except Exception as e:
            if verbose:
                click.echo(f"  Warning: Could not fetch service metadata: {e}")

        # Extract key metadata
        service_name = service_meta.get("name", "")
        service_desc = service_meta.get("description", "")
        extent = service_meta.get("extent", {})
        pixel_size_x = service_meta.get("pixelSizeX")
        pixel_size_y = service_meta.get("pixelSizeY")
        band_count = service_meta.get("bandCount")

        if verbose and service_name:
            click.echo(f"  Service: {service_name}")
            click.echo(f"  Bands: {band_count}, Pixel size: {pixel_size_x} x {pixel_size_y}")

        # Update kind to raster
        resource.kind = "raster"

        # Use raquet-io for extraction (outputs Raquet format)
        cmd = ["raquet-io", "convert", "imageserver", resource.origin.url, str(output_path)]
        if bbox:
            cmd.extend(["--bbox", bbox])
        if verbose:
            cmd.append("-v")
        click.echo(f"  Running: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True, capture_output=not verbose)
        except subprocess.CalledProcessError as e:
            raise click.ClickException(f"Failed to extract from ArcGIS ImageServer: {e}")
        except FileNotFoundError:
            raise click.ClickException(
                "raquet-io command not found. Install: pip install 'raquet-io[imageserver]'\n"
                "Note: GDAL must be installed separately (brew install gdal on macOS)"
            )

        # Store ImageServer metadata
        if service_meta:
            resource.metadata.source = SourceMetadata(
                provider="arcgis_imageserver",
                ref={"service_url": resource.origin.url},
                fetched_at=datetime.now(timezone.utc).isoformat(),
                data={
                    "name": service_name,
                    "description": service_desc,
                    "extent": extent,
                    "pixelSizeX": pixel_size_x,
                    "pixelSizeY": pixel_size_y,
                    "bandCount": band_count,
                    "serviceDataType": service_meta.get("serviceDataType"),
                    "currentVersion": service_meta.get("currentVersion"),
                },
            )

    elif resource.origin.type == "stac":
        # Download primary asset from STAC item
        import httpx
        from portolan_resource import SourceMetadata

        if verbose:
            click.echo(f"  Fetching STAC item from {resource.origin.url}...")

        try:
            response = httpx.get(resource.origin.url, follow_redirects=True, timeout=30)
            response.raise_for_status()
            item = response.json()
        except Exception as e:
            raise click.ClickException(f"Failed to fetch STAC item: {e}")

        # Extract STAC metadata
        stac_id = item.get("id")
        stac_collection = item.get("collection")
        stac_bbox = item.get("bbox")
        stac_properties = item.get("properties", {})

        # Update origin with STAC-specific fields
        resource.origin.stac_collection = stac_collection
        resource.origin.stac_item_id = stac_id

        if verbose:
            click.echo(f"  STAC Item: {stac_id}")
            click.echo(f"  Collection: {stac_collection}")
            if stac_bbox:
                click.echo(f"  Bbox: {stac_bbox}")

        # Find the primary data asset
        assets = item.get("assets", {})
        primary_asset = None

        # Priority order for asset keys
        priority_keys = ["data", "visual", "image", "default", "asset"]
        for key in priority_keys:
            if key in assets:
                primary_asset = assets[key]
                break

        # Fall back to first asset with parquet/tiff type
        if not primary_asset:
            for key, asset in assets.items():
                asset_type = asset.get("type", "")
                if "parquet" in asset_type or "tiff" in asset_type or "geotiff" in asset_type:
                    primary_asset = asset
                    break

        # Final fallback to first asset
        if not primary_asset and assets:
            primary_asset = next(iter(assets.values()))

        if not primary_asset:
            raise click.ClickException("No downloadable asset found in STAC item")

        asset_url = primary_asset.get("href")
        if not asset_url:
            raise click.ClickException("Asset has no href")

        # Convert s3:// URLs to https:// for public buckets
        if asset_url.startswith("s3://"):
            # s3://bucket-name/path -> https://bucket-name.s3.amazonaws.com/path
            parts = asset_url[5:].split("/", 1)
            bucket = parts[0]
            key = parts[1] if len(parts) > 1 else ""
            asset_url = f"https://{bucket}.s3.amazonaws.com/{key}"
            if verbose:
                click.echo(f"  Converted S3 URL to HTTPS")

        # Determine asset type
        asset_type = primary_asset.get("type", "")
        is_raster = "tiff" in asset_type.lower() or "geotiff" in asset_type.lower() or asset_url.endswith(".tif")
        is_parquet = "parquet" in asset_type.lower() or asset_url.endswith(".parquet")

        if verbose:
            click.echo(f"  Asset type: {asset_type}")
            click.echo(f"  Downloading asset from {asset_url}...")

        if is_raster:
            # For raster assets, download then convert with raquet-io
            import subprocess
            import tempfile

            # Download to temp file first
            temp_file = snapshot_dir / "temp_raster.tif"
            if verbose:
                click.echo(f"  Downloading raster to temp file...")
            try:
                response = httpx.get(asset_url, follow_redirects=True, timeout=300)
                response.raise_for_status()
                with open(temp_file, "wb") as f:
                    f.write(response.content)
            except Exception as e:
                raise click.ClickException(f"Failed to download STAC raster: {e}")

            # Convert to Raquet format
            if verbose:
                click.echo(f"  Converting raster to Raquet format...")
            cmd = ["raquet-io", "convert", "raster", str(temp_file), str(output_path)]
            if verbose:
                cmd.append("-v")
            try:
                subprocess.run(cmd, check=True, capture_output=not verbose)
            except subprocess.CalledProcessError as e:
                raise click.ClickException(f"Failed to convert raster STAC asset: {e}")
            except FileNotFoundError:
                raise click.ClickException(
                    "raquet-io command not found. Install: pip install raquet-io\n"
                    "Note: GDAL must be installed separately (brew install gdal on macOS)"
                )
            finally:
                # Clean up temp file
                if temp_file.exists():
                    temp_file.unlink()
        else:
            # For parquet/vector assets, download directly
            try:
                response = httpx.get(asset_url, follow_redirects=True, timeout=300)
                response.raise_for_status()
                with open(output_path, "wb") as f:
                    f.write(response.content)
            except Exception as e:
                raise click.ClickException(f"Failed to download STAC asset: {e}")

        # Store STAC metadata in resource
        resource.metadata.source = SourceMetadata(
            provider="stac",
            ref={"item_url": resource.origin.url, "item_id": stac_id},
            fetched_at=datetime.now(timezone.utc).isoformat(),
            data={
                "collection": stac_collection,
                "bbox": stac_bbox,
                "properties": stac_properties,
                "assets": {k: {"href": v.get("href"), "type": v.get("type")} for k, v in item.get("assets", {}).items()},
            },
        )

        # Update kind based on asset type
        if is_raster:
            resource.kind = "raster"

        # Store bbox in derived metadata if available
        if stac_bbox and len(stac_bbox) >= 4:
            # Will be merged with computed derived metadata later
            pass  # bbox will be set from stac_bbox below

    elif resource.origin.type == "postgres":
        # Extract from PostgreSQL using geopandas
        import geopandas as gpd

        conn_config = load_connection(catalog.path, resource.origin.connection_ref)
        if not conn_config:
            raise click.ClickException(
                f"Connection '{resource.origin.connection_ref}' not found. "
                f"Add it with: portolan connection add {resource.origin.connection_ref} <connection_string>"
            )

        table_name = resource.origin.layer
        if not table_name:
            raise click.ClickException("No table specified. Use --layer to specify the table name.")

        if verbose:
            click.echo(f"  Extracting from PostgreSQL table: {table_name}...")

        try:
            gdf = gpd.read_postgis(
                sql=f"SELECT * FROM {table_name}",
                con=conn_config["connection_string"],
                geom_col=conn_config.get("geometry_column", "geom"),
            )
            gdf.to_parquet(output_path)
        except Exception as e:
            raise click.ClickException(f"Failed to extract from PostgreSQL: {e}")

    elif resource.origin.type == "oracle":
        # Extract from Oracle using geopandas with cx_Oracle
        import geopandas as gpd

        conn_config = load_connection(catalog.path, resource.origin.connection_ref)
        if not conn_config:
            raise click.ClickException(
                f"Connection '{resource.origin.connection_ref}' not found. "
                f"Add it with: portolan connection add {resource.origin.connection_ref} <connection_string>"
            )

        table_name = resource.origin.layer
        if not table_name:
            raise click.ClickException("No table specified. Use --layer to specify the table name.")

        if verbose:
            click.echo(f"  Extracting from Oracle table: {table_name}...")

        try:
            gdf = gpd.read_postgis(
                sql=f"SELECT * FROM {table_name}",
                con=conn_config["connection_string"],
                geom_col=conn_config.get("geometry_column", "GEOMETRY"),
            )
            gdf.to_parquet(output_path)
        except Exception as e:
            raise click.ClickException(f"Failed to extract from Oracle: {e}")

    else:
        raise click.ClickException(f"Unsupported origin type: {resource.origin.type}")

    # Compute derived metadata
    if verbose:
        click.echo("  Computing derived metadata...")
    derived = compute_derived_metadata(output_path)

    # Check for schema drift
    old_derived = resource.metadata.derived
    if old_derived and old_derived.schema_hash:
        old_hash = old_derived.schema_hash
        new_hash = derived.schema_hash
        if old_hash != new_hash:
            click.echo()
            click.echo(click.style(f"⚠️  Schema drift detected for {resource_name}", fg="yellow"))
            click.echo(f"  Previous schema hash: {old_hash}")
            click.echo(f"  New schema hash:      {new_hash}")
            if not force:
                click.echo()
                click.echo("The schema has changed since the last snapshot.")
                click.echo("Use --force to accept the new schema.")
                raise click.ClickException("Schema drift detected. Use --force to accept new schema.")

            # Track the schema change
            derived.previous_schema_hash = old_hash
            derived.schema_changed_at = datetime.now(timezone.utc).isoformat()
            click.echo(click.style("  Schema change accepted with --force", fg="green"))

    # Update resource
    resource.assets.snapshot = SnapshotAsset(
        href=str(output_path.relative_to(catalog.path)),
        type="application/vnd.apache.parquet",
        taken_at=datetime.now(timezone.utc).isoformat(),
        format="geoparquet",
    )
    resource.metadata.derived = derived
    resource.updated_at = datetime.now(timezone.utc).isoformat()

    # Validate before saving
    errors = validate_resource(resource.to_dict())
    if errors:
        click.echo(click.style("Validation errors:", fg="red"))
        for error in errors:
            click.echo(f"  - {error}")
        raise click.ClickException("Resource validation failed after snapshot")

    # For vector resources (GeoParquet), auto-create Iceberg metadata
    # This is "lightweight Iceberg" - just metadata, no data rewrite needed
    if resource.kind == "vector" and resource.assets.snapshot and resource.assets.snapshot.format == "geoparquet":
        import uuid

        from iceberg_catalog import (
            create_table_metadata,
            generate_manifest_files,
            parquet_to_iceberg_table,
        )
        from portolan_resource import IcebergAsset

        if verbose:
            click.echo("  Auto-creating Iceberg metadata for vector resource...")

        table = parquet_to_iceberg_table(str(output_path), table_name=resource_name)
        metadata_dir = catalog.path / "data" / namespace / resource_name / "metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)

        table_uuid = str(uuid.uuid4())
        data_base_url = f"file://{catalog.path.absolute()}"
        table_path = f"{namespace}/{resource_name}"
        snapshot_file_url = f"file://{output_path.absolute()}"

        generate_manifest_files(
            table=table,
            data_base_url=data_base_url,
            metadata_dir=metadata_dir,
            arrow_schema=table.arrow_schema,
            snapshot_id=1,
            sequence_number=1,
            table_path=table_path,
            data_file_path=snapshot_file_url,
        )

        metadata = create_table_metadata(table, data_base_url, table_uuid, table_path=table_path)
        metadata_path = metadata_dir / "v1.metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        resource.assets.iceberg = IcebergAsset(
            metadata=str(metadata_path.relative_to(catalog.path)),
        )

    # Validate before saving
    errors = validate_resource(resource.to_dict())
    if errors:
        click.echo(click.style("Validation errors:", fg="red"))
        for error in errors:
            click.echo(f"  - {error}")
        raise click.ClickException("Resource validation failed after snapshot")

    # Save
    save_resource(resource, resource_path)

    click.echo(f"Snapshot created: {output_path}")
    click.echo(f"  State: {resource.state.upper()}")
    click.echo(f"  Size: {output_path.stat().st_size / 1024:.1f} KB")
    if derived.row_count:
        click.echo(f"  Rows: {derived.row_count}")

    if resource.assets.iceberg:
        # Vector: auto-materialized
        click.echo(f"  Iceberg: auto-registered (lightweight)")
        click.echo()
        click.echo("Query with DuckDB:")
        iceberg_meta = catalog.path / resource.assets.iceberg.metadata
        click.echo(f"  duckdb -c \"SELECT * FROM iceberg_scan('{iceberg_meta}')\"")
    else:
        # Raster/other: needs explicit materialize
        click.echo()
        click.echo(f"Next: portolan materialize {resource_name} --namespace {namespace}")


@cli.command()
@click.argument("resource_name", required=False)
@click.option("--namespace", "-ns", default="default", help="Namespace")
@click.option("--all", "all_resources", is_flag=True, help="Materialize all CACHED resources in namespace")
@click.option("--remote", is_flag=True, help="Create Iceberg metadata pointing to remote data (no download)")
@click.option("--force", "-f", is_flag=True, help="Re-materialize even if already done")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def materialize(ctx, resource_name: str | None, namespace: str, all_resources: bool, remote: bool, force: bool, verbose: bool):
    """
    Create Iceberg table from cached or remote data.

    For vector resources (GeoParquet), this is usually a no-op since
    snapshot auto-creates Iceberg metadata. Use --force to regenerate.

    For raster resources (COG/Zarr), this converts to Raquet format
    and creates Iceberg metadata (expensive operation).

    With --remote, creates Iceberg metadata pointing to a remote GeoParquet
    file without downloading it. Only reads the Parquet schema (range request).

    \b
    Examples:
        portolan materialize cities
        portolan materialize boundaries --namespace public
        portolan materialize buildings --remote          # Remote Iceberg (no download)
        portolan materialize --all --namespace federated_wildfire  # Batch materialize
    """
    import json
    import uuid

    from iceberg_catalog import (
        create_table_metadata,
        generate_manifest_files,
        parquet_to_iceberg_table,
    )
    from portolan_resource import IcebergAsset, load_resource, save_resource
    from schemas import validate_resource

    catalog = get_catalog(ctx)

    # Handle --all flag for batch operations
    if all_resources:
        namespace_dir = catalog.path / "resources" / namespace
        if not namespace_dir.exists():
            raise click.ClickException(f"Namespace not found: {namespace}")

        # Find all CACHED resources
        resource_files = list(namespace_dir.glob("*.json"))
        if not resource_files:
            click.echo(f"No resources found in namespace: {namespace}")
            return

        cached_resources = []
        for rf in resource_files:
            res = load_resource(rf)
            if res.state == "cached" or (force and res.state == "materialized"):
                cached_resources.append(rf.stem)

        if not cached_resources:
            click.echo(f"No CACHED resources to materialize in namespace: {namespace}")
            return

        click.echo(f"Batch materializing {len(cached_resources)} resources in {namespace}...")
        click.echo()

        success = 0
        failed = 0
        for res_name in cached_resources:
            try:
                # Recursively invoke materialize for each resource
                ctx.invoke(materialize, resource_name=res_name, namespace=namespace,
                          all_resources=False, remote=False, force=force, verbose=verbose)
                success += 1
            except click.ClickException as e:
                click.echo(click.style(f"  Failed: {res_name} - {e.message}", fg="red"))
                failed += 1
            click.echo()

        click.echo(f"Batch materialize complete: {success} succeeded, {failed} failed")
        return

    # Single resource mode
    if not resource_name:
        raise click.ClickException("Resource name required (or use --all)")

    # Load resource
    resource_path = catalog.path / "resources" / namespace / f"{resource_name}.json"
    if not resource_path.exists():
        raise click.ClickException(f"Resource not found: {resource_name} in namespace {namespace}")

    resource = load_resource(resource_path)

    if resource.state == "materialized" and not force:
        if resource.kind == "vector":
            click.echo("Vector resource already has Iceberg metadata (auto-created during snapshot).")
            click.echo("Use --force to regenerate.")
        else:
            click.echo("Resource is already materialized. Use --force to re-materialize.")
        return

    # --remote: Create Iceberg metadata pointing to remote data (no download)
    if remote:
        if resource.state != "external" and not force:
            raise click.ClickException(
                "Resource is not EXTERNAL. Use --remote only with registered (not cached) resources."
            )

        if not resource.origin or not resource.origin.url:
            raise click.ClickException("Resource has no origin URL - cannot create remote Iceberg metadata.")

        remote_url = resource.origin.url

        click.echo(f"Creating remote Iceberg metadata for {resource_name}...")
        click.echo(f"  Remote URL: {remote_url}")

        if verbose:
            click.echo("  Reading Parquet schema from remote (range request only)...")

        # Read schema from remote Parquet file without downloading
        import pyarrow.parquet as pq

        try:
            remote_pf = _open_remote_parquet(remote_url)
        except Exception as e:
            raise click.ClickException(f"Failed to read remote Parquet schema: {e}")

        arrow_schema = remote_pf.schema_arrow
        num_rows = remote_pf.metadata.num_rows

        # Get file size from remote
        try:
            file_size = _get_remote_file_size(remote_url)
        except Exception:
            file_size = 0  # Fallback if we can't determine size

        if verbose:
            click.echo(f"  Schema: {len(arrow_schema)} fields")
            click.echo(f"  Rows: {num_rows}")
            click.echo(f"  Size: {file_size / 1024 / 1024:.1f} MB")

        # Create Iceberg table from remote schema
        from iceberg_catalog import IcebergTable, _arrow_schema_to_iceberg

        iceberg_schema = _arrow_schema_to_iceberg(arrow_schema)
        table = IcebergTable(
            name=resource_name,
            parquet_path=remote_url,
            schema=iceberg_schema,
            arrow_schema=arrow_schema,
            num_rows=num_rows,
            file_size_bytes=file_size,
        )

        # Generate metadata directory
        metadata_dir = catalog.path / "data" / namespace / resource_name / "metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)

        table_uuid = str(uuid.uuid4())
        data_base_url = f"file://{catalog.path.absolute()}"
        table_path = f"{namespace}/{resource_name}"

        # Data file path points to the REMOTE URL
        generate_manifest_files(
            table=table,
            data_base_url=data_base_url,
            metadata_dir=metadata_dir,
            arrow_schema=arrow_schema,
            snapshot_id=1,
            sequence_number=1,
            table_path=table_path,
            data_file_path=remote_url,
        )

        metadata = create_table_metadata(table, data_base_url, table_uuid, table_path=table_path)
        metadata_path = metadata_dir / "v1.metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        # Update resource with Iceberg asset (no snapshot asset - data stays remote)
        resource.assets.iceberg = IcebergAsset(
            metadata=str(metadata_path.relative_to(catalog.path)),
        )
        resource.updated_at = datetime.now(timezone.utc).isoformat()

        # Validate before saving
        errors = validate_resource(resource.to_dict())
        if errors:
            click.echo(click.style("Validation errors:", fg="red"))
            for error in errors:
                click.echo(f"  - {error}")
            raise click.ClickException("Resource validation failed after remote materialize")

        save_resource(resource, resource_path)

        click.echo(f"Remote Iceberg metadata created: {metadata_path}")
        click.echo(f"  State: {resource.state.upper()}")
        click.echo(f"  Data: stays at {remote_url} (not downloaded)")
        click.echo()
        click.echo("Query with DuckDB:")
        click.echo(f"  duckdb -c \"SELECT * FROM iceberg_scan('{metadata_path}')\"")
        return

    # Standard materialize (from cached snapshot)
    if resource.state == "external":
        raise click.ClickException(
            f"Resource must be cached first. Run: portolan snapshot {resource_name} --namespace {namespace}\n"
            f"Or use --remote to create Iceberg metadata without downloading."
        )

    if not resource.assets.snapshot:
        raise click.ClickException("Resource has no snapshot - cannot materialize.")

    snapshot_path = catalog.path / resource.assets.snapshot.href

    if not snapshot_path.exists():
        raise click.ClickException(f"Snapshot not found: {snapshot_path}")

    click.echo(f"Materializing {resource_name}...")

    # Lightweight Iceberg: no Parquet rewrite needed
    # We use schema.name-mapping.default property for column matching by name

    # Create Iceberg table
    if verbose:
        click.echo("  Creating Iceberg table metadata...")
    table = parquet_to_iceberg_table(str(snapshot_path), table_name=resource_name)

    # Generate metadata directory
    metadata_dir = catalog.path / "data" / namespace / resource_name / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)

    # Generate Iceberg metadata
    table_uuid = str(uuid.uuid4())
    data_base_url = f"file://{catalog.path.absolute()}"

    # Table path includes namespace
    table_path = f"{namespace}/{resource_name}"

    # Generate manifest files
    if verbose:
        click.echo("  Generating manifest files...")
    # Use actual snapshot path for data file
    snapshot_file_url = f"file://{snapshot_path.absolute()}"
    generate_manifest_files(
        table=table,
        data_base_url=data_base_url,
        metadata_dir=metadata_dir,
        arrow_schema=table.arrow_schema,
        snapshot_id=1,
        sequence_number=1,
        table_path=table_path,
        data_file_path=snapshot_file_url,
    )

    # Create table metadata
    metadata = create_table_metadata(table, data_base_url, table_uuid, table_path=table_path)

    metadata_path = metadata_dir / "v1.metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(metadata, f, indent=2)

    # Update resource
    resource.assets.iceberg = IcebergAsset(
        metadata=str(metadata_path.relative_to(catalog.path)),
    )
    resource.updated_at = datetime.now(timezone.utc).isoformat()

    # Validate before saving
    errors = validate_resource(resource.to_dict())
    if errors:
        click.echo(click.style("Validation errors:", fg="red"))
        for error in errors:
            click.echo(f"  - {error}")
        raise click.ClickException("Resource validation failed after materialize")

    save_resource(resource, resource_path)

    click.echo(f"Materialized: {metadata_path}")
    click.echo(f"  State: {resource.state.upper()}")
    click.echo()
    click.echo("Query with DuckDB:")
    click.echo(f"  duckdb -c \"SELECT * FROM iceberg_scan('{metadata_path}')\"")


@cli.command("add")
@click.argument("source", type=click.Path(exists=True))
@click.option("--name", "-n", help="Resource name (default: filename)")
@click.option("--namespace", "-ns", default="default", help="Namespace")
@click.option("--title", help="Human-readable title")
@click.option("--description", help="Description")
@click.option("--public", is_flag=True, help="Make public (sets namespace to 'public')")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def add_resource(ctx, source: str, name: str | None, namespace: str,
                 title: str | None, description: str | None, public: bool,
                 verbose: bool):
    """
    Add a resource (convenience: register + snapshot + materialize).

    This is the quickest way to add a local file to the catalog.

    \b
    Examples:
        portolan add /path/to/data.parquet --public
        portolan add countries.geojson --name world-countries --title "World Countries"
    """
    if public:
        namespace = "public"

    source_path = Path(source).resolve()

    # Derive name
    if not name:
        name = source_path.stem

    click.echo(f"Adding resource: {name}")
    click.echo()

    # Step 1: Register
    ctx.invoke(register, origin_type="file", url=str(source_path), name=name,
               namespace=namespace, title=title, description=description,
               verbose=verbose)

    # Step 2: Snapshot
    ctx.invoke(snapshot, resource_name=name, namespace=namespace, verbose=verbose)

    # Step 3: Materialize (will be no-op for vectors since snapshot already did it)
    ctx.invoke(materialize, resource_name=name, namespace=namespace, remote=False, verbose=verbose)

    click.echo()
    click.echo(click.style("Resource added successfully!", fg="green"))
    click.echo()
    click.echo("Run 'portolan sync' to push to remote storage.")




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

    \b
    Examples:
        portolan dataset add countries.parquet --public --title "World Countries"
        portolan dataset add imagery.parquet -c imagery --tenant acme
    """
    from iceberg_catalog import extract_parquet_metadata, generate_sdi_catalog

    catalog = get_catalog(ctx)
    file_path = Path(file).resolve()

    # Determine dataset ID
    if dataset_id is None:
        dataset_id = file_path.stem

    # Sanitize dataset ID
    dataset_id = dataset_id.lower().replace(" ", "_").replace("-", "_")
    dataset_id = "".join(c for c in dataset_id if c.isalnum() or c == "_")

    # Determine visibility and path
    visibility = "public" if is_public else "private"
    if visibility == "public":
        base_path = f"public/{collection}"
    else:
        base_path = f"private/{tenant}/{collection}"

    # For local catalog, use relative path
    base_url = f"./{base_path}"

    # Extract metadata (auto-detects Raquet vs GeoParquet)
    click.echo(f"Analyzing {file_path.name}...")
    metadata = extract_parquet_metadata(str(file_path))
    file_type = metadata.get("type", "geoparquet")
    format_name = metadata.get("format_name", "Parquet")
    spatial_representation = metadata.get("spatial_representation", "vector")
    raquet_info = metadata.get("raquet_info", {})
    geoparquet_info = metadata.get("geoparquet_info", {})
    stac_info = metadata.get("stac_info", {})

    # Use bounds from metadata if available
    bounds = metadata.get("bounds", stac_info.get("bbox", []))
    if bounds:
        stac_info["bbox"] = bounds

    collections_config = [{
        "name": collection,
        "title": title or f"{collection.title()} Collection",
        "items": [{
            "id": dataset_id,
            "title": title or dataset_id,
            "asset_path": str(file_path),
            "stac_info": stac_info,
            "iso_info": {
                "abstract": description or f"Dataset: {dataset_id}",
                "topic_category": topic,
                "format_name": format_name,
                "spatial_representation": spatial_representation,
                "license": license_,
            },
            "raquet_info": raquet_info if file_type == "raquet" else {},
            "geoparquet_info": geoparquet_info if file_type == "geoparquet" else {},
        }]
    }]

    # Generate catalog in the local .portolan directory
    output_dir = catalog.path / base_path
    output_dir.mkdir(parents=True, exist_ok=True)

    generate_sdi_catalog(
        collections=collections_config,
        output_dir=str(output_dir),
        data_base_url=base_url,
        verbose=verbose,
    )

    # Create resource entry for manifest-based tracking
    namespace = collection
    resources_dir = catalog.path / "resources" / namespace
    resources_dir.mkdir(parents=True, exist_ok=True)

    # Build spatial extent from bounds
    spatial_extent = None
    if bounds and len(bounds) >= 4:
        spatial_extent = {
            "west": bounds[0],
            "south": bounds[1],
            "east": bounds[2],
            "north": bounds[3],
        }

    resource = {
        "name": dataset_id,
        "type": "managed",
        "format": file_type,
        "title": title or dataset_id,
        "abstract": description or f"Dataset: {dataset_id}",
        "origin": "portolan",
        "spatial_extent": spatial_extent,
        "crs": "EPSG:4326",
        "assets": {
            "data": {
                "href": f"data/{namespace}/{dataset_id}/{dataset_id}.parquet",
                "type": "application/vnd.apache.parquet",
                "title": f"{format_name} file",
            }
        },
        "properties": metadata.get("properties", {}),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    resource_path = resources_dir / f"{dataset_id}.json"
    with open(resource_path, "w") as f:
        json.dump(resource, f, indent=2)

    if verbose:
        click.echo(f"Created resource: {resource_path}")

    # Update outputs if enabled
    from output_generators import update_all_outputs
    update_all_outputs(catalog, resource, namespace, verbose=verbose)

    click.echo()
    click.echo(click.style("Dataset added successfully!", fg="green"))
    click.echo(f"  ID: {dataset_id}")
    click.echo(f"  Type: {format_name}")
    click.echo(f"  Visibility: {visibility}")
    click.echo(f"  Location: {output_dir}")

    if not is_public:
        click.echo("\n  Note: Private datasets require authentication to access.")

    click.echo("\nRun 'portolan sync' to push to remote storage.")


@dataset.command("list")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed information")
@click.pass_context
def dataset_list(ctx, verbose: bool):
    """List datasets in the local catalog."""
    catalog = get_catalog(ctx)

    # Find all metadata files
    found_any = False

    for visibility in ["public", "private"]:
        vis_dir = catalog.path / visibility
        if not vis_dir.exists():
            continue

        datasets = []
        for metadata_file in vis_dir.rglob("v1.metadata.json"):
            # Extract collection and dataset info from path
            rel_path = metadata_file.relative_to(vis_dir)
            parts = list(rel_path.parts)

            # Try to find collection name
            if "data" in parts:
                idx = parts.index("data")
                collection = parts[idx + 1] if idx + 1 < len(parts) else "unknown"
                dataset_name = parts[idx + 2] if idx + 2 < len(parts) else "unknown"
            else:
                collection = parts[0] if parts else "unknown"
                dataset_name = parts[1] if len(parts) > 1 else "unknown"

            datasets.append({
                "collection": collection,
                "name": dataset_name,
                "path": str(rel_path),
            })

        if datasets:
            found_any = True
            click.echo(click.style(f"\n{visibility.title()} datasets:", bold=True))
            click.echo("-" * 40)

            for ds in datasets:
                if verbose:
                    click.echo(f"  {ds['collection']}/{ds['name']}")
                    click.echo(f"    Path: {ds['path']}")
                else:
                    click.echo(f"  {ds['collection']}/{ds['name']}")

    if not found_any:
        click.echo("No datasets found. Add one with:")
        click.echo("  portolan dataset add <file.parquet> --public")


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


# ============== CATALOG SOURCE FEDERATION ==============


@cli.group("catalog")
def catalog_cmd():
    """Manage federated catalog sources."""
    pass


@catalog_cmd.command("add")
@click.argument("url")
@click.option("--name", "-n", help="Catalog name (default: derived from URL)")
@click.option("--type", "catalog_type", type=click.Choice(["stac", "arcgis", "wfs", "portolan"]),
              help="Catalog type (auto-detected if not specified)")
@click.option("--collections", "-c", multiple=True, help="Filter to specific collections (STAC only)")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def catalog_add(ctx, url: str, name: str | None, catalog_type: str | None,
                collections: tuple, verbose: bool):
    """Register an upstream catalog for federation.

    Registers a catalog URL that can be synced to import resources.

    \b
    Examples:
        portolan catalog add https://earth-search.aws.element84.com/v1 --name earth-search
        portolan catalog add https://services.arcgis.com/... --name city-gis --type arcgis
        portolan catalog add https://example.com/stac -c sentinel-2-l2a -c landsat
    """
    from catalog_sources import CatalogSource, CatalogSourceStore

    catalog = get_catalog(ctx)
    store = CatalogSourceStore(catalog.path)

    # Auto-detect catalog type if not specified
    if not catalog_type:
        if "stac" in url.lower() or "element84" in url.lower() or "earth-search" in url.lower():
            catalog_type = "stac"
        elif "arcgis" in url.lower():
            catalog_type = "arcgis"
        elif "wfs" in url.lower():
            catalog_type = "wfs"
        else:
            catalog_type = "stac"  # Default to STAC
            click.echo(f"Auto-detected catalog type: {catalog_type}")

    # Derive name from URL if not provided
    if not name:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host_parts = parsed.netloc.split(".")
        name = host_parts[0] if host_parts else "catalog"
        # Sanitize
        name = name.lower().replace("-", "_")
        name = "".join(c for c in name if c.isalnum() or c == "_")

    # Check if already exists
    existing = store.get_source(name)
    if existing:
        click.echo(f"Catalog source '{name}' already exists.")
        click.echo(f"  URL: {existing.url}")
        click.echo("Use a different --name or remove the existing one first.")
        return

    # Create catalog source
    filters = {}
    if collections:
        filters["collections"] = list(collections)

    source = CatalogSource(
        name=name,
        type=catalog_type,
        url=url,
        filters=filters,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    store.add_source(source)

    click.echo(f"Registered catalog source: {name}")
    click.echo(f"  Type: {catalog_type}")
    click.echo(f"  URL: {url}")
    if filters:
        click.echo(f"  Filters: {filters}")
    click.echo()
    click.echo(f"Next: portolan catalog sync {name}")


@catalog_cmd.command("list")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed information")
@click.pass_context
def catalog_list(ctx, verbose: bool):
    """List registered catalog sources."""
    from catalog_sources import CatalogSourceStore

    catalog = get_catalog(ctx)
    store = CatalogSourceStore(catalog.path)
    sources = store.list_sources()

    if not sources:
        click.echo("No catalog sources registered.")
        click.echo("Add one with: portolan catalog add <url> --name <name>")
        return

    click.echo(f"Registered catalog sources ({len(sources)}):")
    click.echo()

    for source in sources:
        if source.last_sync:
            sync_info = f"last sync: {source.last_sync[:10]}"
        else:
            sync_info = "never synced"

        click.echo(f"  {source.name} ({source.type}) - {sync_info}")

        if verbose:
            click.echo(f"    URL: {source.url}")
            if source.filters:
                click.echo(f"    Filters: {source.filters}")
            if source.sync_hash:
                click.echo(f"    Sync hash: {source.sync_hash}")


@catalog_cmd.command("sync")
@click.argument("name", required=False)
@click.option("--max-items", type=int, default=100, help="Maximum items to sync (0 = all)")
@click.option("--dry-run", is_flag=True, help="Show what would be synced without saving")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def catalog_sync(ctx, name: str | None, max_items: int, dry_run: bool, verbose: bool):
    """Sync resources from upstream catalogs.

    Syncs all catalogs if no name specified, or just the named catalog.

    \b
    Examples:
        portolan catalog sync                    # Sync all catalogs
        portolan catalog sync earth-search       # Sync specific catalog
        portolan catalog sync --dry-run          # Preview changes
    """
    from catalog_sources import CatalogSourceStore, sync_stac_catalog

    catalog = get_catalog(ctx)
    store = CatalogSourceStore(catalog.path)
    resources_dir = catalog.path / "resources"

    # Get sources to sync
    if name:
        source = store.get_source(name)
        if not source:
            raise click.ClickException(f"Catalog source not found: {name}")
        sources = [source]
    else:
        sources = store.list_sources()
        if not sources:
            click.echo("No catalog sources registered.")
            click.echo("Add one with: portolan catalog add <url> --name <name>")
            return

    for source in sources:
        click.echo(f"Syncing {source.name} ({source.type})...")

        if source.type == "stac":
            results = sync_stac_catalog(
                source=source,
                resources_dir=resources_dir,
                max_items=max_items,
                verbose=verbose,
                dry_run=dry_run,
            )

            if results["errors"]:
                click.echo(click.style(f"  Errors: {len(results['errors'])}", fg="yellow"))
                if verbose:
                    for error in results["errors"][:5]:
                        click.echo(f"    - {error}")

            if dry_run:
                click.echo(f"  Would add: {len(results['added'])}")
                if verbose and results["added"]:
                    for name_item in results["added"][:10]:
                        click.echo(f"    + {name_item}")
                    if len(results["added"]) > 10:
                        click.echo(f"    ... and {len(results['added']) - 10} more")
            else:
                if results["unchanged"] and not results["added"] and not results["updated"]:
                    click.echo(f"  No changes ({len(results['unchanged'])} items unchanged)")
                else:
                    click.echo(f"  Added: {len(results['added'])}")
                    click.echo(f"  Updated: {len(results['updated'])}")

                # Update sync state
                if results["new_hash"]:
                    store.update_sync_state(source.name, results["new_hash"])

        elif source.type == "arcgis":
            from catalog_sources import sync_arcgis_server

            results = sync_arcgis_server(
                source=source,
                resources_dir=resources_dir,
                verbose=verbose,
                dry_run=dry_run,
            )

            if results["added"]:
                click.echo(f"  Added: {len(results['added'])} resources")
                if verbose:
                    for name in results["added"]:
                        click.echo(f"    + {name}")
            if results["updated"]:
                click.echo(f"  Updated: {len(results['updated'])} resources")
            if results["unchanged"]:
                click.echo(f"  Unchanged: {len(results['unchanged'])} resources")
            if results["errors"]:
                click.echo(click.style(f"  Errors: {len(results['errors'])}", fg="yellow"))
                for error in results["errors"]:
                    click.echo(f"    - {error}")

            if not dry_run and results["new_hash"]:
                if results["added"] or results["updated"]:
                    store.update_sync_state(source.name, results["new_hash"])

        elif source.type == "wfs":
            click.echo("  WFS catalog sync not yet implemented")

        else:
            click.echo(f"  Unknown catalog type: {source.type}")

    if not dry_run:
        click.echo()
        click.echo(click.style("Sync complete!", fg="green"))


@catalog_cmd.command("remove")
@click.argument("name")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation")
@click.pass_context
def catalog_remove(ctx, name: str, force: bool):
    """Remove a registered catalog source."""
    from catalog_sources import CatalogSourceStore

    catalog = get_catalog(ctx)
    store = CatalogSourceStore(catalog.path)

    source = store.get_source(name)
    if not source:
        raise click.ClickException(f"Catalog source not found: {name}")

    if not force:
        click.confirm(f"Remove catalog source '{name}'?", abort=True)

    if store.remove_source(name):
        click.echo(f"Removed catalog source: {name}")
    else:
        raise click.ClickException(f"Failed to remove catalog source: {name}")


# ============== CORS HELPER ==============

def setup_cors_for_url(url: str):
    """Configure CORS for a storage URL to enable browser access."""
    import subprocess
    import tempfile

    if url.startswith("gs://"):
        # Google Cloud Storage
        bucket = url[5:].split("/")[0]

        cors_config = [
            {
                "origin": ["*"],
                "method": ["GET", "HEAD", "OPTIONS"],
                "responseHeader": ["Content-Type", "Content-Length", "Content-Range", "Access-Control-Allow-Origin"],
                "maxAgeSeconds": 3600
            }
        ]

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(cors_config, f)
            cors_file = f.name

        try:
            subprocess.run(
                ["gsutil", "cors", "set", cors_file, f"gs://{bucket}"],
                capture_output=True,
                text=True,
                check=True
            )
        finally:
            Path(cors_file).unlink()

    elif url.startswith("s3://"):
        # Amazon S3
        bucket = url[5:].split("/")[0]

        cors_config = {
            "CORSRules": [
                {
                    "AllowedOrigins": ["*"],
                    "AllowedMethods": ["GET", "HEAD"],
                    "AllowedHeaders": ["*"],
                    "MaxAgeSeconds": 3600
                }
            ]
        }

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(cors_config, f)
            cors_file = f.name

        try:
            subprocess.run(
                ["aws", "s3api", "put-bucket-cors", "--bucket", bucket, "--cors-configuration", f"file://{cors_file}"],
                capture_output=True,
                text=True,
                check=True
            )
        finally:
            Path(cors_file).unlink()

    elif url.startswith("az://"):
        # Azure Blob Storage - skip for now, needs account name
        pass

    # Local/file URLs don't need CORS


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
        # Check legacy remote config
        if catalog.default_remote and catalog.default_remote in catalog.remotes:
            state.remote_url = catalog.remotes[catalog.default_remote].url
            state.save(catalog.path / "state.json")
        else:
            raise click.ClickException(
                "No remote configured. Add one with:\n"
                "  portolan remote add origin gs://your-bucket/path"
            )

    store = get_remote_store(state.remote_url)
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

    # Upload changes
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
        click.echo()
        click.echo(click.style("Error: Remote changed during sync!", fg="red"))
        click.echo("Another process modified the catalog while we were uploading.")
        click.echo("Run 'portolan pull' to get latest changes, then try again.")
        raise click.ClickException("Sync aborted. Concurrent modification detected.")

    # Upload new manifest
    try:
        new_hash = store.put_manifest(new_manifest)
    except Exception as e:
        raise click.ClickException(f"Failed to upload manifest: {e}")

    # Update local state
    state.base_manifest_hash = new_hash
    state.save(catalog.path / "state.json")

    # Save new base manifest locally
    base_manifest_path = catalog.path / "base_manifest.json"
    base_manifest_path.write_text(new_manifest.to_json())

    # Setup CORS automatically for cloud storage
    if state.remote_url and (state.remote_url.startswith("gs://") or state.remote_url.startswith("s3://")):
        try:
            setup_cors_for_url(state.remote_url)
        except Exception:
            pass  # CORS setup is best-effort, don't fail sync

    click.echo()
    click.echo(click.style("Sync complete!", fg="green"))
    click.echo(f"  Uploaded: {uploaded}")
    click.echo(f"  Deleted: {deleted}")
    if errors:
        click.echo(click.style(f"  Errors: {errors}", fg="yellow"))
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
            store = get_remote_store(state.remote_url)
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
    for name, enabled in catalog.outputs.items():
        out_status = click.style("enabled", fg="green") if enabled else click.style("disabled", dim=True)
        click.echo(f"  {name}: {out_status}")




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
    store = get_remote_store(state.remote_url)
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

    # Fetch new manifest
    remote_manifest, remote_hash = store.get_manifest()
    if remote_manifest is None:
        raise click.ClickException("Could not fetch remote manifest")

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

    click.echo()
    click.echo(click.style("Pull complete!", fg="green"))
    click.echo(f"  Added: {added}")
    click.echo(f"  Updated: {updated}")
    click.echo(f"  Deleted: {deleted}")


# ============== IMPORT ==============

@cli.group(name="import")
def import_cmd():
    """Import datasets from external catalogs."""
    pass


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


def stac_item_to_resource(item: dict, item_url: str) -> dict:
    """Convert a STAC item to a Portolan resource entry."""
    # Extract bbox
    bbox = item.get("bbox", [])
    spatial_extent = None
    if len(bbox) >= 4:
        spatial_extent = {
            "west": bbox[0],
            "south": bbox[1],
            "east": bbox[2],
            "north": bbox[3],
        }

    # Extract temporal
    properties = item.get("properties", {})
    datetime_str = properties.get("datetime")
    start_datetime = properties.get("start_datetime")
    end_datetime = properties.get("end_datetime")

    temporal_extent = None
    if start_datetime and end_datetime:
        temporal_extent = {"start": start_datetime, "end": end_datetime}
    elif datetime_str:
        temporal_extent = {"start": datetime_str, "end": datetime_str}

    # Find the primary asset (prefer data assets, then the first one)
    assets = item.get("assets", {})
    primary_asset = None
    primary_asset_key = None

    # Priority order for asset keys
    priority_keys = ["data", "visual", "image", "default", "asset"]
    for key in priority_keys:
        if key in assets:
            primary_asset = assets[key]
            primary_asset_key = key
            break

    # Fall back to first asset
    if not primary_asset and assets:
        primary_asset_key = next(iter(assets))
        primary_asset = assets[primary_asset_key]

    if not primary_asset:
        return None

    asset_format = extract_asset_format(primary_asset)

    return {
        "name": item.get("id", "unknown"),
        "type": "external",
        "format": asset_format,
        "origin": primary_asset.get("href"),
        "title": properties.get("title") or item.get("id"),
        "abstract": properties.get("description", ""),
        "spatial_extent": spatial_extent,
        "temporal_extent": temporal_extent,
        "crs": "EPSG:4326",  # STAC items are typically in WGS84
        "stac_item_url": item_url,
        "stac_collection": item.get("collection"),
        "assets": {k: {"href": v.get("href"), "type": v.get("type")} for k, v in assets.items()},
        "properties": properties,
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
    from output_generators import regenerate_all_outputs

    catalog = get_catalog(ctx)

    # Show what will be rebuilt
    enabled = [k for k, v in catalog.outputs.items() if v]
    click.echo(f"Rebuilding: {', '.join(enabled)}")

    if outputs_only:
        click.echo("Skipping Iceberg rebuild (--outputs-only)")
        regenerate_all_outputs(catalog, verbose=verbose)
        click.echo(click.style("Outputs rebuilt!", fg="green"))
        return

    # Continue with full Iceberg rebuild...
    import pyarrow as pa
    import pyarrow.parquet as pq

    from iceberg_catalog import (
        IcebergTable,
        _arrow_schema_to_iceberg,
        add_iceberg_field_ids,
        generate_static_catalog,
    )

    catalog = get_catalog(ctx)
    resources_dir = catalog.path / "resources"

    if not resources_dir.exists():
        click.echo("No resources found. Import some first with:")
        click.echo("  portolan import stac <url>")
        return

    # Collect all resources
    resources = []
    for namespace_dir in resources_dir.iterdir():
        if not namespace_dir.is_dir():
            continue

        namespace = namespace_dir.name

        for resource_file in namespace_dir.glob("*.json"):
            if resource_file.name.startswith("_"):
                continue

            try:
                with open(resource_file) as f:
                    resource = json.load(f)
                resource["namespace"] = namespace
                resources.append(resource)

                if verbose:
                    click.echo(f"  {namespace}/{resource.get('name', 'unknown')}")
            except Exception as e:
                if verbose:
                    click.echo(f"  Error reading {resource_file}: {e}", err=True)

    if not resources:
        click.echo("No resources found.")
        return

    click.echo(f"Found {len(resources)} resources")

    # Flatten resources to tabular format
    rows = []
    for r in resources:
        spatial = r.get("spatial_extent", {}) or {}
        temporal = r.get("temporal_extent", {}) or {}

        row = {
            "namespace": r.get("namespace", ""),
            "name": r.get("name", ""),
            "type": r.get("type", "external"),
            "format": r.get("format", "unknown"),
            "origin": r.get("origin", ""),
            "title": r.get("title", ""),
            "abstract": r.get("abstract", ""),
            "bbox_west": spatial.get("west"),
            "bbox_south": spatial.get("south"),
            "bbox_east": spatial.get("east"),
            "bbox_north": spatial.get("north"),
            "crs": r.get("crs", ""),
            "temporal_start": temporal.get("start", ""),
            "temporal_end": temporal.get("end", ""),
            "stac_collection": r.get("stac_collection", ""),
            "stac_item_url": r.get("stac_item_url", ""),
            "created_at": r.get("created_at", ""),
            "updated_at": r.get("updated_at", ""),
            # Store complex fields as JSON strings
            "assets": json.dumps(r.get("assets", {})),
            "properties": json.dumps(r.get("properties", {})),
        }
        rows.append(row)

    # Create PyArrow table
    pa_table = pa.Table.from_pylist(rows)

    # Create data directory and write Parquet file
    data_dir = catalog.path / "data" / "resources"
    data_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = data_dir / "resources.parquet"
    pq.write_table(pa_table, parquet_path, compression="zstd")

    # Add Iceberg field IDs to the Parquet file
    click.echo("Adding Iceberg field IDs...")
    add_iceberg_field_ids(parquet_path)

    # Re-read to get updated schema with field IDs
    pa_table = pq.read_table(parquet_path)

    # Create IcebergTable object for the resources registry
    iceberg_table = IcebergTable(
        name="resources",
        parquet_path="resources/resources.parquet",
        schema=_arrow_schema_to_iceberg(pa_table.schema),
        arrow_schema=pa_table.schema,
        num_rows=len(rows),
        file_size_bytes=parquet_path.stat().st_size,
    )

    # Collect all tables to register (resources + direct data tables)
    all_tables = [iceberg_table]

    # Register GeoParquet and Raquet files as direct Iceberg tables
    click.echo("Registering direct data tables...")
    direct_table_formats = {"geoparquet", "raquet"}

    for r in resources:
        fmt = r.get("format", "")
        rtype = r.get("type", "external")
        name = r.get("name", "")
        assets = r.get("assets", {})

        if fmt not in direct_table_formats:
            continue

        # Get the data URL
        data_asset = assets.get("data", {}) or assets.get("cache", {})
        data_url = data_asset.get("href", "")

        if not data_url:
            if verbose:
                click.echo(f"  Skipping {name}: no data URL")
            continue

        # For managed/cached data, copy to the catalog
        # For external with HTTP/GCS URLs, download
        try:
            table_data_dir = catalog.path / "data" / name
            table_data_dir.mkdir(parents=True, exist_ok=True)
            table_parquet_path = table_data_dir / f"{name}.parquet"

            if rtype == "managed" and data_url.startswith("gs://"):
                # Will be uploaded later, create placeholder from local file if exists
                local_file = catalog.path / "sample_cities.parquet" if "cities" in name else None
                if local_file and local_file.exists():
                    shutil.copy(local_file, table_parquet_path)
                else:
                    if verbose:
                        click.echo(f"  Skipping {name}: managed file not found locally")
                    continue
            elif data_url.startswith(("http://", "https://", "gs://")):
                # Download the file
                if verbose:
                    click.echo(f"  Downloading {name}...")

                import httpx
                if data_url.startswith("gs://"):
                    # Convert gs:// to https://
                    https_url = data_url.replace("gs://", "https://storage.googleapis.com/")
                else:
                    https_url = data_url

                response = httpx.get(https_url, follow_redirects=True, timeout=60)
                response.raise_for_status()

                with open(table_parquet_path, "wb") as f:
                    f.write(response.content)
            else:
                if verbose:
                    click.echo(f"  Skipping {name}: unsupported URL scheme")
                continue

            # Add Iceberg field IDs
            add_iceberg_field_ids(table_parquet_path)

            # Read schema
            table_pa = pq.read_table(table_parquet_path)

            # Create IcebergTable
            direct_table = IcebergTable(
                name=name,
                parquet_path=f"{name}/{name}.parquet",
                schema=_arrow_schema_to_iceberg(table_pa.schema),
                arrow_schema=table_pa.schema,
                num_rows=table_pa.num_rows,
                file_size_bytes=table_parquet_path.stat().st_size,
            )
            all_tables.append(direct_table)

            if verbose:
                click.echo(f"  Registered {name} ({fmt}, {table_pa.num_rows} rows)")

        except Exception as e:
            if verbose:
                click.echo(f"  Error registering {name}: {e}", err=True)
            continue

    # Determine base URL
    if base_url:
        data_base_url = base_url.rstrip("/")
    else:
        # Default to local path for testing
        data_base_url = f"file://{catalog.path.absolute()}"

    # Generate full Iceberg catalog
    click.echo(f"Generating Iceberg catalog with {len(all_tables)} tables...")
    generate_static_catalog(
        tables=all_tables,
        output_dir=str(catalog.path),
        namespace="portolan",
        prefix="catalog",
        data_base_url=data_base_url,
        verbose=verbose,
    )

    # Also keep a simple catalog.parquet at root for easy access
    simple_parquet = catalog.path / "catalog.parquet"
    shutil.copy(parquet_path, simple_parquet)

    click.echo()
    click.echo(click.style("Built Iceberg catalog!", fg="green"))
    click.echo(f"  Resources: {len(resources)}")
    click.echo(f"  Direct tables: {len(all_tables) - 1}")  # Minus the resources table
    click.echo(f"  Location: {catalog.path}")

    # Regenerate all enabled outputs (STAC, ISO, etc.)
    regenerate_all_outputs(catalog, verbose=verbose)

    # Show format breakdown
    format_counts = {}
    for r in resources:
        fmt = r.get("format", "unknown")
        format_counts[fmt] = format_counts.get(fmt, 0) + 1

    click.echo("\nFormats:")
    for fmt, count in sorted(format_counts.items()):
        click.echo(f"  {fmt}: {count}")

    # Show registered direct tables
    if len(all_tables) > 1:
        click.echo("\nDirect tables (queryable as catalog.portolan.<name>):")
        for t in all_tables:
            if t.name != "resources":
                click.echo(f"  - {t.name}")

    click.echo("\nQuery with DuckDB (simple Parquet):")
    click.echo(f"  duckdb -c \"SELECT name, format, title FROM '{simple_parquet}'\"")

    click.echo("\nQuery with DuckDB (Iceberg):")
    metadata_path = catalog.path / "data" / "resources" / "metadata" / "v1.metadata.json"
    click.echo(f"  duckdb -c \"SELECT * FROM iceberg_scan('{metadata_path}')\"")

    if base_url:
        # Convert gs:// to https:// for public access
        https_url = base_url.replace("gs://", "https://storage.googleapis.com/")

        click.echo(f"\nAfter uploading with: .portolan/upload_static_catalog.sh {base_url}")
        click.echo("\nQuery with DuckDB (iceberg_scan):")
        click.echo(f"  duckdb -c \"SELECT * FROM iceberg_scan('{https_url}/data/resources/metadata/v1.metadata.json')\"")
        click.echo("\nQuery with DuckDB (REST catalog ATTACH):")
        click.echo("  ATTACH '' AS catalog (")
        click.echo("      TYPE iceberg,")
        click.echo(f"      ENDPOINT '{https_url}',")
        click.echo("      AUTHORIZATION_TYPE 'none'")
        click.echo("  );")
        click.echo("  -- Discovery table:")
        click.echo("  SELECT * FROM catalog.portolan.resources;")
        if len(all_tables) > 1:
            direct_names = [t.name for t in all_tables if t.name != "resources"]
            click.echo("  -- Direct data tables:")
            for tname in direct_names[:3]:  # Show first 3
                click.echo(f"  SELECT * FROM catalog.portolan.{tname} LIMIT 10;")
        click.echo("\nBigQuery (BigLake Iceberg table):")
        click.echo(f"  bq mk --table --external_table_definition=ICEBERG={base_url}/data/resources/metadata/v1.metadata.json dataset.resources")


@import_cmd.command("stac")
@click.argument("url")
@click.option("--namespace", "-n", default="stac", help="Namespace for imported items")
@click.option("--max-items", type=int, default=100, help="Maximum items to import (0 = all)")
@click.option("--collections", "-c", multiple=True, help="Only import specific collections")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.option("--dry-run", is_flag=True, help="Show what would be imported without saving")
@click.pass_context
def import_stac(ctx, url: str, namespace: str, max_items: int, collections: tuple, verbose: bool, dry_run: bool):
    """Import datasets from a STAC catalog.

    Crawls a STAC catalog and registers items as external resources.
    Supports STAC Catalogs, Collections, and Items.

    \b
    Examples:
        portolan import stac https://earth-search.aws.element84.com/v1
        portolan import stac https://example.com/stac/catalog.json --max-items 50
        portolan import stac https://example.com/stac/catalog.json -c sentinel-2
    """
    catalog = get_catalog(ctx)

    click.echo(f"Fetching STAC catalog from {url}...")

    try:
        root = fetch_json(url)
    except Exception as e:
        raise click.ClickException(f"Failed to fetch STAC catalog: {e}")

    stac_type = root.get("type", "Catalog")
    click.echo(f"Found STAC {stac_type}: {root.get('title', root.get('id', 'Unknown'))}")

    # Collect items to import
    items_to_import = []
    collections_found = set()

    def process_item(item: dict, item_url: str):
        """Process a single STAC item."""
        resource = stac_item_to_resource(item, item_url)
        if resource:
            items_to_import.append(resource)
            if verbose:
                click.echo(f"  Found item: {resource['name']} ({resource['format']})")

    def crawl_catalog(catalog_url: str, catalog_obj: dict, depth: int = 0):
        """Recursively crawl a STAC catalog."""
        if max_items > 0 and len(items_to_import) >= max_items:
            return

        indent = "  " * depth

        # Process child catalogs
        child_links = get_stac_links(catalog_obj, "child")
        for link in child_links:
            if max_items > 0 and len(items_to_import) >= max_items:
                break

            child_url = resolve_url(catalog_url, link["href"])

            try:
                child = fetch_json(child_url)
                child_type = child.get("type", "Catalog")
                child_id = child.get("id", "unknown")

                # Check collection filter
                if collections and child_type == "Collection" and child_id not in collections:
                    if verbose:
                        click.echo(f"{indent}Skipping collection: {child_id}")
                    continue

                if child_type == "Collection":
                    collections_found.add(child_id)

                if verbose:
                    click.echo(f"{indent}Crawling {child_type}: {child.get('title', child_id)}")

                crawl_catalog(child_url, child, depth + 1)

            except Exception as e:
                if verbose:
                    click.echo(f"{indent}Error fetching {child_url}: {e}", err=True)

        # Process items in this catalog/collection
        item_links = get_stac_links(catalog_obj, "item")
        for link in item_links:
            if max_items > 0 and len(items_to_import) >= max_items:
                break

            item_url = resolve_url(catalog_url, link["href"])

            try:
                item = fetch_json(item_url)
                process_item(item, item_url)
            except Exception as e:
                if verbose:
                    click.echo(f"{indent}Error fetching item {item_url}: {e}", err=True)

        # Check for items link (STAC API style)
        items_links = get_stac_links(catalog_obj, "items")
        for link in items_links:
            if max_items > 0 and len(items_to_import) >= max_items:
                break

            items_url = resolve_url(catalog_url, link["href"])

            try:
                items_response = fetch_json(items_url)
                features = items_response.get("features", [])

                for item in features:
                    if max_items > 0 and len(items_to_import) >= max_items:
                        break
                    process_item(item, items_url)

            except Exception as e:
                if verbose:
                    click.echo(f"{indent}Error fetching items {items_url}: {e}", err=True)

    # Start crawling
    with click.progressbar(length=max_items or 100, label="Crawling catalog") as bar:
        crawl_catalog(url, root)
        bar.update(len(items_to_import))

    click.echo(f"\nFound {len(items_to_import)} items from {len(collections_found)} collections")

    if not items_to_import:
        click.echo("No items found to import.")
        return

    # Show format breakdown
    format_counts = {}
    for item in items_to_import:
        fmt = item.get("format", "unknown")
        format_counts[fmt] = format_counts.get(fmt, 0) + 1

    click.echo("\nFormats:")
    for fmt, count in sorted(format_counts.items()):
        click.echo(f"  {fmt}: {count}")

    if dry_run:
        click.echo("\nDry run - would import:")
        for item in items_to_import[:10]:
            click.echo(f"  {item['name']} ({item['format']}): {item.get('origin', 'N/A')[:60]}...")
        if len(items_to_import) > 10:
            click.echo(f"  ... and {len(items_to_import) - 10} more")
        return

    # Save resources to catalog
    click.echo(f"\nSaving to namespace '{namespace}'...")

    resources_dir = catalog.path / "resources" / namespace
    resources_dir.mkdir(parents=True, exist_ok=True)

    # Import output generators
    from output_generators import update_all_outputs

    # Save each resource as JSON and update outputs
    saved = 0
    for item in items_to_import:
        resource_file = resources_dir / f"{item['name']}.json"

        # Add timestamps
        item["created_at"] = datetime.now(timezone.utc).isoformat()
        item["updated_at"] = item["created_at"]

        with open(resource_file, "w") as f:
            json.dump(item, f, indent=2)

        # Update all enabled outputs (STAC, ISO, etc.)
        update_all_outputs(catalog, item, namespace, verbose=verbose)

        saved += 1

    # Save a summary/index file
    index = {
        "namespace": namespace,
        "source": url,
        "source_type": "stac",
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "total_items": len(items_to_import),
        "collections": list(collections_found),
        "formats": format_counts,
    }

    with open(resources_dir / "_index.json", "w") as f:
        json.dump(index, f, indent=2)

    # Show enabled outputs
    enabled = [k for k, v in catalog.outputs.items() if v and k != "iceberg"]

    click.echo()
    click.echo(click.style(f"Imported {saved} resources!", fg="green"))
    click.echo(f"  Location: {resources_dir}")
    if enabled:
        click.echo(f"  Also updated: {', '.join(enabled)}")
    click.echo("\nRun 'portolan sync' to push to remote storage.")


# ============== MAIN ==============

def main():
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
