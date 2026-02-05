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
