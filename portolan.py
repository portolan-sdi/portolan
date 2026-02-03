#!/usr/bin/env python3
"""
Portolan CLI - Manage geospatial data infrastructure with cloud-native formats.

Local-first workflow:
    portolan init [path]                    # Initialize a local catalog
    portolan dataset add <file> [options]   # Add dataset to local catalog
    portolan dataset list                   # List local datasets
    portolan sync                           # Sync local catalog to remote storage

Remote configuration:
    portolan remote add <name> <url>        # Add a remote storage backend
    portolan remote list                    # List configured remotes
    portolan remote remove <name>           # Remove a remote

Supported storage backends (via obstore):
    - s3://bucket/path          (AWS S3)
    - gs://bucket/path          (Google Cloud Storage)
    - az://container/path       (Azure Blob Storage)
    - file:///local/path        (Local filesystem)
    - memory://                 (In-memory, for testing)
"""

from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click

# ============== CONFIGURATION ==============

DEFAULT_CATALOG_DIR = Path.cwd() / ".portolan"
GLOBAL_CONFIG_DIR = Path.home() / ".portolan"
GLOBAL_CONFIG_FILE = GLOBAL_CONFIG_DIR / "config.json"


@dataclass
class RemoteConfig:
    """Configuration for a remote storage backend."""
    name: str
    url: str  # e.g., s3://bucket/path, gs://bucket/path, file:///path
    options: dict = field(default_factory=dict)  # Backend-specific options (credentials, region, etc.)

    def to_dict(self) -> dict:
        return {"name": self.name, "url": self.url, "options": self.options}

    @classmethod
    def from_dict(cls, data: dict) -> "RemoteConfig":
        return cls(name=data["name"], url=data["url"], options=data.get("options", {}))


@dataclass
class CatalogConfig:
    """Configuration for a Portolan catalog."""
    path: Path
    default_remote: Optional[str] = None
    remotes: dict[str, RemoteConfig] = field(default_factory=dict)

    @property
    def config_file(self) -> Path:
        return self.path / "config.json"

    @property
    def data_dir(self) -> Path:
        return self.path / "data"

    @property
    def metadata_dir(self) -> Path:
        return self.path / "v1"

    def save(self):
        """Save catalog configuration."""
        self.path.mkdir(parents=True, exist_ok=True)
        data = {
            "default_remote": self.default_remote,
            "remotes": {name: r.to_dict() for name, r in self.remotes.items()},
        }
        with open(self.config_file, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: Path) -> "CatalogConfig":
        """Load catalog configuration from path."""
        config_file = path / "config.json"
        if config_file.exists():
            with open(config_file) as f:
                data = json.load(f)
            remotes = {
                name: RemoteConfig.from_dict(r)
                for name, r in data.get("remotes", {}).items()
            }
            return cls(
                path=path,
                default_remote=data.get("default_remote"),
                remotes=remotes,
            )
        return cls(path=path)

    def add_remote(self, name: str, url: str, options: dict | None = None, set_default: bool = False):
        """Add a remote storage backend."""
        self.remotes[name] = RemoteConfig(name=name, url=url, options=options or {})
        if set_default or not self.default_remote:
            self.default_remote = name
        self.save()

    def remove_remote(self, name: str):
        """Remove a remote storage backend."""
        if name in self.remotes:
            del self.remotes[name]
            if self.default_remote == name:
                self.default_remote = next(iter(self.remotes), None)
            self.save()


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


# ============== STORAGE ABSTRACTION (obstore) ==============

def get_store(url: str, options: dict | None = None):
    """Get an obstore store for the given URL."""
    import obstore
    from obstore.store import S3Store, GCSStore, AzureStore, LocalStore, MemoryStore

    options = options or {}

    if url.startswith("s3://"):
        # Parse s3://bucket/path
        parts = url[5:].split("/", 1)
        bucket = parts[0]
        prefix = parts[1] if len(parts) > 1 else ""

        store_options = {
            "bucket": bucket,
            "region": options.get("region", "us-east-1"),
            "skip_signature": options.get("anonymous", False),
        }

        # Add credentials if provided
        if "access_key_id" in options:
            store_options["access_key_id"] = options["access_key_id"]
        if "secret_access_key" in options:
            store_options["secret_access_key"] = options["secret_access_key"]
        if "endpoint" in options:
            store_options["endpoint"] = options["endpoint"]

        return S3Store(**store_options), prefix

    elif url.startswith("gs://"):
        parts = url[5:].split("/", 1)
        bucket = parts[0]
        prefix = parts[1] if len(parts) > 1 else ""
        return GCSStore(bucket=bucket), prefix

    elif url.startswith("az://"):
        parts = url[5:].split("/", 1)
        container = parts[0]
        prefix = parts[1] if len(parts) > 1 else ""
        account = options.get("account_name", "")
        return AzureStore(container=container, account=account), prefix

    elif url.startswith("file://"):
        path = url[7:]
        return LocalStore(prefix=path), ""

    elif url.startswith("memory://"):
        return MemoryStore(), ""

    else:
        raise ValueError(f"Unsupported storage URL: {url}")


async def upload_directory(store, prefix: str, local_dir: Path, verbose: bool = False):
    """Upload a local directory to remote storage."""
    import obstore

    for local_path in local_dir.rglob("*"):
        if local_path.is_file():
            relative = local_path.relative_to(local_dir)
            remote_path = f"{prefix}/{relative}" if prefix else str(relative)

            if verbose:
                click.echo(f"  Uploading {relative}...")

            with open(local_path, "rb") as f:
                data = f.read()

            await obstore.put_async(store, remote_path, data)


async def list_remote_files(store, prefix: str, pattern: str = "") -> list[str]:
    """List files in remote storage."""
    import obstore

    results = []
    async for item in obstore.list(store, prefix=prefix):
        path = item["path"]
        if not pattern or pattern in path:
            results.append(path)
    return results


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
@click.option("--remote", "-r", help="Remote storage URL (e.g., s3://bucket/path)")
@click.option("--name", "-n", default="origin", help="Name for the remote (default: origin)")
def init(path: str, remote: str | None, name: str):
    """Initialize a new Portolan catalog.

    Creates a .portolan directory in the specified PATH (default: current directory).

    \b
    Examples:
        portolan init                           # Initialize in current directory
        portolan init ./my-catalog              # Initialize in specific directory
        portolan init -r s3://my-bucket/data    # Initialize with S3 remote
        portolan init -r gs://my-bucket         # Initialize with GCS remote
    """
    catalog_path = Path(path).resolve() / ".portolan"

    if catalog_path.exists():
        click.echo(f"Catalog already exists at {catalog_path}")
        return

    # Create catalog structure
    catalog = CatalogConfig(path=catalog_path)
    catalog.path.mkdir(parents=True, exist_ok=True)
    catalog.data_dir.mkdir(exist_ok=True)
    catalog.metadata_dir.mkdir(exist_ok=True)

    # Add remote if provided
    if remote:
        catalog.add_remote(name, remote, set_default=True)
        click.echo(f"Added remote '{name}': {remote}")

    catalog.save()

    click.echo(f"Initialized Portolan catalog at {catalog_path}")
    click.echo()
    click.echo("Next steps:")
    click.echo("  portolan dataset add <file.parquet> --public")
    if not remote:
        click.echo("  portolan remote add origin s3://your-bucket/path")
    click.echo("  portolan sync")


# ============== REMOTE ==============

@cli.group()
def remote():
    """Manage remote storage backends."""
    pass


@remote.command("add")
@click.argument("name")
@click.argument("url")
@click.option("--access-key", envvar="AWS_ACCESS_KEY_ID", help="Access key for S3-compatible storage")
@click.option("--secret-key", envvar="AWS_SECRET_ACCESS_KEY", help="Secret key for S3-compatible storage")
@click.option("--endpoint", help="Custom endpoint URL (for MinIO, etc.)")
@click.option("--region", default="us-east-1", help="AWS region (default: us-east-1)")
@click.option("--anonymous", is_flag=True, help="Use anonymous access (no credentials)")
@click.option("--default", "set_default", is_flag=True, help="Set as default remote")
@click.pass_context
def remote_add(ctx, name: str, url: str, access_key: str | None, secret_key: str | None,
               endpoint: str | None, region: str, anonymous: bool, set_default: bool):
    """Add a remote storage backend.

    \b
    Supported URL formats:
        s3://bucket/path          AWS S3 or S3-compatible (MinIO, etc.)
        gs://bucket/path          Google Cloud Storage
        az://container/path       Azure Blob Storage
        file:///local/path        Local filesystem

    \b
    Examples:
        portolan remote add origin s3://my-bucket/portolan
        portolan remote add minio s3://warehouse --endpoint http://localhost:9000
        portolan remote add gcs gs://my-bucket/data
        portolan remote add local file:///var/data/portolan
    """
    catalog = get_catalog(ctx)

    options = {"region": region}
    if access_key:
        options["access_key_id"] = access_key
    if secret_key:
        options["secret_access_key"] = secret_key
    if endpoint:
        options["endpoint"] = endpoint
    if anonymous:
        options["anonymous"] = True

    catalog.add_remote(name, url, options, set_default=set_default)
    click.echo(f"Added remote '{name}': {url}")

    if set_default or catalog.default_remote == name:
        click.echo(f"Set '{name}' as default remote")


@remote.command("list")
@click.pass_context
def remote_list(ctx):
    """List configured remote storage backends."""
    catalog = get_catalog(ctx)

    if not catalog.remotes:
        click.echo("No remotes configured. Add one with:")
        click.echo("  portolan remote add origin s3://your-bucket/path")
        return

    for name, remote in catalog.remotes.items():
        default_marker = " (default)" if name == catalog.default_remote else ""
        click.echo(f"  {name}: {remote.url}{default_marker}")


@remote.command("remove")
@click.argument("name")
@click.pass_context
def remote_remove(ctx, name: str):
    """Remove a remote storage backend."""
    catalog = get_catalog(ctx)

    if name not in catalog.remotes:
        raise click.ClickException(f"Remote '{name}' not found")

    catalog.remove_remote(name)
    click.echo(f"Removed remote '{name}'")


@remote.command("set-default")
@click.argument("name")
@click.pass_context
def remote_set_default(ctx, name: str):
    """Set the default remote for sync operations."""
    catalog = get_catalog(ctx)

    if name not in catalog.remotes:
        raise click.ClickException(f"Remote '{name}' not found")

    catalog.default_remote = name
    catalog.save()
    click.echo(f"Set '{name}' as default remote")


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
    from iceberg_catalog import generate_sdi_catalog, extract_parquet_metadata

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

    click.echo()
    click.echo(click.style("Dataset added successfully!", fg="green"))
    click.echo(f"  ID: {dataset_id}")
    click.echo(f"  Type: {format_name}")
    click.echo(f"  Visibility: {visibility}")
    click.echo(f"  Location: {output_dir}")

    if not is_public:
        click.echo(f"\n  Note: Private datasets require authentication to access.")

    click.echo(f"\nRun 'portolan sync' to push to remote storage.")


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


# ============== SYNC ==============

@cli.command()
@click.option("--remote", "-r", help="Remote name (default: uses default remote)")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.option("--dry-run", is_flag=True, help="Show what would be synced without uploading")
@click.pass_context
def sync(ctx, remote: str | None, verbose: bool, dry_run: bool):
    """Sync local catalog to remote storage.

    Uploads all local datasets to the configured remote storage backend.

    \b
    Examples:
        portolan sync                    # Sync to default remote
        portolan sync -r backup          # Sync to specific remote
        portolan sync --dry-run          # Preview sync without uploading
    """
    import asyncio

    catalog = get_catalog(ctx)

    # Get the remote configuration
    remote_name = remote or catalog.default_remote
    if not remote_name:
        raise click.ClickException(
            "No remote configured. Add one with:\n"
            "  portolan remote add origin s3://your-bucket/path"
        )

    if remote_name not in catalog.remotes:
        raise click.ClickException(f"Remote '{remote_name}' not found")

    remote_config = catalog.remotes[remote_name]
    click.echo(f"Syncing to {remote_config.url}...")

    # Count files to sync
    files_to_sync = []
    for subdir in ["public", "private", "v1"]:
        local_dir = catalog.path / subdir
        if local_dir.exists():
            for f in local_dir.rglob("*"):
                if f.is_file():
                    rel_path = f.relative_to(catalog.path)
                    files_to_sync.append((f, str(rel_path)))

    if not files_to_sync:
        click.echo("Nothing to sync. Add datasets with:")
        click.echo("  portolan dataset add <file.parquet> --public")
        return

    click.echo(f"Found {len(files_to_sync)} files to sync")

    if dry_run:
        click.echo("\nDry run - would sync:")
        for local_path, rel_path in files_to_sync[:20]:
            click.echo(f"  {rel_path}")
        if len(files_to_sync) > 20:
            click.echo(f"  ... and {len(files_to_sync) - 20} more")
        return

    # Perform the sync using obstore
    async def do_sync():
        try:
            store, prefix = get_store(remote_config.url, remote_config.options)
        except ImportError:
            raise click.ClickException(
                "obstore not installed. Install with:\n"
                "  pip install obstore"
            )

        import obstore

        uploaded = 0
        errors = 0

        with click.progressbar(files_to_sync, label="Uploading") as bar:
            for local_path, rel_path in bar:
                remote_path = f"{prefix}/{rel_path}" if prefix else rel_path

                try:
                    with open(local_path, "rb") as f:
                        data = f.read()

                    await obstore.put_async(store, remote_path, data)
                    uploaded += 1

                    if verbose:
                        click.echo(f"  {rel_path}")

                except Exception as e:
                    errors += 1
                    if verbose:
                        click.echo(f"  Error uploading {rel_path}: {e}", err=True)

        return uploaded, errors

    uploaded, errors = asyncio.run(do_sync())

    click.echo()
    if errors:
        click.echo(click.style(f"Synced {uploaded} files with {errors} errors", fg="yellow"))
    else:
        click.echo(click.style(f"Synced {uploaded} files successfully!", fg="green"))

    # Show the remote URL
    click.echo(f"\nRemote catalog: {remote_config.url}")


# ============== STATUS ==============

@cli.command()
@click.pass_context
def status(ctx):
    """Show catalog status and configuration."""
    catalog = find_catalog()

    if catalog is None:
        click.echo("No Portolan catalog found in current directory.")
        click.echo("Run 'portolan init' to create one.")
        return

    click.echo(click.style("Portolan Catalog Status", bold=True))
    click.echo("=" * 40)
    click.echo(f"Location: {catalog.path}")

    # Count datasets
    public_count = 0
    private_count = 0

    for metadata_file in (catalog.path / "public").rglob("v1.metadata.json"):
        public_count += 1
    for metadata_file in (catalog.path / "private").rglob("v1.metadata.json"):
        private_count += 1

    click.echo(f"\nDatasets:")
    click.echo(f"  Public: {public_count}")
    click.echo(f"  Private: {private_count}")

    # Show remotes
    click.echo(f"\nRemotes:")
    if catalog.remotes:
        for name, remote in catalog.remotes.items():
            default = " (default)" if name == catalog.default_remote else ""
            click.echo(f"  {name}: {remote.url}{default}")
    else:
        click.echo("  No remotes configured")

    # Check sync status
    if catalog.default_remote:
        click.echo(f"\nSync: Use 'portolan sync' to push changes to remote")


# ============== WEB ==============

@cli.group()
def web():
    """Manage the web UI."""
    pass


@web.command("serve")
@click.option("--port", "-p", type=int, default=8080, help="Port (default: 8080)")
@click.option("--host", "-h", default="127.0.0.1", help="Host (default: 127.0.0.1)")
@click.pass_context
def web_serve(ctx, port: int, host: str):
    """Serve the web UI locally for development.

    This serves both the web UI and the local catalog data.
    """
    import http.server
    import socketserver

    catalog = find_catalog()

    # Determine what to serve
    if catalog:
        serve_dir = catalog.path.parent  # Serve from the directory containing .portolan
    else:
        # Fallback to serving just the web UI
        web_dir = Path(__file__).parent / "web"
        if web_dir.exists():
            serve_dir = web_dir
        else:
            serve_dir = Path.cwd() / "web"

    if not serve_dir.exists():
        raise click.ClickException(f"Directory not found: {serve_dir}")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(serve_dir), **kwargs)

        def end_headers(self):
            # Add CORS headers for local development
            self.send_header("Access-Control-Allow-Origin", "*")
            super().end_headers()

    click.echo(f"Serving at http://{host}:{port}")
    click.echo(f"Directory: {serve_dir}")

    if catalog:
        click.echo(f"Catalog: {catalog.path}")

    click.echo("\nPress Ctrl+C to stop")

    with socketserver.TCPServer((host, port), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            click.echo("\nStopped")


@web.command("deploy")
@click.option("--remote", "-r", help="Remote name (default: uses default remote)")
@click.pass_context
def web_deploy(ctx, remote: str | None):
    """Deploy web UI to remote storage.

    Uploads index.html and updates the manifest.
    """
    import asyncio

    catalog = get_catalog(ctx)

    # Get the remote configuration
    remote_name = remote or catalog.default_remote
    if not remote_name or remote_name not in catalog.remotes:
        raise click.ClickException("No remote configured. Run 'portolan remote add' first.")

    remote_config = catalog.remotes[remote_name]

    # Find web UI
    web_dir = Path(__file__).parent / "web"
    if not web_dir.exists():
        web_dir = Path.cwd() / "web"

    index_file = web_dir / "index.html"
    if not index_file.exists():
        raise click.ClickException(f"Web UI not found at {web_dir}")

    async def do_deploy():
        store, prefix = get_store(remote_config.url, remote_config.options)
        import obstore

        # Upload index.html
        click.echo("Uploading index.html...")
        with open(index_file, "rb") as f:
            data = f.read()
        remote_path = f"{prefix}/index.html" if prefix else "index.html"
        await obstore.put_async(store, remote_path, data)

        # Generate and upload manifest
        click.echo("Generating manifest...")
        manifest = {
            "version": "1.0",
            "updated": datetime.now(timezone.utc).isoformat(),
            "catalogs": {"public": [], "private": []},
        }

        # Scan for catalogs
        for visibility in ["public", "private"]:
            vis_dir = catalog.path / visibility
            if vis_dir.exists():
                for metadata_file in vis_dir.rglob("v1.metadata.json"):
                    rel_path = str(metadata_file.relative_to(catalog.path))
                    parts = rel_path.split("/")

                    if visibility == "public":
                        collection = parts[2] if len(parts) > 2 else "unknown"
                        manifest["catalogs"]["public"].append({
                            "path": rel_path,
                            "collection": collection,
                        })
                    else:
                        tenant = parts[1] if len(parts) > 1 else "unknown"
                        collection = parts[3] if len(parts) > 3 else "unknown"
                        manifest["catalogs"]["private"].append({
                            "path": rel_path,
                            "tenant": tenant,
                            "collection": collection,
                        })

        manifest_data = json.dumps(manifest, indent=2).encode()
        manifest_path = f"{prefix}/manifest.json" if prefix else "manifest.json"
        await obstore.put_async(store, manifest_path, manifest_data)

        return len(manifest["catalogs"]["public"]), len(manifest["catalogs"]["private"])

    public_count, private_count = asyncio.run(do_deploy())

    click.echo()
    click.echo(click.style("Web UI deployed!", fg="green"))
    click.echo(f"  URL: {remote_config.url}/index.html")
    click.echo(f"  Public catalogs: {public_count}")
    click.echo(f"  Private catalogs: {private_count}")


# ============== MAIN ==============

def main():
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
