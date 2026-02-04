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
    outputs: dict[str, bool] = field(default_factory=lambda: {
        "iceberg": True,   # Always enabled - core catalog
        "stac": False,     # STAC static catalog
        "iso19139": False, # ISO 19139 XML metadata
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
            # Load outputs with defaults for missing keys
            default_outputs = {"iceberg": True, "stac": False, "iso19139": False}
            outputs = {**default_outputs, **data.get("outputs", {})}
            return cls(
                path=path,
                default_remote=data.get("default_remote"),
                remotes=remotes,
                outputs=outputs,
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
@click.option("--stac/--no-stac", default=False, help="Enable STAC output generation")
@click.option("--iso/--no-iso", "iso19139", default=False, help="Enable ISO 19139 output generation")
def init(path: str, remote: str | None, name: str, stac: bool, iso19139: bool):
    """Initialize a new Portolan catalog.

    Creates a .portolan directory in the specified PATH (default: current directory).

    \b
    Examples:
        portolan init                           # Initialize in current directory
        portolan init ./my-catalog              # Initialize in specific directory
        portolan init -r s3://my-bucket/data    # Initialize with S3 remote
        portolan init --stac                    # Initialize with STAC output enabled
        portolan init --stac --iso              # Enable both STAC and ISO outputs
    """
    catalog_path = Path(path).resolve() / ".portolan"

    if catalog_path.exists():
        click.echo(f"Catalog already exists at {catalog_path}")
        return

    # Create catalog structure with outputs config
    outputs = {"iceberg": True, "stac": stac, "iso19139": iso19139}
    catalog = CatalogConfig(path=catalog_path, outputs=outputs)
    catalog.path.mkdir(parents=True, exist_ok=True)
    catalog.data_dir.mkdir(exist_ok=True)
    catalog.metadata_dir.mkdir(exist_ok=True)

    # Add remote if provided
    if remote:
        catalog.add_remote(name, remote, set_default=True)
        click.echo(f"Added remote '{name}': {remote}")

    catalog.save()

    click.echo(f"Initialized Portolan catalog at {catalog_path}")

    # Show enabled outputs
    enabled_outputs = [k for k, v in outputs.items() if v]
    click.echo(f"Outputs: {', '.join(enabled_outputs)}")

    click.echo()
    click.echo("Next steps:")
    click.echo("  portolan dataset add <file.parquet> --public")
    if not remote:
        click.echo("  portolan remote add origin s3://your-bucket/path")
    click.echo("  portolan sync")
    click.echo()
    click.echo("To enable more outputs later:")
    click.echo("  portolan outputs enable stac")
    click.echo("  portolan outputs enable iso19139")


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
@click.option("--setup-cors", "do_cors", is_flag=True, help="Configure CORS for browser access")
@click.pass_context
def remote_add(ctx, name: str, url: str, access_key: str | None, secret_key: str | None,
               endpoint: str | None, region: str, anonymous: bool, set_default: bool, do_cors: bool):
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
        portolan remote add origin gs://my-bucket --setup-cors
        portolan remote add minio s3://warehouse --endpoint http://localhost:9000
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

    # Setup CORS if requested
    if do_cors:
        click.echo("Setting up CORS for browser access...")
        try:
            setup_cors_for_url(url, options)
            click.echo(click.style("CORS configured!", fg="green"))
        except Exception as e:
            click.echo(click.style(f"Warning: Could not configure CORS: {e}", fg="yellow"))
            click.echo("Run 'portolan remote setup-cors' later to enable browser access")


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


@remote.command("setup-cors")
@click.argument("name", required=False)
@click.pass_context
def remote_setup_cors(ctx, name: str | None):
    """Configure CORS on remote storage for browser access.

    This enables STAC Browser and other web tools to access your catalog.
    Supports GCS (gs://), S3 (s3://), and Azure (az://).

    \b
    Examples:
        portolan remote setup-cors           # Setup CORS on default remote
        portolan remote setup-cors origin    # Setup CORS on specific remote
    """
    catalog = get_catalog(ctx)

    remote_name = name or catalog.default_remote
    if not remote_name:
        raise click.ClickException("No remote specified and no default remote configured")

    if remote_name not in catalog.remotes:
        raise click.ClickException(f"Remote '{remote_name}' not found")

    remote_config = catalog.remotes[remote_name]
    url = remote_config.url

    click.echo(f"Setting up CORS for {remote_name} ({url})...")

    try:
        setup_cors_for_url(url, remote_config.options)

        # Mark CORS as configured so we don't keep prompting
        remote_config.options["cors_configured"] = True
        catalog.save()

        click.echo(click.style("CORS configured successfully!", fg="green"))
        click.echo("Your STAC catalog is now accessible from web browsers.")
    except Exception as e:
        raise click.ClickException(f"Failed to configure CORS: {e}")


def setup_cors_for_url(url: str, options: dict | None = None):
    """Configure CORS for a storage URL."""
    import subprocess
    import tempfile

    options = options or {}

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
            result = subprocess.run(
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
            result = subprocess.run(
                ["aws", "s3api", "put-bucket-cors", "--bucket", bucket, "--cors-configuration", f"file://{cors_file}"],
                capture_output=True,
                text=True,
                check=True
            )
        finally:
            Path(cors_file).unlink()

    elif url.startswith("az://"):
        # Azure Blob Storage - requires az CLI
        container = url[5:].split("/")[0]
        account = options.get("account_name", "")

        if not account:
            raise ValueError("Azure storage account name required in remote options")

        result = subprocess.run(
            [
                "az", "storage", "cors", "add",
                "--services", "b",
                "--methods", "GET", "HEAD", "OPTIONS",
                "--origins", "*",
                "--allowed-headers", "*",
                "--exposed-headers", "*",
                "--max-age", "3600",
                "--account-name", account
            ],
            capture_output=True,
            text=True,
            check=True
        )

    elif url.startswith("file://"):
        # Local filesystem - no CORS needed
        pass

    else:
        raise ValueError(f"Unsupported storage URL for CORS: {url}")


# ============== OUTPUTS ==============

@cli.group()
def outputs():
    """Manage output format generation (STAC, ISO 19139, etc.)."""
    pass


@outputs.command("list")
@click.pass_context
def outputs_list(ctx):
    """List output formats and their status."""
    catalog = get_catalog(ctx)

    click.echo("Output formats:")
    for name, enabled in catalog.outputs.items():
        status = click.style("enabled", fg="green") if enabled else click.style("disabled", fg="red")
        click.echo(f"  {name}: {status}")


@outputs.command("enable")
@click.argument("format_name", type=click.Choice(["stac", "iso19139"]))
@click.option("--rebuild", is_flag=True, help="Rebuild the output immediately")
@click.pass_context
def outputs_enable(ctx, format_name: str, rebuild: bool):
    """Enable an output format.

    \b
    Formats:
        stac      - STAC (SpatioTemporal Asset Catalog) JSON files
        iso19139  - ISO 19139 XML metadata files

    \b
    Examples:
        portolan outputs enable stac
        portolan outputs enable iso19139 --rebuild
    """
    from output_generators import regenerate_all_outputs

    catalog = get_catalog(ctx)
    catalog.outputs[format_name] = True
    catalog.save()

    click.echo(f"Enabled {format_name} output")

    if rebuild:
        click.echo(f"Rebuilding {format_name}...")
        regenerate_all_outputs(catalog, verbose=True)
    else:
        click.echo(f"Run 'portolan rebuild' to generate {format_name} files for existing resources")


@outputs.command("disable")
@click.argument("format_name", type=click.Choice(["stac", "iso19139"]))
@click.pass_context
def outputs_disable(ctx, format_name: str):
    """Disable an output format.

    Note: This does not delete existing output files. Use --clean to remove them.
    """
    catalog = get_catalog(ctx)
    catalog.outputs[format_name] = False
    catalog.save()

    click.echo(f"Disabled {format_name} output")
    click.echo(f"Existing {format_name} files remain in place. Delete manually if needed.")


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

    # Count files to sync (including output formats)
    files_to_sync = []
    sync_dirs = ["public", "private", "v1", "data", "gcs"]

    # Add output format directories if enabled
    if catalog.outputs.get("stac"):
        sync_dirs.append("stac")
    if catalog.outputs.get("iso19139"):
        sync_dirs.append("iso19139")

    for subdir in sync_dirs:
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

    # Hint about CORS if STAC/ISO outputs were synced
    has_browser_outputs = catalog.outputs.get("stac") or catalog.outputs.get("iso19139")
    if has_browser_outputs and not remote_config.options.get("cors_configured"):
        click.echo()
        click.echo(click.style("Tip:", bold=True) + " To access STAC/ISO from web browsers, run:")
        click.echo(f"  portolan remote setup-cors {remote_name}")


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

    # Show outputs
    click.echo(f"\nOutputs:")
    for name, enabled in catalog.outputs.items():
        status = click.style("enabled", fg="green") if enabled else click.style("disabled", dim=True)
        click.echo(f"  {name}: {status}")

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


# ============== CLONE ==============

@cli.command()
@click.argument("url")
@click.argument("path", type=click.Path(), default=".", required=False)
@click.option("--name", "-n", default="origin", help="Name for the remote (default: origin)")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def clone(url: str, path: str, name: str, verbose: bool):
    """Clone an existing Portolan catalog from a remote URL.

    Downloads the catalog metadata and resources to create a local working copy.
    The remote becomes the source of truth - use 'portolan pull' to get updates.

    \b
    Examples:
        portolan clone https://storage.googleapis.com/portolan-demo-catalog
        portolan clone gs://my-bucket/catalog ./my-local-copy
    """
    import httpx

    # Convert gs:// to https:// for fetching
    if url.startswith("gs://"):
        fetch_url = url.replace("gs://", "https://storage.googleapis.com/")
        remote_url = url  # Keep gs:// for remote config
    else:
        fetch_url = url.rstrip("/")
        remote_url = url

    catalog_path = Path(path).resolve() / ".portolan"

    if catalog_path.exists():
        raise click.ClickException(f"Catalog already exists at {catalog_path}")

    click.echo(f"Cloning from {url}...")

    # Try to fetch the Iceberg resources table to get the catalog contents
    resources_url = f"{fetch_url}/data/resources/metadata/v1.metadata.json"

    try:
        # First verify the catalog exists by checking config
        config_url = f"{fetch_url}/v1/config"
        response = httpx.get(config_url, follow_redirects=True, timeout=30)
        response.raise_for_status()
        if verbose:
            click.echo(f"  Found catalog config at {config_url}")
    except Exception as e:
        raise click.ClickException(f"Could not find Portolan catalog at {url}: {e}")

    # Create local catalog structure
    catalog = CatalogConfig(path=catalog_path)
    catalog.path.mkdir(parents=True, exist_ok=True)
    catalog.data_dir.mkdir(exist_ok=True)
    catalog.metadata_dir.mkdir(exist_ok=True)

    # Add the remote
    catalog.add_remote(name, remote_url, set_default=True)

    # Try to download resources from the STAC catalog (easier to parse than Iceberg)
    stac_url = f"{fetch_url}/stac/collections"
    resources_dir = catalog.path / "resources"

    try:
        # Try STAC catalog first
        stac_catalog_url = f"{fetch_url}/stac/catalog.json"
        response = httpx.get(stac_catalog_url, follow_redirects=True, timeout=30)

        if response.status_code == 200:
            stac_catalog = response.json()
            click.echo("  Found STAC catalog, downloading resources...")

            # Get collections from links
            for link in stac_catalog.get("links", []):
                if link.get("rel") == "child":
                    collection_href = link.get("href", "")
                    collection_url = f"{fetch_url}/stac/{collection_href.lstrip('./')}"

                    try:
                        coll_response = httpx.get(collection_url, follow_redirects=True, timeout=30)
                        if coll_response.status_code == 200:
                            collection = coll_response.json()
                            coll_id = collection.get("id", "default")

                            # Create namespace directory
                            ns_dir = resources_dir / coll_id
                            ns_dir.mkdir(parents=True, exist_ok=True)

                            # Download items
                            for item_link in collection.get("links", []):
                                if item_link.get("rel") == "item":
                                    item_href = item_link.get("href", "")
                                    item_url = f"{fetch_url}/stac/collections/{coll_id}/{item_href.lstrip('./')}"

                                    try:
                                        item_response = httpx.get(item_url, follow_redirects=True, timeout=30)
                                        if item_response.status_code == 200:
                                            item = item_response.json()
                                            item_id = item.get("id", "unknown")

                                            # Convert STAC item to Portolan resource format
                                            resource = _stac_item_to_portolan_resource(item)

                                            # Save resource
                                            resource_file = ns_dir / f"{item_id}.json"
                                            with open(resource_file, "w") as f:
                                                json.dump(resource, f, indent=2)

                                            if verbose:
                                                click.echo(f"    Downloaded: {coll_id}/{item_id}")
                                    except Exception as e:
                                        if verbose:
                                            click.echo(f"    Error downloading item {item_href}: {e}")

                    except Exception as e:
                        if verbose:
                            click.echo(f"  Error downloading collection {collection_href}: {e}")

            # Enable STAC output since the remote has it
            catalog.outputs["stac"] = True

    except Exception as e:
        if verbose:
            click.echo(f"  No STAC catalog found, skipping resource download: {e}")

    # Check for ISO 19139
    try:
        iso_test_url = f"{fetch_url}/iso19139/"
        response = httpx.get(iso_test_url, follow_redirects=True, timeout=10)
        if response.status_code == 200:
            catalog.outputs["iso19139"] = True
            if verbose:
                click.echo("  Found ISO 19139 metadata")
    except Exception:
        pass

    catalog.save()

    # Count what we got
    resource_count = sum(1 for _ in resources_dir.rglob("*.json")) if resources_dir.exists() else 0

    click.echo()
    click.echo(click.style("Cloned successfully!", fg="green"))
    click.echo(f"  Location: {catalog_path}")
    click.echo(f"  Remote: {name} ({remote_url})")
    click.echo(f"  Resources: {resource_count}")
    click.echo(f"  Outputs: {', '.join(k for k, v in catalog.outputs.items() if v)}")
    click.echo()
    click.echo("Next steps:")
    click.echo("  portolan status          # View catalog status")
    click.echo("  portolan pull            # Get latest from remote")
    click.echo("  portolan dataset add ... # Add new data")
    click.echo("  portolan sync            # Push changes to remote")


def _stac_item_to_portolan_resource(item: dict) -> dict:
    """Convert a STAC item to Portolan resource format."""
    properties = item.get("properties", {})
    bbox = item.get("bbox", [])

    spatial_extent = None
    if len(bbox) >= 4:
        spatial_extent = {
            "west": bbox[0],
            "south": bbox[1],
            "east": bbox[2],
            "north": bbox[3],
        }

    # Extract format from portolan extension or guess from assets
    fmt = properties.get("portolan:format", "unknown")
    rtype = properties.get("portolan:type", "external")

    # Convert assets
    assets = {}
    for key, asset in item.get("assets", {}).items():
        assets[key] = {
            "href": asset.get("href", ""),
            "type": asset.get("type", ""),
            "title": asset.get("title", key),
        }

    return {
        "name": item.get("id", "unknown"),
        "type": rtype,
        "format": fmt,
        "title": properties.get("title", item.get("id", "")),
        "abstract": properties.get("description", ""),
        "spatial_extent": spatial_extent,
        "crs": "EPSG:4326",
        "assets": assets,
        "properties": properties,
        "created_at": properties.get("datetime"),
        "updated_at": properties.get("datetime"),
    }


# ============== PULL ==============

@cli.command()
@click.option("--remote", "-r", help="Remote name (default: uses default remote)")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def pull(ctx, remote: str | None, verbose: bool):
    """Pull latest changes from remote catalog.

    Downloads new and updated resources from the remote, similar to 'git pull'.
    Local changes that haven't been synced will be preserved.

    \b
    Examples:
        portolan pull              # Pull from default remote
        portolan pull -r origin    # Pull from specific remote
    """
    import httpx

    catalog = get_catalog(ctx)

    # Get remote config
    remote_name = remote or catalog.default_remote
    if not remote_name:
        raise click.ClickException("No remote configured. Add one with 'portolan remote add'")

    if remote_name not in catalog.remotes:
        raise click.ClickException(f"Remote '{remote_name}' not found")

    remote_config = catalog.remotes[remote_name]
    url = remote_config.url

    # Convert gs:// to https://
    if url.startswith("gs://"):
        fetch_url = url.replace("gs://", "https://storage.googleapis.com/")
    else:
        fetch_url = url.rstrip("/")

    click.echo(f"Pulling from {remote_name} ({url})...")

    resources_dir = catalog.path / "resources"
    added = 0
    updated = 0
    unchanged = 0

    # Try to pull from STAC catalog
    try:
        stac_catalog_url = f"{fetch_url}/stac/catalog.json"
        response = httpx.get(stac_catalog_url, follow_redirects=True, timeout=30)

        if response.status_code == 200:
            stac_catalog = response.json()

            for link in stac_catalog.get("links", []):
                if link.get("rel") == "child":
                    collection_href = link.get("href", "")
                    collection_url = f"{fetch_url}/stac/{collection_href.lstrip('./')}"

                    try:
                        coll_response = httpx.get(collection_url, follow_redirects=True, timeout=30)
                        if coll_response.status_code == 200:
                            collection = coll_response.json()
                            coll_id = collection.get("id", "default")
                            ns_dir = resources_dir / coll_id
                            ns_dir.mkdir(parents=True, exist_ok=True)

                            for item_link in collection.get("links", []):
                                if item_link.get("rel") == "item":
                                    item_href = item_link.get("href", "")
                                    item_url = f"{fetch_url}/stac/collections/{coll_id}/{item_href.lstrip('./')}"

                                    try:
                                        item_response = httpx.get(item_url, follow_redirects=True, timeout=30)
                                        if item_response.status_code == 200:
                                            item = item_response.json()
                                            item_id = item.get("id", "unknown")
                                            resource = _stac_item_to_portolan_resource(item)

                                            resource_file = ns_dir / f"{item_id}.json"

                                            # Check if exists and compare
                                            if resource_file.exists():
                                                with open(resource_file) as f:
                                                    existing = json.load(f)

                                                # Simple comparison - check if assets changed
                                                if existing.get("assets") != resource.get("assets"):
                                                    with open(resource_file, "w") as f:
                                                        json.dump(resource, f, indent=2)
                                                    updated += 1
                                                    if verbose:
                                                        click.echo(f"  Updated: {coll_id}/{item_id}")
                                                else:
                                                    unchanged += 1
                                            else:
                                                with open(resource_file, "w") as f:
                                                    json.dump(resource, f, indent=2)
                                                added += 1
                                                if verbose:
                                                    click.echo(f"  Added: {coll_id}/{item_id}")

                                    except Exception as e:
                                        if verbose:
                                            click.echo(f"  Error: {item_href}: {e}")

                    except Exception as e:
                        if verbose:
                            click.echo(f"  Error fetching collection: {e}")

        else:
            click.echo("  No STAC catalog found on remote")

    except Exception as e:
        raise click.ClickException(f"Failed to pull from remote: {e}")

    click.echo()
    click.echo(click.style("Pull complete!", fg="green"))
    click.echo(f"  Added: {added}")
    click.echo(f"  Updated: {updated}")
    click.echo(f"  Unchanged: {unchanged}")

    if added > 0 or updated > 0:
        click.echo()
        click.echo("Run 'portolan rebuild' to regenerate outputs with new data")


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
    from iceberg_catalog import (
        IcebergTable,
        generate_static_catalog,
        add_iceberg_field_ids,
        _arrow_schema_to_iceberg,
    )
    import pyarrow as pa
    import pyarrow.parquet as pq

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

    click.echo(f"\nFormats:")
    for fmt, count in sorted(format_counts.items()):
        click.echo(f"  {fmt}: {count}")

    # Show registered direct tables
    if len(all_tables) > 1:
        click.echo(f"\nDirect tables (queryable as catalog.portolan.<name>):")
        for t in all_tables:
            if t.name != "resources":
                click.echo(f"  - {t.name}")

    click.echo(f"\nQuery with DuckDB (simple Parquet):")
    click.echo(f"  duckdb -c \"SELECT name, format, title FROM '{simple_parquet}'\"")

    click.echo(f"\nQuery with DuckDB (Iceberg):")
    metadata_path = catalog.path / "data" / "resources" / "metadata" / "v1.metadata.json"
    click.echo(f"  duckdb -c \"SELECT * FROM iceberg_scan('{metadata_path}')\"")

    if base_url:
        # Convert gs:// to https:// for public access
        https_url = base_url.replace("gs://", "https://storage.googleapis.com/")

        click.echo(f"\nAfter uploading with: .portolan/upload_static_catalog.sh {base_url}")
        click.echo(f"\nQuery with DuckDB (iceberg_scan):")
        click.echo(f"  duckdb -c \"SELECT * FROM iceberg_scan('{https_url}/data/resources/metadata/v1.metadata.json')\"")
        click.echo(f"\nQuery with DuckDB (REST catalog ATTACH):")
        click.echo(f"  ATTACH '' AS catalog (")
        click.echo(f"      TYPE iceberg,")
        click.echo(f"      ENDPOINT '{https_url}',")
        click.echo(f"      AUTHORIZATION_TYPE 'none'")
        click.echo(f"  );")
        click.echo(f"  -- Discovery table:")
        click.echo(f"  SELECT * FROM catalog.portolan.resources;")
        if len(all_tables) > 1:
            direct_names = [t.name for t in all_tables if t.name != "resources"]
            click.echo(f"  -- Direct data tables:")
            for tname in direct_names[:3]:  # Show first 3
                click.echo(f"  SELECT * FROM catalog.portolan.{tname} LIMIT 10;")
        click.echo(f"\nBigQuery (BigLake Iceberg table):")
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
    outputs_msg = f" + {', '.join(enabled)}" if enabled else ""

    click.echo()
    click.echo(click.style(f"Imported {saved} resources!", fg="green"))
    click.echo(f"  Location: {resources_dir}")
    if enabled:
        click.echo(f"  Also updated: {', '.join(enabled)}")
    click.echo(f"\nRun 'portolan sync' to push to remote storage.")


# ============== MAIN ==============

def main():
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
