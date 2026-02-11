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

    Creates a directory structure (`v1/`) with __list__/__detail__ files for local
    development/testing. Use `portolan sync` to upload to remote storage — the sync
    command handles mapping __list__/__detail__ files to correct REST endpoint paths.

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

    def write_endpoint(url_path: str, data: dict, local_path: Path):
        """Write endpoint to local dir."""
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with open(local_path, "w") as f:
            json.dump(data, f, indent=2)

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
            metadata = create_table_metadata(table, data_base_url, table_uuid, table_path=data_path)
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

            # Generate manifest files (required by Iceberg readers like DuckDB)
            generate_manifest_files(table, data_base_url, metadata_dir, table.arrow_schema, table_path=data_path)
            if verbose:
                print(f"Created manifest files in {metadata_dir}")
                print(f"Created {metadata_file}")

    print(f"Generated static catalog with {total_tables} tables across {len(all_iceberg_namespaces)} namespaces")
    print("  v1/: Iceberg REST catalog endpoints")
    print("  data/: Iceberg metadata + data files")
    print("\nUse 'portolan sync' to upload to remote storage.")
    return files_created
