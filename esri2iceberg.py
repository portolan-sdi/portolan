#!/usr/bin/env python3
"""
Convert ArcGIS REST Services (FeatureServers and ImageServers) to Iceberg.

This script:
1. Discovers all FeatureServers and ImageServers from an ArcGIS services endpoint
2. Converts FeatureServer layers to GeoParquet (vector data)
3. Converts ImageServers to Raquet format (raster data in parquet with QUADBIN indexing)
4. Generates Iceberg catalog metadata with S3-compatible URLs
5. Uploads everything to S3-compatible storage (AWS S3, GCS, MinIO)

Usage:
    python esri2iceberg.py <services_url> --bucket BUCKET [--s3-endpoint ENDPOINT]

Examples:
    # AWS S3
    python esri2iceberg.py https://services6.arcgis.com/.../rest/services --bucket my-bucket

    # GCS (S3-compatible)
    python esri2iceberg.py https://services6.arcgis.com/.../rest/services --bucket my-bucket --s3-endpoint storage.googleapis.com

    # MinIO
    python esri2iceberg.py https://services6.arcgis.com/.../rest/services --bucket my-bucket --s3-endpoint localhost:9000
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from iceberg_catalog import (
    add_iceberg_field_ids,
    generate_static_catalog,
    parquet_to_iceberg_table,
)


@dataclass
class FeatureServerInfo:
    """Information about an ArcGIS FeatureServer."""
    name: str
    url: str
    layers: list[dict]


@dataclass
class ImageServerInfo:
    """Information about an ArcGIS ImageServer."""
    name: str
    url: str
    pixel_type: str | None = None
    band_count: int | None = None
    extent: dict | None = None


@dataclass
class StorageConfig:
    """Configuration for S3-compatible storage."""
    bucket: str
    endpoint: str | None = None  # None = AWS S3
    region: str = "us-east-1"

    @property
    def is_gcs(self) -> bool:
        return self.endpoint and "storage.googleapis.com" in self.endpoint

    @property
    def is_minio(self) -> bool:
        return self.endpoint and self.endpoint not in ("storage.googleapis.com",)

    def get_s3_url(self, path: str) -> str:
        """Get S3 URL for a path."""
        return f"s3://{self.bucket}/{path}"

    def get_http_url(self, path: str) -> str:
        """Get HTTP URL for a path (for REST catalog endpoint)."""
        if self.is_gcs:
            return f"https://storage.googleapis.com/{self.bucket}/{path}"
        elif self.endpoint:
            # MinIO or custom endpoint
            protocol = "http" if "localhost" in self.endpoint or "127.0.0.1" in self.endpoint else "https"
            return f"{protocol}://{self.endpoint}/{self.bucket}/{path}"
        else:
            # AWS S3
            return f"https://{self.bucket}.s3.amazonaws.com/{path}"


def get_server_id(services_url: str) -> str:
    """Generate a short ID from the services URL for folder naming."""
    parsed = urlparse(services_url)
    path_parts = [p for p in parsed.path.split('/') if p and p not in ('ArcGIS', 'arcgis', 'rest', 'services')]
    if path_parts:
        org_id = path_parts[0]
    else:
        org_id = hashlib.md5(services_url.encode()).hexdigest()[:8]
    host_short = parsed.netloc.split('.')[0]
    return f"{host_short}_{org_id}".lower()


def discover_services(services_url: str, verbose: bool = False) -> tuple[list[FeatureServerInfo], list[ImageServerInfo]]:
    """Discover all FeatureServers and ImageServers from an ArcGIS services endpoint."""
    services_url = services_url.rstrip('/')

    if verbose:
        print(f"Discovering services from {services_url}")

    try:
        response = httpx.get(f"{services_url}?f=json", timeout=30)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"Error fetching services: {e}")
        return [], []

    feature_servers = []
    image_servers = []
    services = data.get('services', [])

    for service in services:
        service_type = service.get('type')
        name = service.get('name', 'unknown')

        if service_type == 'FeatureServer':
            url = service.get('url') or f"{services_url}/{name}/FeatureServer"

            try:
                fs_response = httpx.get(f"{url}?f=json", timeout=30)
                fs_response.raise_for_status()
                fs_data = fs_response.json()
                layers = fs_data.get('layers', [])

                feature_servers.append(FeatureServerInfo(
                    name=name,
                    url=url,
                    layers=layers
                ))

                if verbose:
                    print(f"  FeatureServer: {name} ({len(layers)} layers)")
            except Exception as e:
                if verbose:
                    print(f"  Skipping FeatureServer {name}: {e}")

        elif service_type == 'ImageServer':
            url = service.get('url') or f"{services_url}/{name}/ImageServer"

            try:
                is_response = httpx.get(f"{url}?f=json", timeout=30)
                is_response.raise_for_status()
                is_data = is_response.json()

                image_servers.append(ImageServerInfo(
                    name=name,
                    url=url,
                    pixel_type=is_data.get('pixelType'),
                    band_count=is_data.get('bandCount'),
                    extent=is_data.get('extent'),
                ))

                if verbose:
                    bands = is_data.get('bandCount', '?')
                    pixel_type = is_data.get('pixelType', '?')
                    print(f"  ImageServer: {name} ({bands} bands, {pixel_type})")
            except Exception as e:
                if verbose:
                    print(f"  Skipping ImageServer {name}: {e}")

    return feature_servers, image_servers


def sanitize_name(name: str) -> str:
    """Convert a name to a safe filename."""
    name = name.lower().replace(" ", "_").replace("-", "_")
    return "".join(c for c in name if c.isalnum() or c == "_")


def convert_layer(layer_url: str, output_path: Path, verbose: bool = False) -> bool:
    """Convert a single ArcGIS FeatureServer layer to GeoParquet."""
    cmd = ["gpio", "extract", "arcgis", layer_url, str(output_path)]

    if verbose:
        cmd.append("--verbose")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            if verbose:
                print(f"    Error: {result.stderr}")
            return False
        return True
    except FileNotFoundError:
        print("Error: 'gpio' command not found. Install geoparquet-io first.")
        sys.exit(1)


def convert_imageserver(
    imageserver_url: str,
    output_path: Path,
    resolution: int | None = None,
    bbox: str | None = None,
    verbose: bool = False
) -> bool:
    """
    Convert an ArcGIS ImageServer to Raquet (raster parquet) format.

    Args:
        imageserver_url: URL to the ImageServer
        output_path: Path for output parquet file
        resolution: Target QUADBIN pixel resolution (auto-detect if None)
        bbox: Optional bounding box filter (xmin,ymin,xmax,ymax in WGS84)
        verbose: Print verbose output

    Returns:
        True if conversion succeeded
    """
    cmd = ["gpio", "raster", "convert-imageserver", imageserver_url, str(output_path)]

    if resolution is not None:
        cmd.extend(["--resolution", str(resolution)])

    if bbox:
        cmd.extend(["--bbox", bbox])

    cmd.append("--overwrite")

    if verbose:
        cmd.append("--verbose")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            if verbose:
                print(f"    Error: {result.stderr}")
            return False
        if verbose and result.stdout:
            # Print key info from stdout
            for line in result.stdout.strip().split('\n'):
                if any(x in line for x in ['ImageServer:', 'blocks', 'bands', 'Written']):
                    print(f"    {line}")
        return True
    except subprocess.TimeoutExpired:
        print("    Error: Conversion timed out (10 min limit)")
        return False
    except FileNotFoundError:
        print("Error: 'gpio' command not found. Install geoparquet-io first.")
        sys.exit(1)


def raquet_to_iceberg_table(
    parquet_path: str,
    table_name: str,
    relative_path: str | None = None,
) -> "IcebergTable":
    """
    Create an IcebergTable from a Raquet (raster parquet) file.

    Raquet files have a specific schema:
    - block (UBIGINT): QUADBIN spatial index
    - metadata (VARCHAR): JSON metadata including bounds, resolution, bands info
    - band_1, band_2, ... (BLOB): Compressed pixel data for each band

    Args:
        parquet_path: Path to the Raquet parquet file
        table_name: Name for the Iceberg table
        relative_path: Relative path for the parquet file in the catalog

    Returns:
        IcebergTable ready for catalog generation
    """
    import pyarrow.parquet as pq
    from iceberg_catalog import IcebergTable

    path = Path(parquet_path)
    file_size = path.stat().st_size
    pf = pq.ParquetFile(parquet_path)
    schema = pf.schema_arrow
    num_rows = pf.metadata.num_rows

    # Build Iceberg schema for Raquet format
    fields = []
    for i, field in enumerate(schema):
        # Map arrow types to Iceberg types
        if field.name == "block":
            iceberg_type = "long"  # QUADBIN index
        elif field.name == "metadata":
            iceberg_type = "string"  # JSON metadata
        else:
            # band_1, band_2, etc. are binary blobs
            iceberg_type = "binary"

        fields.append({
            "id": i + 1,
            "name": field.name,
            "required": not field.nullable,
            "type": iceberg_type,
        })

    iceberg_schema = {
        "type": "struct",
        "schema-id": 0,
        "fields": fields,
    }

    if relative_path is None:
        relative_path = f"data/{table_name}/{path.name}"

    return IcebergTable(
        name=table_name,
        parquet_path=relative_path,
        schema=iceberg_schema,
        arrow_schema=schema,
        num_rows=num_rows,
        file_size_bytes=file_size,
    )


def upload_to_s3(local_path: Path, s3_path: str, storage: StorageConfig, verbose: bool = False) -> bool:
    """Upload a file or directory to S3-compatible storage."""

    # Build aws s3 command
    cmd = ["aws", "s3", "cp"]

    if local_path.is_dir():
        cmd.append("--recursive")

    cmd.extend([str(local_path), s3_path])

    # Add endpoint if not AWS
    if storage.endpoint:
        cmd.extend(["--endpoint-url", f"https://{storage.endpoint}"])
        if storage.is_gcs:
            # GCS doesn't need special handling, just endpoint
            pass
        elif storage.is_minio:
            # MinIO might need different settings
            if "localhost" in storage.endpoint or "127.0.0.1" in storage.endpoint:
                cmd[cmd.index(f"https://{storage.endpoint}")] = f"http://{storage.endpoint}"

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            if verbose:
                print(f"Upload error: {result.stderr}")
            # Try with gcloud for GCS if aws fails
            if storage.is_gcs:
                return upload_to_gcs_fallback(local_path, s3_path, storage, verbose)
            return False
        return True
    except FileNotFoundError:
        if storage.is_gcs:
            return upload_to_gcs_fallback(local_path, s3_path, storage, verbose)
        print("Error: 'aws' CLI not found. Install AWS CLI.")
        return False


def upload_to_gcs_fallback(local_path: Path, s3_path: str, storage: StorageConfig, verbose: bool = False) -> bool:
    """Fallback to gcloud for GCS uploads."""
    # Convert s3:// to gs://
    gcs_path = s3_path.replace("s3://", "gs://")

    cmd = ["gcloud", "storage", "cp"]
    if local_path.is_dir():
        cmd.append("-r")
    cmd.extend([str(local_path), gcs_path])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            if verbose:
                print(f"Upload error: {result.stderr}")
            return False
        return True
    except FileNotFoundError:
        print("Error: Neither 'aws' nor 'gcloud' CLI found.")
        return False


def upload_catalog_endpoints(gcs_dir: Path, storage: StorageConfig, server_id: str, verbose: bool = False) -> bool:
    """Upload REST catalog endpoint files with proper object naming."""

    if storage.is_gcs:
        # Use GCS API for exact object naming (no extension)
        try:
            result = subprocess.run(
                ["gcloud", "auth", "print-access-token"],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                print("Error getting auth token")
                return False
            token = result.stdout.strip()

            for json_file in gcs_dir.glob("*.json"):
                if json_file.name == "manifest.json":
                    continue

                object_name = json_file.stem.replace("__", "/")
                upload_url = f"https://storage.googleapis.com/upload/storage/v1/b/{storage.bucket}/o"
                cmd = [
                    "curl", "-s", "-X", "POST",
                    "-H", f"Authorization: Bearer {token}",
                    "-H", "Content-Type: application/json",
                    "--data-binary", f"@{json_file}",
                    f"{upload_url}?uploadType=media&name={server_id}/{object_name}"
                ]

                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    if verbose:
                        print(f"  Error uploading {object_name}: {result.stderr}")
                    return False

                if verbose:
                    print(f"  Uploaded {object_name}")

            return True
        except FileNotFoundError:
            print("Error: 'curl' or 'gcloud' command not found.")
            return False
    else:
        # For S3/MinIO, upload files directly (they handle extensionless objects fine)
        for json_file in gcs_dir.glob("*.json"):
            if json_file.name == "manifest.json":
                continue

            object_name = json_file.stem.replace("__", "/")
            s3_path = f"s3://{storage.bucket}/{server_id}/{object_name}"

            cmd = ["aws", "s3", "cp", str(json_file), s3_path]
            if storage.endpoint:
                protocol = "http" if "localhost" in storage.endpoint else "https"
                cmd.extend(["--endpoint-url", f"{protocol}://{storage.endpoint}"])

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                if verbose:
                    print(f"  Error uploading {object_name}: {result.stderr}")
                return False

            if verbose:
                print(f"  Uploaded {object_name}")

        return True


def main():
    parser = argparse.ArgumentParser(
        description="Convert ArcGIS services (FeatureServers + ImageServers) to Iceberg on S3-compatible storage",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # AWS S3
  %(prog)s https://services.arcgis.com/.../rest/services --bucket my-bucket

  # GCS (S3-compatible)
  %(prog)s https://services.arcgis.com/.../rest/services --bucket my-bucket --s3-endpoint storage.googleapis.com

  # MinIO
  %(prog)s https://services.arcgis.com/.../rest/services --bucket my-bucket --s3-endpoint localhost:9000

  # With raster options
  %(prog)s https://server.com/rest/services --bucket my-bucket --raster-resolution 12 --raster-bbox "-122.5,37.5,-122.0,38.0"
        """
    )
    parser.add_argument(
        "services_url",
        help="ArcGIS REST services URL (e.g., https://...arcgis.com/.../rest/services)"
    )
    parser.add_argument(
        "--bucket",
        required=True,
        help="S3 bucket name"
    )
    parser.add_argument(
        "--s3-endpoint",
        help="S3-compatible endpoint (e.g., storage.googleapis.com for GCS, localhost:9000 for MinIO)"
    )
    parser.add_argument(
        "--raster-resolution",
        type=int,
        help="QUADBIN pixel resolution for ImageServers (0-26, auto-detect if not specified)"
    )
    parser.add_argument(
        "--raster-bbox",
        help="Bounding box for ImageServers: xmin,ymin,xmax,ymax in WGS84"
    )
    parser.add_argument(
        "--skip-rasters",
        action="store_true",
        help="Skip ImageServer conversion (only process FeatureServers)"
    )
    parser.add_argument(
        "--skip-vectors",
        action="store_true",
        help="Skip FeatureServer conversion (only process ImageServers)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover services but don't convert or upload"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )

    args = parser.parse_args()

    # Setup storage config
    storage = StorageConfig(
        bucket=args.bucket,
        endpoint=args.s3_endpoint,
    )

    # Normalize URL
    services_url = args.services_url.rstrip('/')
    if not services_url.endswith('/services'):
        if '/rest/services' not in services_url:
            print("Error: URL should be an ArcGIS REST services endpoint")
            print("Example: https://services6.arcgis.com/.../ArcGIS/rest/services")
            sys.exit(1)

    # Discover services
    print(f"Discovering services from: {services_url}")
    feature_servers, image_servers = discover_services(services_url, verbose=args.verbose)

    # Apply filters
    if args.skip_vectors:
        feature_servers = []
    if args.skip_rasters:
        image_servers = []

    if not feature_servers and not image_servers:
        print("No services found")
        sys.exit(1)

    # Print summary
    total_layers = sum(len(fs.layers) for fs in feature_servers)
    print(f"\nFound {len(feature_servers)} FeatureServers ({total_layers} layers), {len(image_servers)} ImageServers:")

    for fs in feature_servers:
        print(f"  [Vector] {fs.name}: {len(fs.layers)} layer(s)")
    for imgs in image_servers:
        bands = imgs.band_count or '?'
        print(f"  [Raster] {imgs.name}: {bands} band(s)")

    if args.dry_run:
        print(f"\nDry run complete. Would process {total_layers} vector layers and {len(image_servers)} raster services.")
        return

    # Create working directory
    server_id = get_server_id(services_url)
    work_dir = Path(tempfile.mkdtemp(prefix=f"esri2iceberg_{server_id}_"))
    data_dir = work_dir / "data"
    data_dir.mkdir()

    # Use S3 URLs for data references in metadata
    s3_base_url = storage.get_s3_url(server_id)
    http_base_url = storage.get_http_url(server_id)

    print(f"\nProcessing to: {s3_base_url}/")
    print(f"Working directory: {work_dir}")

    # Convert all layers
    converted_tables = []

    for fs in feature_servers:
        print(f"\nProcessing: {fs.name}")

        for layer in fs.layers:
            layer_id = layer.get('id', 0)
            layer_name = layer.get('name', f"layer_{layer_id}")
            geom_type = layer.get('geometryType', 'unknown')

            table_name = sanitize_name(f"{fs.name}_{layer_name}" if len(fs.layers) > 1 else fs.name)

            print(f"  Layer {layer_id}: {layer_name} ({geom_type})")

            table_dir = data_dir / table_name
            table_dir.mkdir(exist_ok=True)
            parquet_path = table_dir / f"{table_name}.parquet"

            layer_url = f"{fs.url}/{layer_id}"
            success = convert_layer(layer_url, parquet_path, verbose=args.verbose)

            if success and parquet_path.exists():
                print(f"    Converted: {parquet_path.stat().st_size / 1024:.1f} KB")

                try:
                    add_iceberg_field_ids(parquet_path)

                    table = parquet_to_iceberg_table(
                        str(parquet_path),
                        table_name=table_name,
                        relative_path=f"data/{table_name}/{table_name}.parquet",
                    )
                    converted_tables.append(table)
                except Exception as e:
                    print(f"    Error processing {table_name}: {e}")
            else:
                print(f"    Failed to convert")

    # Convert ImageServers to Raquet format
    for imgs in image_servers:
        table_name = sanitize_name(imgs.name)
        print(f"\nProcessing ImageServer: {imgs.name}")

        bands = imgs.band_count or '?'
        pixel_type = imgs.pixel_type or 'unknown'
        print(f"  {bands} band(s), type: {pixel_type}")

        table_dir = data_dir / table_name
        table_dir.mkdir(exist_ok=True)
        parquet_path = table_dir / f"{table_name}.parquet"

        success = convert_imageserver(
            imgs.url,
            parquet_path,
            resolution=args.raster_resolution,
            bbox=args.raster_bbox,
            verbose=args.verbose,
        )

        if success and parquet_path.exists():
            print(f"    Converted: {parquet_path.stat().st_size / 1024:.1f} KB")

            try:
                # Raquet files need field IDs too
                add_iceberg_field_ids(parquet_path)

                table = raquet_to_iceberg_table(
                    str(parquet_path),
                    table_name=table_name,
                    relative_path=f"data/{table_name}/{table_name}.parquet",
                )
                converted_tables.append(table)
            except Exception as e:
                print(f"    Error processing {table_name}: {e}")
        else:
            print(f"    Failed to convert")

    if not converted_tables:
        print("\nNo services were successfully converted")
        shutil.rmtree(work_dir)
        sys.exit(1)

    # Generate Iceberg catalog with S3 URLs
    print(f"\nGenerating Iceberg catalog for {len(converted_tables)} tables...")
    generate_static_catalog(
        tables=converted_tables,
        output_dir=str(work_dir),
        namespace="default",
        prefix="catalog",
        data_base_url=s3_base_url,  # Use S3 URLs in metadata
        verbose=args.verbose,
    )

    # Create tables.json manifest with type info
    # Track which tables are rasters (have 'block' column in schema)
    raster_table_names = {sanitize_name(imgs.name) for imgs in image_servers}

    tables_manifest = {
        "tables": [
            {
                "name": table.name,
                "type": "raster" if table.name in raster_table_names else "vector",
                "num_rows": table.num_rows,
                "metadata_url": f"{s3_base_url}/data/{table.name}/metadata/v1.metadata.json",
            }
            for table in converted_tables
        ]
    }
    tables_json_path = work_dir / "tables.json"
    with open(tables_json_path, "w") as f:
        json.dump(tables_manifest, f, indent=2)

    # Upload to S3-compatible storage
    print(f"\nUploading to {s3_base_url}/...")

    # Upload data directory
    success = upload_to_s3(
        data_dir,
        f"{s3_base_url}/",
        storage,
        verbose=args.verbose
    )

    # Upload tables.json
    if success:
        success = upload_to_s3(
            tables_json_path,
            f"{s3_base_url}/tables.json",
            storage,
            verbose=args.verbose
        )

    # Upload REST catalog endpoints
    gcs_dir = work_dir / "gcs"
    if success and gcs_dir.exists():
        print("Uploading REST catalog endpoints...")
        success = upload_catalog_endpoints(
            gcs_dir,
            storage,
            server_id,
            verbose=args.verbose
        )

    if not success:
        print("Error uploading")
        shutil.rmtree(work_dir)
        sys.exit(1)

    # Cleanup
    shutil.rmtree(work_dir)

    # Print summary
    print("\n" + "=" * 60)
    print(f"Successfully converted {len(converted_tables)} tables")
    print(f"\nS3 Location: {s3_base_url}/")
    print(f"HTTP URL: {http_base_url}/")

    # DuckDB examples
    print(f"\n--- DuckDB Usage ---")

    if storage.is_gcs:
        print("""
-- Configure for GCS S3-compatible API
SET s3_endpoint='storage.googleapis.com';
SET s3_url_style='path';
""")
    elif storage.is_minio:
        protocol = "http" if "localhost" in storage.endpoint else "https"
        print(f"""
-- Configure for MinIO
SET s3_endpoint='{storage.endpoint}';
SET s3_url_style='path';
SET s3_use_ssl={'true' if protocol == 'https' else 'false'};
""")

    print(f"""
-- Attach Iceberg REST catalog
LOAD iceberg;
ATTACH 'warehouse' AS catalog (
    TYPE iceberg,
    ENDPOINT '{http_base_url}',
    AUTHORIZATION_TYPE 'none'
);

-- List tables
SHOW ALL TABLES;

-- Query a table
SELECT * FROM catalog.default.{converted_tables[0].name} LIMIT 10;
""")

    # List tables by type
    vector_tables = [t for t in converted_tables if t.name not in raster_table_names]
    raster_tables = [t for t in converted_tables if t.name in raster_table_names]

    if vector_tables:
        print("\nVector tables (GeoParquet):")
        for table in vector_tables:
            print(f"  - {table.name}: {table.num_rows} rows")

    if raster_tables:
        print("\nRaster tables (Raquet):")
        for table in raster_tables:
            print(f"  - {table.name}: {table.num_rows} blocks")


if __name__ == "__main__":
    main()
