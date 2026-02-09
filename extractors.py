"""
Extractors for snapshotting external resources.

Each extractor downloads/converts data from a specific source type
(file, ArcGIS, WFS, STAC, PostgreSQL, Oracle) to local GeoParquet.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import click

from portolan_resource import Resource, SourceMetadata

# Table name validation to prevent SQL injection
TABLE_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]*$")


def _validate_table_name(name: str) -> str:
    """Validate table name to prevent SQL injection."""
    if not TABLE_NAME_RE.match(name):
        raise click.ClickException(
            f"Invalid table name: {name}. Only alphanumeric, underscore, and dot allowed."
        )
    return name


def _load_connection(catalog_path: Path, name: str | None) -> dict | None:
    """Load a connection configuration by name."""
    import json

    if not name:
        return None

    connections_file = catalog_path / "connections.json"
    if not connections_file.exists():
        return None

    with open(connections_file) as f:
        connections = json.load(f)

    return connections.get("connections", {}).get(name)


# Supported extractor types — used by _detect_default_action in portolan.py
EXTRACTORS = {
    "file", "arcgis_featureserver", "wfs", "arcgis_imageserver",
    "stac", "postgres", "oracle", "pointcloud",
}


def run_extractor(
    resource: Resource,
    output_path: Path,
    catalog_path: Path,
    bbox: str | None = None,
    verbose: bool = False,
) -> None:
    """Dispatch to the correct extractor based on resource.origin.type."""
    extractors = {
        "file": extract_file,
        "arcgis_featureserver": extract_arcgis_featureserver,
        "wfs": extract_wfs,
        "arcgis_imageserver": extract_arcgis_imageserver,
        "stac": extract_stac,
        "postgres": extract_postgres,
        "oracle": extract_oracle,
        "pointcloud": extract_pointcloud,
    }
    fn = extractors.get(resource.origin.type)
    if fn is None:
        raise click.ClickException(f"Unsupported origin type: {resource.origin.type}")
    fn(resource, output_path, catalog_path=catalog_path, bbox=bbox, verbose=verbose)


def extract_file(
    resource: Resource,
    output_path: Path,
    catalog_path: Path = None,
    bbox: str | None = None,
    verbose: bool = False,
) -> None:
    """Extract from a local file (copy or convert to GeoParquet)."""
    source_path = Path(resource.origin.url)
    if not source_path.exists():
        raise click.ClickException(f"Source file not found: {source_path}")

    if source_path.suffix in (".parquet", ".geoparquet"):
        shutil.copy(source_path, output_path)
        if verbose:
            click.echo(f"  Copied {source_path} to {output_path}")
    else:
        import geopandas as gpd

        gdf = gpd.read_file(source_path)
        gdf.to_parquet(output_path)
        if verbose:
            click.echo(f"  Converted {source_path} to GeoParquet")


def extract_pointcloud(
    resource: Resource,
    output_path: Path,
    catalog_path: Path = None,
    bbox: str | None = None,
    verbose: bool = False,
) -> None:
    """Extract point cloud (LAZ/LAS/COPC/E57) to Parquet using DuckDB PDAL extension."""
    import duckdb

    source_url = resource.origin.url
    source_path = Path(source_url)
    is_remote = source_url.startswith(("http://", "https://", "s3://"))

    if not is_remote and not source_path.exists():
        raise click.ClickException(f"Point cloud file not found: {source_path}")

    conn = duckdb.connect()
    try:
        conn.execute("INSTALL pdal FROM community; LOAD pdal;")
    except Exception as e:
        raise click.ClickException(
            f"Failed to load DuckDB PDAL extension: {e}\n"
            "Install with: duckdb -c \"INSTALL pdal FROM community;\""
        )

    read_path = source_url if is_remote else str(source_path.resolve())

    if verbose:
        try:
            info = conn.execute(f"SELECT * FROM PDAL_Info('{read_path}')").fetchone()
            if info:
                click.echo(f"  Point cloud: {info[0]} points")
        except Exception:
            pass

    conn.execute(f"""
        COPY (SELECT * FROM PDAL_Read('{read_path}'))
        TO '{output_path}' (FORMAT PARQUET)
    """)
    conn.close()

    if verbose:
        click.echo(f"  Converted {source_url} to Parquet: {output_path}")


def extract_arcgis_featureserver(
    resource: Resource,
    output_path: Path,
    catalog_path: Path = None,
    bbox: str | None = None,
    verbose: bool = False,
) -> None:
    """Extract from ArcGIS FeatureServer using gpio CLI."""
    import httpx

    # Fetch layer metadata from ArcGIS REST API
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

    layer_name = layer_meta.get("name", "")
    geometry_type = layer_meta.get("geometryType", "")
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
        layer_desc = layer_meta.get("description", "")
        extent = layer_meta.get("extent", {})
        fields = layer_meta.get("fields", [])
        resource.metadata.source = SourceMetadata(
            provider="arcgis",
            ref={"service_url": resource.origin.url, "layer_id": layer_meta.get("id")},
            fetched_at=datetime.now(timezone.utc).isoformat(),
            data={
                "name": layer_name,
                "description": layer_desc,
                "geometryType": geometry_type,
                "extent": extent,
                "fields": [
                    {"name": f.get("name"), "type": f.get("type"), "alias": f.get("alias")}
                    for f in fields
                ],
                "capabilities": layer_meta.get("capabilities"),
                "currentVersion": layer_meta.get("currentVersion"),
            },
        )


def extract_wfs(
    resource: Resource,
    output_path: Path,
    catalog_path: Path = None,
    bbox: str | None = None,
    verbose: bool = False,
) -> None:
    """Extract from WFS using ogr2ogr."""
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

    resource.metadata.source = SourceMetadata(
        provider="wfs",
        ref={"service_url": resource.origin.url, "layer": resource.origin.layer},
        fetched_at=datetime.now(timezone.utc).isoformat(),
        data={
            "service_type": "WFS",
            "layer": resource.origin.layer,
        },
    )


def extract_arcgis_imageserver(
    resource: Resource,
    output_path: Path,
    catalog_path: Path = None,
    bbox: str | None = None,
    verbose: bool = False,
) -> None:
    """Extract from ArcGIS ImageServer using raquet-io."""
    import httpx

    # Fetch service metadata
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

    service_name = service_meta.get("name", "")
    pixel_size_x = service_meta.get("pixelSizeX")
    pixel_size_y = service_meta.get("pixelSizeY")
    band_count = service_meta.get("bandCount")
    if verbose and service_name:
        click.echo(f"  Service: {service_name}")
        click.echo(f"  Bands: {band_count}, Pixel size: {pixel_size_x} x {pixel_size_y}")

    # Update kind to raster
    resource.kind = "raster"

    # Use raquet-io for extraction
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
        service_desc = service_meta.get("description", "")
        extent = service_meta.get("extent", {})
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


def extract_stac(
    resource: Resource,
    output_path: Path,
    catalog_path: Path = None,
    bbox: str | None = None,
    verbose: bool = False,
) -> None:
    """Download primary asset from a STAC item."""
    import httpx

    if verbose:
        click.echo(f"  Fetching STAC item from {resource.origin.url}...")

    try:
        response = httpx.get(resource.origin.url, follow_redirects=True, timeout=30)
        response.raise_for_status()
        item = response.json()
    except Exception as e:
        raise click.ClickException(f"Failed to fetch STAC item: {e}")

    stac_id = item.get("id")
    stac_collection = item.get("collection")
    stac_bbox = item.get("bbox")
    stac_properties = item.get("properties", {})

    resource.origin.stac_collection = stac_collection
    resource.origin.stac_item_id = stac_id

    if verbose:
        click.echo(f"  STAC Item: {stac_id}")
        click.echo(f"  Collection: {stac_collection}")
        if stac_bbox:
            click.echo(f"  Bbox: {stac_bbox}")

    # Find primary data asset
    assets = item.get("assets", {})
    primary_asset = None

    priority_keys = ["data", "visual", "image", "default", "asset"]
    for key in priority_keys:
        if key in assets:
            primary_asset = assets[key]
            break

    if not primary_asset:
        for key, asset in assets.items():
            asset_type = asset.get("type", "")
            if "parquet" in asset_type or "tiff" in asset_type or "geotiff" in asset_type:
                primary_asset = asset
                break

    if not primary_asset and assets:
        primary_asset = next(iter(assets.values()))

    if not primary_asset:
        raise click.ClickException("No downloadable asset found in STAC item")

    asset_url = primary_asset.get("href")
    if not asset_url:
        raise click.ClickException("Asset has no href")

    # Convert s3:// URLs to https:// for public buckets
    if asset_url.startswith("s3://"):
        parts = asset_url[5:].split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""
        asset_url = f"https://{bucket}.s3.amazonaws.com/{key}"
        if verbose:
            click.echo("  Converted S3 URL to HTTPS")

    asset_type = primary_asset.get("type", "")
    is_raster = "tiff" in asset_type.lower() or "geotiff" in asset_type.lower() or asset_url.endswith(".tif")

    if verbose:
        click.echo(f"  Asset type: {asset_type}")
        click.echo(f"  Downloading asset from {asset_url}...")

    if is_raster:
        # Download then convert with raquet-io
        snapshot_dir = output_path.parent
        temp_file = snapshot_dir / "temp_raster.tif"
        if verbose:
            click.echo("  Downloading raster to temp file...")
        try:
            response = httpx.get(asset_url, follow_redirects=True, timeout=300)
            response.raise_for_status()
            with open(temp_file, "wb") as f:
                f.write(response.content)
        except Exception as e:
            raise click.ClickException(f"Failed to download STAC raster: {e}")

        if verbose:
            click.echo("  Converting raster to Raquet format...")
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
            if temp_file.exists():
                temp_file.unlink()
    else:
        # Download parquet/vector directly
        try:
            response = httpx.get(asset_url, follow_redirects=True, timeout=300)
            response.raise_for_status()
            with open(output_path, "wb") as f:
                f.write(response.content)
        except Exception as e:
            raise click.ClickException(f"Failed to download STAC asset: {e}")

    # Store STAC metadata
    resource.metadata.source = SourceMetadata(
        provider="stac",
        ref={"item_url": resource.origin.url, "item_id": stac_id},
        fetched_at=datetime.now(timezone.utc).isoformat(),
        data={
            "collection": stac_collection,
            "bbox": stac_bbox,
            "properties": stac_properties,
            "assets": {
                k: {"href": v.get("href"), "type": v.get("type")}
                for k, v in item.get("assets", {}).items()
            },
        },
    )

    if is_raster:
        resource.kind = "raster"


def extract_postgres(
    resource: Resource,
    output_path: Path,
    catalog_path: Path = None,
    bbox: str | None = None,
    verbose: bool = False,
) -> None:
    """Extract from PostgreSQL using geopandas."""
    import geopandas as gpd

    conn_config = _load_connection(catalog_path, resource.origin.connection_ref)
    if not conn_config:
        raise click.ClickException(
            f"Connection '{resource.origin.connection_ref}' not found. "
            f"Add it with: portolan connection add {resource.origin.connection_ref} <connection_string>"
        )

    table_name = resource.origin.layer
    if not table_name:
        raise click.ClickException("No table specified. Use --layer to specify the table name.")

    # Validate table name to prevent SQL injection
    _validate_table_name(table_name)

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


def extract_oracle(
    resource: Resource,
    output_path: Path,
    catalog_path: Path = None,
    bbox: str | None = None,
    verbose: bool = False,
) -> None:
    """Extract from Oracle using geopandas.

    Note: gpd.read_postgis() works with any SQLAlchemy connectable,
    not just PostgreSQL. The function name is misleading but it accepts
    Oracle connections via cx_Oracle/oracledb SQLAlchemy engines.
    """
    import geopandas as gpd

    conn_config = _load_connection(catalog_path, resource.origin.connection_ref)
    if not conn_config:
        raise click.ClickException(
            f"Connection '{resource.origin.connection_ref}' not found. "
            f"Add it with: portolan connection add {resource.origin.connection_ref} <connection_string>"
        )

    table_name = resource.origin.layer
    if not table_name:
        raise click.ClickException("No table specified. Use --layer to specify the table name.")

    # Validate table name to prevent SQL injection
    _validate_table_name(table_name)

    if verbose:
        click.echo(f"  Extracting from Oracle table: {table_name}...")

    try:
        # read_postgis works with any SQLAlchemy engine (PostgreSQL, Oracle, etc.)
        gdf = gpd.read_postgis(
            sql=f"SELECT * FROM {table_name}",
            con=conn_config["connection_string"],
            geom_col=conn_config.get("geometry_column", "GEOMETRY"),
        )
        gdf.to_parquet(output_path)
    except Exception as e:
        raise click.ClickException(f"Failed to extract from Oracle: {e}")
