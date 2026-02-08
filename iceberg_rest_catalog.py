"""
Static Iceberg REST Catalog generation.

This module generates static JSON files that implement a read-only Iceberg REST catalog.
The generated files can be hosted on any static file server (GCS, S3, Nginx, etc.)
and consumed by Iceberg clients like DuckDB, Spark, or Trino.

REST Catalog Endpoints (implemented as static files):
- /v1/config - Catalog configuration
- /v1/{prefix}/namespaces - List namespaces
- /v1/{prefix}/namespaces/{namespace} - Get namespace details
- /v1/{prefix}/namespaces/{namespace}/tables - List tables in namespace
- /v1/{prefix}/namespaces/{namespace}/tables/{table} - Load table (returns metadata)
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from iceberg_metadata import (
    IcebergTable,
    create_table_metadata,
    generate_manifest_files,
)


def create_catalog_config(prefix: str = "catalog") -> dict:
    """Create the /v1/config response."""
    return {
        "defaults": {},
        "overrides": {
            "prefix": prefix,
        },
        "endpoints": [
            f"GET /v1/{prefix}/namespaces",
            f"GET /v1/{prefix}/namespaces/{{namespace}}",
            f"GET /v1/{prefix}/namespaces/{{namespace}}/tables",
            f"GET /v1/{prefix}/namespaces/{{namespace}}/tables/{{table}}",
        ],
    }


def create_namespaces_list(namespaces: list[str]) -> dict:
    """Create the /v1/{prefix}/namespaces response."""
    return {"namespaces": [[ns] for ns in namespaces]}


def create_namespace_detail(namespace: str, properties: dict | None = None) -> dict:
    """Create the /v1/{prefix}/namespaces/{namespace} response."""
    return {"namespace": [namespace], "properties": properties or {}}


def create_tables_list(tables: list[str], namespace: str) -> dict:
    """Create the /v1/{prefix}/namespaces/{namespace}/tables response."""
    return {"identifiers": [{"namespace": [namespace], "name": t} for t in tables]}


def create_load_table_response(
    table: IcebergTable,
    metadata: dict,
    metadata_location: str,
) -> dict:
    """Create the /v1/{prefix}/namespaces/{namespace}/tables/{table} response."""
    return {
        "metadata-location": metadata_location,
        "metadata": metadata,
        "config": {},
    }


def generate_static_catalog(
    tables: list[IcebergTable] | dict[str, list[IcebergTable]],
    output_dir: str,
    namespace: str = "default",
    prefix: str = "catalog",
    data_base_url: str | None = None,
    verbose: bool = False,
) -> dict[str, str]:
    """
    Generate all static JSON files for an Iceberg REST catalog.

    Creates three output structures:
    1. A directory structure (`v1/`) for local development/testing with __list__ files
    2. A flat `gcs/` directory with URL-path filenames (double-underscore separated)
    3. A `static/` directory with files at exact REST endpoint paths for static hosting

    The `static/` directory is designed for direct upload to GCS/S3 where files are
    served at their exact object paths. This allows DuckDB to ATTACH directly to the
    static catalog endpoint.

    Args:
        tables: Either a list of IcebergTable objects (all in one namespace) or
                a dict mapping namespace names to lists of IcebergTable objects.
                Dotted namespaces (e.g., "europe.spain") are converted to underscores
                for Iceberg REST compatibility (e.g., "europe_spain").
        output_dir: Directory to write the catalog files
        namespace: Namespace name (used when tables is a flat list)
        prefix: URL prefix for the catalog (default: "catalog")
        data_base_url: Base URL where data files will be served from
        verbose: Whether to print debug output

    Returns:
        Dict mapping endpoint paths to file paths
    """
    from namespace_utils import namespace_to_iceberg

    output_path = Path(output_dir)

    if data_base_url is None:
        data_base_url = str(output_path.absolute())

    # Normalize input: wrap flat list into single-namespace dict
    if isinstance(tables, list):
        tables_by_ns: dict[str, list[IcebergTable]] = {namespace: tables}
    else:
        tables_by_ns = tables

    # Convert dotted namespaces to Iceberg-safe underscored names
    iceberg_ns_map: dict[str, str] = {}  # original → iceberg-safe
    for ns in tables_by_ns:
        iceberg_ns_map[ns] = namespace_to_iceberg(ns)

    all_iceberg_namespaces = sorted(set(iceberg_ns_map.values()))
    total_tables = sum(len(ts) for ts in tables_by_ns.values())

    files_created = {}

    # Create directory structure for local development
    v1_dir = output_path / "v1"
    catalog_dir = v1_dir / prefix
    ns_dir = catalog_dir / "namespaces"

    for d in [v1_dir, catalog_dir, ns_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # Create GCS-ready flat directory (with __ separators)
    gcs_dir = output_path / "gcs"
    gcs_dir.mkdir(parents=True, exist_ok=True)

    # Track GCS objects to create
    gcs_objects = {}

    # Track files for static hosting upload script
    static_upload_map = {}

    def write_endpoint(url_path: str, data: dict, local_path: Path):
        """Write endpoint to local dir and track for static hosting upload."""
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, "w") as f:
            json.dump(data, f, indent=2)

        static_upload_map[url_path] = str(local_path)
        gcs_objects[url_path] = data
        files_created[url_path] = str(local_path)
        if verbose:
            print(f"Created {local_path}")

    # 1. /v1/config
    config_data = create_catalog_config(prefix)
    write_endpoint("/v1/config", config_data, v1_dir / "config")

    # 2. /v1/{prefix}/namespaces
    namespaces_data = create_namespaces_list(all_iceberg_namespaces)
    write_endpoint(f"/v1/{prefix}/namespaces", namespaces_data, ns_dir / "__list__")

    # 3-5. Per-namespace endpoints
    for orig_ns, ns_tables in tables_by_ns.items():
        iceberg_ns = iceberg_ns_map[orig_ns]
        ns_detail_dir = ns_dir / iceberg_ns
        tables_dir = ns_detail_dir / "tables"

        for d in [ns_detail_dir, tables_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # 3. /v1/{prefix}/namespaces/{namespace}
        ns_detail_data = create_namespace_detail(iceberg_ns)
        write_endpoint(
            f"/v1/{prefix}/namespaces/{iceberg_ns}",
            ns_detail_data,
            ns_detail_dir / "__detail__",
        )

        # 4. /v1/{prefix}/namespaces/{namespace}/tables
        table_names = [t.name for t in ns_tables]
        tables_list_data = create_tables_list(table_names, iceberg_ns)
        write_endpoint(
            f"/v1/{prefix}/namespaces/{iceberg_ns}/tables",
            tables_list_data,
            ns_detail_dir / "tables__list__",
        )

        # 5. For each table
        for table in ns_tables:
            if verbose:
                print(f"Creating catalog entry for {iceberg_ns}.{table.name}...")

            table_uuid = str(uuid.uuid4())
            data_path = f"{iceberg_ns}/{table.name}" if len(tables_by_ns) > 1 else table.name
            metadata = create_table_metadata(table, data_base_url, table_uuid)
            metadata_location = f"{data_base_url.rstrip('/')}/data/{data_path}/metadata/v1.metadata.json"
            load_response = create_load_table_response(table, metadata, metadata_location)

            write_endpoint(
                f"/v1/{prefix}/namespaces/{iceberg_ns}/tables/{table.name}",
                load_response,
                tables_dir / table.name,
            )

            # Write standalone metadata file
            metadata_dir = output_path / "data" / data_path / "metadata"
            metadata_dir.mkdir(parents=True, exist_ok=True)
            metadata_file = metadata_dir / "v1.metadata.json"
            with open(metadata_file, "w") as f:
                json.dump(metadata, f, indent=2)

            # Track metadata for static upload
            static_upload_map[f"/data/{data_path}/metadata/v1.metadata.json"] = str(metadata_file)

            # Generate manifest files (required by Iceberg readers like DuckDB)
            generate_manifest_files(table, data_base_url, metadata_dir, table.arrow_schema)
            if verbose:
                print(f"Created manifest files in {metadata_dir}")

            # Track manifest files for static upload
            manifest_path = metadata_dir / "snap-1-manifest.avro"
            manifest_list_path = metadata_dir / "snap-1-manifest-list.avro"
            if manifest_path.exists():
                static_upload_map[f"/data/{data_path}/metadata/snap-1-manifest.avro"] = str(manifest_path)
            if manifest_list_path.exists():
                static_upload_map[f"/data/{data_path}/metadata/snap-1-manifest-list.avro"] = str(manifest_list_path)

            # Track the data parquet file for upload
            data_parquet_path = output_path / "data" / data_path / f"{table.name}.parquet"
            if data_parquet_path.exists():
                static_upload_map[f"/data/{data_path}/{table.name}.parquet"] = str(data_parquet_path)
                if verbose:
                    print(f"Tracking data file: {data_parquet_path}")

            gcs_objects[f"/data/{data_path}/metadata/v1.metadata.json"] = metadata

            if verbose:
                print(f"Created {metadata_file}")

    # Write GCS manifest and individual files (flat structure with __ separators)
    manifest_path = gcs_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump({
            "endpoints": list(gcs_objects.keys()),
            "description": "Static Iceberg REST catalog manifest",
        }, f, indent=2)

    for url_path, data in gcs_objects.items():
        safe_name = url_path.lstrip("/").replace("/", "__") + ".json"
        file_path = gcs_dir / safe_name
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2)
        if verbose:
            print(f"Created GCS file: {file_path}")

    # Generate upload script for static hosting
    # Use the first namespace for the example in the script
    example_ns = all_iceberg_namespaces[0] if all_iceberg_namespaces else "default"
    upload_script_path = output_path / "upload_static_catalog.sh"
    with open(upload_script_path, "w") as f:
        f.write("#!/bin/bash\n")
        f.write("# Upload script for static Iceberg REST catalog\n")
        f.write("# This uploads files to exact REST endpoint paths in GCS\n")
        f.write("# Usage: ./upload_static_catalog.sh gs://your-bucket\n")
        f.write("#\n")
        f.write("# After upload, connect with DuckDB:\n")
        f.write("#   ATTACH '' AS catalog (\n")
        f.write("#       TYPE iceberg,\n")
        f.write("#       ENDPOINT 'https://storage.googleapis.com/YOUR-BUCKET',\n")
        f.write("#       AUTHORIZATION_TYPE 'none'\n")
        f.write("#   );\n")
        f.write(f"#   SELECT * FROM catalog.{example_ns}.TABLE_NAME;\n\n")
        f.write("BUCKET=${1:?\"Usage: $0 gs://bucket-name\"}\n\n")
        f.write("echo \"Uploading static catalog to $BUCKET...\"\n\n")

        # Separate REST endpoints from data files
        rest_endpoints = []
        data_files = []
        for url_path, local_path in sorted(static_upload_map.items()):
            if url_path.startswith("/v1/"):
                rest_endpoints.append((url_path, local_path))
            else:
                data_files.append((url_path, local_path))

        # Data files can use regular gsutil cp
        if data_files:
            f.write("# Data files\n")
            for url_path, local_path in data_files:
                gcs_path = url_path.lstrip("/")
                f.write(f"gsutil cp \"{local_path}\" \"$BUCKET/{gcs_path}\"\n")
            f.write("\n")

        # REST endpoints must use cat | gsutil cp - to create objects at exact paths
        if rest_endpoints:
            f.write("# REST endpoints (use stdin to create objects at exact paths)\n")
            for url_path, local_path in rest_endpoints:
                gcs_path = url_path.lstrip("/")
                f.write(f"cat \"{local_path}\" | gsutil cp - \"$BUCKET/{gcs_path}\"\n")

        # Add STAC and ISO directories if they exist
        f.write("\n# Compatibility layer outputs (STAC, ISO 19139)\n")
        f.write("SCRIPT_DIR=\"$(dirname \"$0\")\"\n")
        f.write("if [ -d \"$SCRIPT_DIR/stac\" ]; then\n")
        f.write("    echo \"Uploading STAC catalog...\"\n")
        f.write("    gsutil -m cp -r \"$SCRIPT_DIR/stac\" \"$BUCKET/\"\n")
        f.write("fi\n")
        f.write("if [ -d \"$SCRIPT_DIR/iso19139\" ]; then\n")
        f.write("    echo \"Uploading ISO 19139 metadata...\"\n")
        f.write("    gsutil -m cp -r \"$SCRIPT_DIR/iso19139\" \"$BUCKET/\"\n")
        f.write("fi\n")

        f.write("\necho \"\"\n")
        f.write("echo \"Upload complete!\"\n")
        f.write("echo \"Catalog endpoint: https://storage.googleapis.com/${BUCKET#gs://}/v1/config\"\n")
        f.write("echo \"\"\n")
        f.write("echo \"Connect with DuckDB:\"\n")
        f.write("echo \"  ATTACH '' AS catalog (\"\n")
        f.write("echo \"      TYPE iceberg,\"\n")
        f.write("echo \"      ENDPOINT 'https://storage.googleapis.com/${BUCKET#gs://}',\"\n")
        f.write("echo \"      AUTHORIZATION_TYPE 'none'\"\n")
        f.write("echo \"  );\"\n")
        f.write(f"echo \"  SELECT * FROM catalog.{example_ns}.TABLE_NAME;\"\n")

    # Make script executable
    upload_script_path.chmod(0o755)

    # Also generate a static upload map JSON for programmatic use
    upload_map_path = output_path / "static_upload_map.json"
    with open(upload_map_path, "w") as f:
        json.dump(static_upload_map, f, indent=2)

    print(f"Generated static catalog with {total_tables} tables across {len(all_iceberg_namespaces)} namespaces")
    print("  - v1/: Local dev structure (with __list__ files)")
    print("  - gcs/: Flat files with __ separators")
    print("\nTo serve as REST catalog with static hosting:")
    print(f"  {upload_script_path} gs://your-bucket")
    print(f"\nOr use the upload map: {upload_map_path}")
    return files_created
