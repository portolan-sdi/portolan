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
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from pyiceberg.io.pyarrow import schema_to_pyarrow
from pyiceberg.manifest import (
    DataFile,
    DataFileContent,
    FileFormat,
    ManifestContent,
    ManifestEntry,
    ManifestEntryStatus,
    ManifestFile,
    write_manifest,
    write_manifest_list,
)
from pyiceberg.partitioning import PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.typedef import Record
from pyiceberg.types import (
    BinaryType,
    BooleanType,
    DateType,
    DoubleType,
    FloatType,
    IntegerType,
    LongType,
    NestedField,
    StringType,
    StructType,
    TimestampType,
)


@dataclass
class IcebergTable:
    """Represents an Iceberg table to be added to the catalog."""

    name: str
    parquet_path: str  # Path to the GeoParquet file (relative to data root)
    schema: dict  # Arrow schema converted to Iceberg JSON format
    arrow_schema: pa.Schema  # Original PyArrow schema
    num_rows: int
    file_size_bytes: int


def _arrow_to_iceberg_schema(arrow_schema: pa.Schema) -> Schema:
    """Convert PyArrow schema to pyiceberg Schema."""
    fields = []
    for i, field in enumerate(arrow_schema):
        iceberg_type = _arrow_type_to_pyiceberg(field.type)
        if iceberg_type is not None:
            fields.append(
                NestedField(
                    field_id=i + 1,
                    name=field.name,
                    field_type=iceberg_type,
                    required=not field.nullable,
                )
            )
    return Schema(*fields)


def _arrow_type_to_pyiceberg(arrow_type):
    """Convert PyArrow type to pyiceberg type."""
    if pa.types.is_boolean(arrow_type):
        return BooleanType()
    if pa.types.is_int8(arrow_type) or pa.types.is_int16(arrow_type) or pa.types.is_int32(arrow_type):
        return IntegerType()
    if pa.types.is_int64(arrow_type):
        return LongType()
    if pa.types.is_uint8(arrow_type) or pa.types.is_uint16(arrow_type) or pa.types.is_uint32(arrow_type):
        return LongType()
    if pa.types.is_uint64(arrow_type):
        return LongType()
    if pa.types.is_float16(arrow_type) or pa.types.is_float32(arrow_type):
        return FloatType()
    if pa.types.is_float64(arrow_type):
        return DoubleType()
    if pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type):
        return StringType()
    if pa.types.is_binary(arrow_type) or pa.types.is_large_binary(arrow_type):
        return BinaryType()
    if pa.types.is_date(arrow_type):
        return DateType()
    if pa.types.is_timestamp(arrow_type):
        return TimestampType()
    if pa.types.is_struct(arrow_type):
        nested_fields = []
        for j, subfield in enumerate(arrow_type):
            subtype = _arrow_type_to_pyiceberg(subfield.type)
            if subtype is not None:
                nested_fields.append(
                    NestedField(
                        field_id=1000 + j,
                        name=subfield.name,
                        field_type=subtype,
                        required=not subfield.nullable,
                    )
                )
        return StructType(*nested_fields) if nested_fields else None
    # Skip unsupported types
    return None


def generate_manifest_files(
    table: IcebergTable,
    data_base_url: str,
    metadata_dir: Path,
    arrow_schema: pa.Schema,
    snapshot_id: int = 1,
    sequence_number: int = 1,
    table_path: str | None = None,
) -> str:
    """
    Generate Iceberg manifest and manifest-list Avro files using pyiceberg.

    Args:
        table: IcebergTable with file info
        data_base_url: Base URL where data files are stored
        metadata_dir: Directory to write manifest files
        arrow_schema: PyArrow schema for the data
        snapshot_id: Snapshot ID for the manifest
        sequence_number: Sequence number for the snapshot
        table_path: Optional path to table (e.g., "namespace/tablename"). If not provided, uses table.name

    Returns:
        Path to the manifest-list file (relative to data_base_url)
    """
    from pyiceberg.io import PY_IO_IMPL, load_file_io

    metadata_dir.mkdir(parents=True, exist_ok=True)

    # Convert arrow schema to iceberg schema
    iceberg_schema = _arrow_to_iceberg_schema(arrow_schema)

    # Create partition spec (unpartitioned)
    partition_spec = PartitionSpec()

    # Use table_path if provided, otherwise just table.name
    path_prefix = table_path if table_path else table.name

    # Create data file entry
    data_file_path = f"{data_base_url.rstrip('/')}/data/{path_prefix}/{table.name}.parquet"

    data_file = DataFile.from_args(
        content=DataFileContent.DATA,
        file_path=data_file_path,
        file_format=FileFormat.PARQUET,
        partition=Record(),
        record_count=table.num_rows,
        file_size_in_bytes=table.file_size_bytes,
    )

    # Create manifest entry
    manifest_entry = ManifestEntry.from_args(
        status=ManifestEntryStatus.ADDED,
        snapshot_id=snapshot_id,
        sequence_number=sequence_number,
        file_sequence_number=sequence_number,
        data_file=data_file,
    )

    # Write manifest file
    manifest_path = str(metadata_dir / f"snap-{snapshot_id}-manifest.avro")
    manifest_url = f"{data_base_url.rstrip('/')}/data/{path_prefix}/metadata/snap-{snapshot_id}-manifest.avro"

    output_file = load_file_io({PY_IO_IMPL: "pyiceberg.io.pyarrow.PyArrowFileIO"}).new_output(
        manifest_path
    )

    with write_manifest(
        format_version=2,
        spec=partition_spec,
        schema=iceberg_schema,
        output_file=output_file,
        snapshot_id=snapshot_id,
        avro_compression="null",
    ) as manifest_writer:
        manifest_writer.add_entry(manifest_entry)
        manifest_file = manifest_writer.to_manifest_file()

    # Get the actual file size (pyiceberg sometimes returns 0 for manifest_length)
    actual_manifest_length = Path(manifest_path).stat().st_size

    # Update manifest path to URL for the manifest-list
    manifest_file_with_url = ManifestFile.from_args(
        manifest_path=manifest_url,
        manifest_length=actual_manifest_length,  # Use actual file size
        partition_spec_id=manifest_file.partition_spec_id,
        content=manifest_file.content,
        sequence_number=manifest_file.sequence_number,
        min_sequence_number=manifest_file.min_sequence_number,
        added_snapshot_id=manifest_file.added_snapshot_id,
        added_files_count=manifest_file.added_files_count,
        existing_files_count=manifest_file.existing_files_count,
        deleted_files_count=manifest_file.deleted_files_count,
        added_rows_count=manifest_file.added_rows_count,
        existing_rows_count=manifest_file.existing_rows_count,
        deleted_rows_count=manifest_file.deleted_rows_count,
        partitions=manifest_file.partitions,
        key_metadata=manifest_file.key_metadata,
    )

    # Write manifest list file
    manifest_list_path = str(metadata_dir / f"snap-{snapshot_id}-manifest-list.avro")
    manifest_list_url = f"{data_base_url.rstrip('/')}/data/{path_prefix}/metadata/snap-{snapshot_id}-manifest-list.avro"

    output_file = load_file_io({PY_IO_IMPL: "pyiceberg.io.pyarrow.PyArrowFileIO"}).new_output(
        manifest_list_path
    )

    with write_manifest_list(
        format_version=2,
        output_file=output_file,
        snapshot_id=snapshot_id,
        parent_snapshot_id=None,
        sequence_number=sequence_number,
        avro_compression="null",
    ) as manifest_list_writer:
        manifest_list_writer.add_manifests([manifest_file_with_url])

    return manifest_list_url


def _arrow_type_to_iceberg(arrow_type) -> dict:
    """Convert PyArrow type to Iceberg type representation."""
    # Handle primitive types
    if pa.types.is_boolean(arrow_type):
        return {"type": "boolean"}
    if pa.types.is_int8(arrow_type) or pa.types.is_int16(arrow_type):
        return {"type": "int"}
    if pa.types.is_int32(arrow_type):
        return {"type": "int"}
    if pa.types.is_int64(arrow_type):
        return {"type": "long"}
    if pa.types.is_uint8(arrow_type) or pa.types.is_uint16(arrow_type):
        return {"type": "int"}
    if pa.types.is_uint32(arrow_type):
        return {"type": "long"}
    if pa.types.is_uint64(arrow_type):
        return {"type": "long"}
    if pa.types.is_float16(arrow_type) or pa.types.is_float32(arrow_type):
        return {"type": "float"}
    if pa.types.is_float64(arrow_type):
        return {"type": "double"}
    if pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type):
        return {"type": "string"}
    if pa.types.is_binary(arrow_type) or pa.types.is_large_binary(arrow_type):
        return {"type": "binary"}
    if pa.types.is_date(arrow_type):
        return {"type": "date"}
    if pa.types.is_timestamp(arrow_type):
        return {"type": "timestamp"}
    if pa.types.is_time(arrow_type):
        return {"type": "time"}

    # Handle nested types
    if pa.types.is_list(arrow_type):
        element_type = _arrow_type_to_iceberg(arrow_type.value_type)
        return {
            "type": "list",
            "element-id": 100,
            "element": element_type.get("type", "string"),
            "element-required": False,
        }

    if pa.types.is_struct(arrow_type):
        fields = []
        for i, field in enumerate(arrow_type):
            field_type = _arrow_type_to_iceberg(field.type)
            fields.append({
                "id": 200 + i,
                "name": field.name,
                "required": not field.nullable,
                "type": field_type.get("type", "string"),
            })
        return {"type": "struct", "fields": fields}

    if pa.types.is_map(arrow_type):
        return {
            "type": "map",
            "key-id": 300,
            "key": "string",
            "value-id": 301,
            "value": "string",
            "value-required": False,
        }

    # Default fallback
    return {"type": "string"}


def _arrow_schema_to_iceberg(schema) -> dict:
    """Convert PyArrow schema to Iceberg schema format."""
    fields = []
    for i, field in enumerate(schema):
        iceberg_type = _arrow_type_to_iceberg(field.type)
        # For complex types (struct, list, map), use the full type dict
        # For primitives, just use the type string
        if isinstance(iceberg_type.get("type"), str) and iceberg_type.get("type") in (
            "struct", "list", "map"
        ):
            type_value = iceberg_type
        else:
            type_value = iceberg_type.get("type", "string")
        fields.append({
            "id": i + 1,
            "name": field.name,
            "required": not field.nullable,
            "type": type_value,
        })

    return {
        "type": "struct",
        "schema-id": 0,
        "fields": fields,
    }


def create_table_metadata(
    table: IcebergTable,
    data_base_url: str,
    table_uuid: str | None = None,
    table_path: str | None = None,
) -> dict:
    """
    Create Iceberg table metadata JSON.

    Args:
        table: IcebergTable with schema and file info
        data_base_url: Base URL where data files are stored
        table_uuid: Optional UUID for the table (generated if not provided)
        table_path: Optional path to table (e.g., "namespace/tablename"). If not provided, uses table.name

    Returns:
        Iceberg table metadata dict
    """
    table_uuid = table_uuid or str(uuid.uuid4())
    current_time_ms = int(time.time() * 1000)

    # Use table_path if provided, otherwise just table.name
    path_prefix = table_path if table_path else table.name

    metadata = {
        "format-version": 2,
        "table-uuid": table_uuid,
        "location": f"{data_base_url.rstrip('/')}/data/{path_prefix}",
        "last-sequence-number": 1,
        "last-updated-ms": current_time_ms,
        "last-column-id": len(table.schema.get("fields", [])),
        "current-schema-id": 0,
        "schemas": [table.schema],
        "default-spec-id": 0,
        "partition-specs": [{"spec-id": 0, "fields": []}],  # Unpartitioned
        "last-partition-id": 999,
        "default-sort-order-id": 0,
        "sort-orders": [{"order-id": 0, "fields": []}],
        "properties": {
            "created-at": str(current_time_ms),
            "geoparquet.source": "portolan",
        },
        "current-snapshot-id": 1,
        "refs": {"main": {"snapshot-id": 1, "type": "branch"}},
        "snapshots": [
            {
                "snapshot-id": 1,
                "sequence-number": 1,
                "timestamp-ms": current_time_ms,
                "summary": {
                    "operation": "append",
                    "added-data-files": "1",
                    "added-records": str(table.num_rows),
                    "added-files-size": str(table.file_size_bytes),
                    "total-records": str(table.num_rows),
                    "total-files-size": str(table.file_size_bytes),
                    "total-data-files": "1",
                },
                "manifest-list": f"{data_base_url.rstrip('/')}/data/{path_prefix}/metadata/snap-1-manifest-list.avro",
                "schema-id": 0,
            }
        ],
        "snapshot-log": [{"snapshot-id": 1, "timestamp-ms": current_time_ms}],
        "metadata-log": [],
    }

    return metadata


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
    tables: list[IcebergTable],
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
        tables: List of IcebergTable objects to include
        output_dir: Directory to write the catalog files
        namespace: Namespace name for all tables
        prefix: URL prefix for the catalog (default: "catalog")
        data_base_url: Base URL where data files will be served from
        verbose: Whether to print debug output

    Returns:
        Dict mapping endpoint paths to file paths
    """
    output_path = Path(output_dir)

    if data_base_url is None:
        data_base_url = str(output_path.absolute())

    files_created = {}

    # Create directory structure for local development
    v1_dir = output_path / "v1"
    catalog_dir = v1_dir / prefix
    ns_dir = catalog_dir / "namespaces"
    ns_detail_dir = ns_dir / namespace
    tables_dir = ns_detail_dir / "tables"

    for d in [v1_dir, catalog_dir, ns_dir, ns_detail_dir, tables_dir]:
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
        # Write to local development directory
        with open(local_path, "w") as f:
            json.dump(data, f, indent=2)

        # Track for static hosting - store the URL path and local file
        # We'll generate upload commands later
        static_upload_map[url_path] = str(local_path)

        gcs_objects[url_path] = data
        files_created[url_path] = str(local_path)
        if verbose:
            print(f"Created {local_path}")

    # 1. /v1/config
    config_data = create_catalog_config(prefix)
    write_endpoint("/v1/config", config_data, v1_dir / "config")

    # 2. /v1/{prefix}/namespaces
    namespaces_data = create_namespaces_list([namespace])
    write_endpoint(f"/v1/{prefix}/namespaces", namespaces_data, ns_dir / "__list__")

    # 3. /v1/{prefix}/namespaces/{namespace}
    ns_detail_data = create_namespace_detail(namespace)
    write_endpoint(
        f"/v1/{prefix}/namespaces/{namespace}", ns_detail_data, ns_detail_dir / "__detail__"
    )

    # 4. /v1/{prefix}/namespaces/{namespace}/tables
    table_names = [t.name for t in tables]
    tables_list_data = create_tables_list(table_names, namespace)
    write_endpoint(
        f"/v1/{prefix}/namespaces/{namespace}/tables",
        tables_list_data,
        ns_detail_dir / "tables__list__",
    )

    # 5. For each table
    for table in tables:
        if verbose:
            print(f"Creating catalog entry for {table.name}...")

        table_uuid = str(uuid.uuid4())
        metadata = create_table_metadata(table, data_base_url, table_uuid)
        metadata_location = f"{data_base_url.rstrip('/')}/data/{table.name}/metadata/v1.metadata.json"
        load_response = create_load_table_response(table, metadata, metadata_location)

        write_endpoint(
            f"/v1/{prefix}/namespaces/{namespace}/tables/{table.name}",
            load_response,
            tables_dir / table.name,
        )

        # Write standalone metadata file
        metadata_dir = output_path / "data" / table.name / "metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)
        metadata_file = metadata_dir / "v1.metadata.json"
        with open(metadata_file, "w") as f:
            json.dump(metadata, f, indent=2)

        # Track metadata for static upload
        static_upload_map[f"/data/{table.name}/metadata/v1.metadata.json"] = str(metadata_file)

        # Generate manifest files (required by Iceberg readers like DuckDB)
        generate_manifest_files(table, data_base_url, metadata_dir, table.arrow_schema)
        if verbose:
            print(f"Created manifest files in {metadata_dir}")

        # Track manifest files for static upload
        manifest_path = metadata_dir / "snap-1-manifest.avro"
        manifest_list_path = metadata_dir / "snap-1-manifest-list.avro"
        if manifest_path.exists():
            static_upload_map[f"/data/{table.name}/metadata/snap-1-manifest.avro"] = str(manifest_path)
        if manifest_list_path.exists():
            static_upload_map[f"/data/{table.name}/metadata/snap-1-manifest-list.avro"] = str(manifest_list_path)

        # Track the data parquet file for upload
        # The data file is at output_path/data/{table.name}/{table.name}.parquet
        # This matches the path in the Iceberg manifest
        data_parquet_path = output_path / "data" / table.name / f"{table.name}.parquet"
        if data_parquet_path.exists():
            static_upload_map[f"/data/{table.name}/{table.name}.parquet"] = str(data_parquet_path)
            if verbose:
                print(f"Tracking data file: {data_parquet_path}")

        gcs_objects[f"/data/{table.name}/metadata/v1.metadata.json"] = metadata

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
        f.write(f"#   SELECT * FROM catalog.{namespace}.TABLE_NAME;\n\n")
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
        f.write(f"SCRIPT_DIR=\"$(dirname \"$0\")\"\n")
        f.write(f"if [ -d \"$SCRIPT_DIR/stac\" ]; then\n")
        f.write(f"    echo \"Uploading STAC catalog...\"\n")
        f.write(f"    gsutil -m cp -r \"$SCRIPT_DIR/stac\" \"$BUCKET/\"\n")
        f.write(f"fi\n")
        f.write(f"if [ -d \"$SCRIPT_DIR/iso19139\" ]; then\n")
        f.write(f"    echo \"Uploading ISO 19139 metadata...\"\n")
        f.write(f"    gsutil -m cp -r \"$SCRIPT_DIR/iso19139\" \"$BUCKET/\"\n")
        f.write(f"fi\n")

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
        f.write(f"echo \"  SELECT * FROM catalog.{namespace}.TABLE_NAME;\"\n")

    # Make script executable
    upload_script_path.chmod(0o755)

    # Also generate a static upload map JSON for programmatic use
    upload_map_path = output_path / "static_upload_map.json"
    with open(upload_map_path, "w") as f:
        json.dump(static_upload_map, f, indent=2)

    print(f"Generated static catalog with {len(tables)} tables")
    print(f"  - v1/: Local dev structure (with __list__ files)")
    print(f"  - gcs/: Flat files with __ separators")
    print(f"\nTo serve as REST catalog with static hosting:")
    print(f"  {upload_script_path} gs://your-bucket")
    print(f"\nOr use the upload map: {upload_map_path}")
    return files_created


def add_iceberg_field_ids(parquet_path: str | Path) -> None:
    """
    Add Iceberg field IDs to a parquet file in place.

    Iceberg requires PARQUET:field_id metadata on each column for proper
    column matching. This function reads a parquet file, adds field IDs
    to the schema, and rewrites it.

    Args:
        parquet_path: Path to the parquet file to modify
    """
    parquet_path = Path(parquet_path)

    # Read the table
    table = pq.read_table(parquet_path)

    def add_field_ids_to_schema(schema: pa.Schema, start_id: int = 1) -> pa.Schema:
        """Add PARQUET:field_id metadata to each field."""
        new_fields = []
        field_id = start_id

        for field in schema:
            # Preserve existing metadata
            metadata = dict(field.metadata) if field.metadata else {}
            metadata[b"PARQUET:field_id"] = str(field_id).encode()

            # Handle struct types recursively
            if pa.types.is_struct(field.type):
                # Add field IDs to nested struct fields
                nested_fields = []
                nested_id = 1000 + (field_id - start_id) * 100  # Nested field ID space
                for subfield in field.type:
                    sub_metadata = dict(subfield.metadata) if subfield.metadata else {}
                    sub_metadata[b"PARQUET:field_id"] = str(nested_id).encode()
                    nested_fields.append(subfield.with_metadata(sub_metadata))
                    nested_id += 1
                new_type = pa.struct(nested_fields)
                new_field = pa.field(field.name, new_type, nullable=field.nullable, metadata=metadata)
            else:
                new_field = field.with_metadata(metadata)

            new_fields.append(new_field)
            field_id += 1

        return pa.schema(new_fields, schema.metadata)

    # Create new schema with field IDs
    new_schema = add_field_ids_to_schema(table.schema)

    # Cast table to new schema
    new_table = table.cast(new_schema)

    # Write back to the same path
    pq.write_table(new_table, parquet_path, compression="zstd")


def parquet_to_iceberg_table(
    parquet_path: str,
    table_name: str | None = None,
    relative_path: str | None = None,
) -> IcebergTable:
    """
    Create an IcebergTable from a GeoParquet file.

    Args:
        parquet_path: Path to the GeoParquet file
        table_name: Name for the table (default: filename without extension)
        relative_path: Relative path for the parquet file in the catalog

    Returns:
        IcebergTable ready for catalog generation
    """
    path = Path(parquet_path)

    if table_name is None:
        table_name = path.stem

    # Sanitize table name
    table_name = table_name.lower().replace(" ", "_").replace("-", "_")
    table_name = "".join(c for c in table_name if c.isalnum() or c == "_")

    file_size = path.stat().st_size
    pf = pq.ParquetFile(parquet_path)
    schema = pf.schema_arrow
    num_rows = pf.metadata.num_rows
    iceberg_schema = _arrow_schema_to_iceberg(schema)

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


# =============================================================================
# STAC + ISO 19115 SDI Catalog Support
# =============================================================================


def create_stac_iso_schema() -> pa.Schema:
    """
    Create PyArrow schema for STAC + ISO 19115 items table.

    This schema combines STAC core fields with standard-depth ISO 19115 metadata
    for SDI compliance. Uses Iceberg-compatible types.

    Returns:
        PyArrow schema for the items table
    """
    return pa.schema([
        # Primary identifier
        pa.field("id", pa.string(), nullable=False),

        # STAC core fields
        pa.field("geometry", pa.binary()),  # WKB geometry (Iceberg geometry support varies)
        pa.field("bbox_west", pa.float64()),
        pa.field("bbox_south", pa.float64()),
        pa.field("bbox_east", pa.float64()),
        pa.field("bbox_north", pa.float64()),
        pa.field("datetime", pa.timestamp("us", tz="UTC")),
        pa.field("start_datetime", pa.timestamp("us", tz="UTC")),
        pa.field("end_datetime", pa.timestamp("us", tz="UTC")),

        # STAC assets and links (JSON as string)
        pa.field("assets", pa.string()),
        pa.field("links", pa.string()),

        # ISO 19115 Core Identification
        pa.field("title", pa.string(), nullable=False),
        pa.field("abstract", pa.string()),
        pa.field("topic_category", pa.string()),
        pa.field("keywords", pa.string()),  # JSON array

        # ISO 19115 Spatial Reference
        pa.field("spatial_resolution", pa.float64()),
        pa.field("spatial_resolution_unit", pa.string()),
        pa.field("reference_system", pa.string()),
        pa.field("spatial_representation", pa.string()),

        # ISO 19115 Contact
        pa.field("contact_organization", pa.string()),
        pa.field("contact_email", pa.string()),
        pa.field("contact_role", pa.string()),

        # ISO 19115 Distribution
        pa.field("format_name", pa.string()),
        pa.field("format_version", pa.string()),
        pa.field("access_url", pa.string()),

        # ISO 19115 Quality & Lineage
        pa.field("lineage", pa.string()),
        pa.field("quality_scope", pa.string()),

        # ISO 19115 Constraints
        pa.field("license", pa.string()),
        pa.field("use_constraints", pa.string()),
        pa.field("access_constraints", pa.string()),

        # Metadata Admin
        pa.field("metadata_date", pa.timestamp("us", tz="UTC")),
        pa.field("created_at", pa.timestamp("us", tz="UTC")),
        pa.field("updated_at", pa.timestamp("us", tz="UTC")),

        # Raquet-specific fields (for raster items)
        pa.field("raquet_num_bands", pa.int32()),
        pa.field("raquet_band_names", pa.string()),  # JSON array
        pa.field("raquet_compression", pa.string()),
        pa.field("raquet_block_size", pa.int32()),
        pa.field("raquet_min_zoom", pa.int32()),
        pa.field("raquet_max_zoom", pa.int32()),
        pa.field("raquet_bounds", pa.string()),  # JSON array [west, south, east, north]
    ])


def create_stac_iso_record(
    item_id: str,
    title: str,
    stac_info: dict | None = None,
    iso_info: dict | None = None,
    raquet_info: dict | None = None,
) -> dict:
    """
    Create a single STAC + ISO 19115 metadata record.

    Args:
        item_id: Unique identifier for the item
        title: Dataset title (required)
        stac_info: STAC fields dict with keys:
            - geometry: WKB bytes or WKT string
            - bbox: [west, south, east, north]
            - datetime: ISO timestamp string or datetime
            - start_datetime, end_datetime: for temporal ranges
            - assets: dict of assets {"name": {"href": "...", "type": "..."}}
            - links: list of link dicts
        iso_info: ISO 19115 fields dict with keys:
            - abstract, topic_category, keywords (list)
            - spatial_resolution, spatial_resolution_unit, reference_system
            - contact_organization, contact_email, contact_role
            - format_name, format_version, access_url
            - lineage, quality_scope
            - license, use_constraints, access_constraints
        raquet_info: Raquet-specific fields dict with keys:
            - num_bands, band_names (list), compression
            - block_size, min_zoom, max_zoom, bounds

    Returns:
        Dict ready for PyArrow table creation
    """
    from datetime import datetime, timezone

    stac = stac_info or {}
    iso = iso_info or {}
    raquet = raquet_info or {}

    now = datetime.now(timezone.utc)

    # Parse bbox
    bbox = stac.get("bbox", [None, None, None, None])

    # Handle datetime parsing
    def parse_dt(val):
        if val is None:
            return None
        if isinstance(val, datetime):
            return val
        if isinstance(val, str):
            # Try ISO format
            try:
                return datetime.fromisoformat(val.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    return {
        # Primary identifier
        "id": item_id,

        # STAC core
        "geometry": stac.get("geometry"),  # WKB bytes or None
        "bbox_west": bbox[0] if len(bbox) > 0 else None,
        "bbox_south": bbox[1] if len(bbox) > 1 else None,
        "bbox_east": bbox[2] if len(bbox) > 2 else None,
        "bbox_north": bbox[3] if len(bbox) > 3 else None,
        "datetime": parse_dt(stac.get("datetime")),
        "start_datetime": parse_dt(stac.get("start_datetime")),
        "end_datetime": parse_dt(stac.get("end_datetime")),

        # STAC assets/links as JSON strings
        "assets": json.dumps(stac.get("assets", {})) if stac.get("assets") else None,
        "links": json.dumps(stac.get("links", [])) if stac.get("links") else None,

        # ISO 19115 Core Identification
        "title": title,
        "abstract": iso.get("abstract"),
        "topic_category": iso.get("topic_category"),
        "keywords": json.dumps(iso.get("keywords", [])) if iso.get("keywords") else None,

        # ISO 19115 Spatial Reference
        "spatial_resolution": iso.get("spatial_resolution"),
        "spatial_resolution_unit": iso.get("spatial_resolution_unit"),
        "reference_system": iso.get("reference_system"),
        "spatial_representation": iso.get("spatial_representation"),

        # ISO 19115 Contact
        "contact_organization": iso.get("contact_organization"),
        "contact_email": iso.get("contact_email"),
        "contact_role": iso.get("contact_role"),

        # ISO 19115 Distribution
        "format_name": iso.get("format_name"),
        "format_version": iso.get("format_version"),
        "access_url": iso.get("access_url"),

        # ISO 19115 Quality & Lineage
        "lineage": iso.get("lineage"),
        "quality_scope": iso.get("quality_scope"),

        # ISO 19115 Constraints
        "license": iso.get("license"),
        "use_constraints": iso.get("use_constraints"),
        "access_constraints": iso.get("access_constraints"),

        # Metadata Admin
        "metadata_date": parse_dt(iso.get("metadata_date")) or now,
        "created_at": now,
        "updated_at": now,

        # Raquet-specific
        "raquet_num_bands": raquet.get("num_bands"),
        "raquet_band_names": json.dumps(raquet.get("band_names", [])) if raquet.get("band_names") else None,
        "raquet_compression": raquet.get("compression"),
        "raquet_block_size": raquet.get("block_size"),
        "raquet_min_zoom": raquet.get("min_zoom"),
        "raquet_max_zoom": raquet.get("max_zoom"),
        "raquet_bounds": json.dumps(raquet.get("bounds", [])) if raquet.get("bounds") else None,
    }


def create_items_table(
    records: list[dict],
    output_dir: str | Path,
    collection: str,
) -> IcebergTable:
    """
    Create an Iceberg items table from STAC+ISO metadata records.

    Args:
        records: List of metadata record dicts (from create_stac_iso_record)
        output_dir: Base output directory for the catalog
        collection: Collection/namespace name

    Returns:
        IcebergTable for the items table
    """
    output_path = Path(output_dir)
    schema = create_stac_iso_schema()

    # Create PyArrow table from records
    arrays = {}
    for field in schema:
        values = [r.get(field.name) for r in records]
        arrays[field.name] = values

    table = pa.table(arrays, schema=schema)

    # Write to parquet
    items_dir = output_path / "data" / collection / "items"
    items_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = items_dir / "items.parquet"
    pq.write_table(table, parquet_path, compression="zstd")

    # Add Iceberg field IDs
    add_iceberg_field_ids(parquet_path)

    # Create IcebergTable
    return parquet_to_iceberg_table(
        str(parquet_path),
        table_name="items",
    )


def extract_raquet_metadata(parquet_path: str | Path) -> dict:
    """
    Extract metadata from a raquet file for STAC+ISO record creation.

    Args:
        parquet_path: Path to raquet parquet file

    Returns:
        Dict with raquet_info and stac bbox/bounds
    """
    pf = pq.ParquetFile(parquet_path)

    # Read metadata row (block = 0)
    table = pq.read_table(parquet_path)

    # Find metadata row
    import pyarrow.compute as pc
    metadata_rows = table.filter(pc.equal(table.column("block"), 0))

    if len(metadata_rows) > 0:
        metadata_json = metadata_rows.column("metadata")[0].as_py()
        if metadata_json:
            metadata = json.loads(metadata_json)

            bands = metadata.get("bands", [])
            bounds = metadata.get("bounds", [])

            return {
                "raquet_info": {
                    "num_bands": len(bands),
                    "band_names": [b.get("name", f"band_{i+1}") for i, b in enumerate(bands)],
                    "compression": metadata.get("compression"),
                    "block_size": metadata.get("block_width", 256),
                    "min_zoom": metadata.get("minresolution"),
                    "max_zoom": metadata.get("maxresolution"),
                    "bounds": bounds,
                },
                "stac_info": {
                    "bbox": bounds,
                },
            }

    return {"raquet_info": {}, "stac_info": {}}


def extract_geoparquet_metadata(parquet_path: str) -> dict:
    """
    Extract metadata from a GeoParquet file.

    Returns:
        Dict with geoparquet_info and stac bbox/bounds
    """
    import geopandas as gpd

    gdf = gpd.read_parquet(parquet_path)

    # Get bounds [minx, miny, maxx, maxy]
    bounds = gdf.total_bounds.tolist()

    # Get geometry types
    geom_types = gdf.geometry.geom_type.unique().tolist()

    # Determine spatial representation
    point_types = {"Point", "MultiPoint"}
    line_types = {"LineString", "MultiLineString"}
    poly_types = {"Polygon", "MultiPolygon"}

    if all(g in point_types for g in geom_types):
        spatial_rep = "point"
    elif all(g in line_types for g in geom_types):
        spatial_rep = "line"
    elif all(g in poly_types for g in geom_types):
        spatial_rep = "polygon"
    else:
        spatial_rep = "mixed"

    return {
        "geoparquet_info": {
            "num_features": len(gdf),
            "geometry_types": geom_types,
            "columns": [c for c in gdf.columns if c != "geometry"],
            "crs": str(gdf.crs) if gdf.crs else "EPSG:4326",
        },
        "stac_info": {
            "bbox": bounds,
        },
        "spatial_representation": spatial_rep,
        "bounds": bounds,
    }


def detect_parquet_type(parquet_path: str) -> str:
    """
    Detect whether a parquet file is Raquet (raster) or GeoParquet (vector).

    Returns:
        "raquet" or "geoparquet"
    """
    pf = pq.ParquetFile(parquet_path)
    columns = pf.schema_arrow.names

    if "block" in columns and "metadata" in columns:
        return "raquet"
    elif "geometry" in columns:
        return "geoparquet"
    else:
        # Default to geoparquet for other parquet files
        return "geoparquet"


def extract_parquet_metadata(parquet_path: str) -> dict:
    """
    Extract metadata from a parquet file, auto-detecting type (Raquet or GeoParquet).

    Returns:
        Dict with file type, metadata info, and stac info
    """
    file_type = detect_parquet_type(parquet_path)

    if file_type == "raquet":
        meta = extract_raquet_metadata(parquet_path)
        return {
            "type": "raquet",
            "format_name": "Raquet",
            "spatial_representation": "grid",
            **meta,
        }
    else:
        meta = extract_geoparquet_metadata(parquet_path)
        return {
            "type": "geoparquet",
            "format_name": "GeoParquet",
            "spatial_representation": meta.get("spatial_representation", "vector"),
            "geoparquet_info": meta.get("geoparquet_info", {}),
            "stac_info": meta.get("stac_info", {}),
            "bounds": meta.get("bounds", []),
        }


def generate_sdi_catalog(
    collections: list[dict],
    output_dir: str,
    data_base_url: str,
    prefix: str = "catalog",
    verbose: bool = False,
) -> dict[str, str]:
    """
    Generate a complete SDI catalog with multiple collections/namespaces.

    Each collection becomes an Iceberg namespace containing:
    - An 'items' table with STAC+ISO metadata
    - Individual tables for each raquet asset

    Args:
        collections: List of collection definitions:
            [
                {
                    "name": "imagery",
                    "title": "Satellite Imagery",
                    "items": [
                        {
                            "id": "europe_rgb",
                            "title": "Europe RGB",
                            "asset_path": "/path/to/file.parquet",
                            "stac_info": {...},
                            "iso_info": {...},
                        }
                    ]
                }
            ]
        output_dir: Directory to write catalog files
        data_base_url: Base URL where data will be served
        prefix: Catalog prefix (default: "catalog")
        verbose: Print progress

    Returns:
        Dict mapping URL paths to created files
    """
    import shutil

    output_path = Path(output_dir)
    all_files = {}

    # Collect all namespaces
    all_namespaces = [c["name"] for c in collections]

    # Create base catalog structure
    v1_dir = output_path / "v1"
    catalog_dir = v1_dir / prefix
    ns_dir = catalog_dir / "namespaces"
    ns_dir.mkdir(parents=True, exist_ok=True)

    # Write /v1/config
    config_data = create_catalog_config(prefix)
    config_path = v1_dir / "config"
    with open(config_path, "w") as f:
        json.dump(config_data, f, indent=2)
    all_files["/v1/config"] = str(config_path)

    # Write /v1/{prefix}/namespaces with all collections
    namespaces_data = create_namespaces_list(all_namespaces)
    namespaces_path = ns_dir / "__list__"
    with open(namespaces_path, "w") as f:
        json.dump(namespaces_data, f, indent=2)
    all_files[f"/v1/{prefix}/namespaces"] = str(namespaces_path)

    # Process each collection
    for collection in collections:
        coll_name = collection["name"]
        coll_title = collection.get("title", coll_name)
        items_config = collection.get("items", [])

        if verbose:
            print(f"Processing collection: {coll_name}")

        # Create namespace directory
        coll_ns_dir = ns_dir / coll_name
        tables_dir = coll_ns_dir / "tables"
        tables_dir.mkdir(parents=True, exist_ok=True)

        # Write namespace detail
        ns_detail = create_namespace_detail(coll_name, {"title": coll_title})
        ns_detail_path = coll_ns_dir / "__detail__"
        with open(ns_detail_path, "w") as f:
            json.dump(ns_detail, f, indent=2)
        all_files[f"/v1/{prefix}/namespaces/{coll_name}"] = str(ns_detail_path)

        # Process items and create metadata records
        metadata_records = []
        raquet_tables = []

        for item in items_config:
            item_id = item["id"]
            item_title = item["title"]
            asset_path = item.get("asset_path")

            if verbose:
                print(f"  Processing item: {item_id}")

            # Extract metadata if asset exists (auto-detects Raquet vs GeoParquet)
            raquet_meta = {}
            geoparquet_meta = {}
            stac_from_file = {}
            file_type = "unknown"
            if asset_path and Path(asset_path).exists():
                extracted = extract_parquet_metadata(asset_path)
                file_type = extracted.get("type", "geoparquet")
                raquet_meta = extracted.get("raquet_info", {})
                geoparquet_meta = extracted.get("geoparquet_info", {})
                stac_from_file = extracted.get("stac_info", {})

                # Copy raquet file to output
                asset_name = item_id.lower().replace(" ", "_").replace("-", "_")
                asset_dir = output_path / "data" / coll_name / asset_name
                asset_dir.mkdir(parents=True, exist_ok=True)
                dest_path = asset_dir / f"{asset_name}.parquet"
                shutil.copy(asset_path, dest_path)

                # Add field IDs and create table
                add_iceberg_field_ids(dest_path)
                raquet_table = parquet_to_iceberg_table(str(dest_path), table_name=asset_name)
                raquet_tables.append(raquet_table)

                # Update asset URL in STAC info
                asset_url = f"{data_base_url.rstrip('/')}/data/{coll_name}/{asset_name}/{asset_name}.parquet"
                stac_info = item.get("stac_info", {})
                stac_info.setdefault("assets", {})
                stac_info["assets"]["data"] = {
                    "href": asset_url,
                    "type": "application/x-parquet",
                    "title": item_title,
                }
                # Merge bbox from file if not provided
                if not stac_info.get("bbox") and stac_from_file.get("bbox"):
                    stac_info["bbox"] = stac_from_file["bbox"]

                item["stac_info"] = stac_info

            # Merge raquet info
            item_raquet = {**raquet_meta, **item.get("raquet_info", {})}

            # Create metadata record
            record = create_stac_iso_record(
                item_id=item_id,
                title=item_title,
                stac_info=item.get("stac_info"),
                iso_info=item.get("iso_info"),
                raquet_info=item_raquet if item_raquet else None,
            )
            metadata_records.append(record)

        # Create items table from metadata records
        if metadata_records:
            items_table = create_items_table(metadata_records, output_dir, coll_name)
            all_tables = [items_table] + raquet_tables
        else:
            all_tables = raquet_tables

        # Write tables list
        table_names = [t.name for t in all_tables]
        tables_list = create_tables_list(table_names, coll_name)
        tables_list_path = coll_ns_dir / "tables__list__"
        with open(tables_list_path, "w") as f:
            json.dump(tables_list, f, indent=2)
        all_files[f"/v1/{prefix}/namespaces/{coll_name}/tables"] = str(tables_list_path)

        # Write each table's metadata
        for table in all_tables:
            table_uuid = str(uuid.uuid4())
            # Include collection name in table path
            full_table_path = f"{coll_name}/{table.name}"
            metadata = create_table_metadata(table, data_base_url, table_uuid, table_path=full_table_path)
            metadata_location = f"{data_base_url.rstrip('/')}/data/{coll_name}/{table.name}/metadata/v1.metadata.json"
            load_response = create_load_table_response(table, metadata, metadata_location)

            # Write table endpoint
            table_endpoint_path = tables_dir / table.name
            with open(table_endpoint_path, "w") as f:
                json.dump(load_response, f, indent=2)
            all_files[f"/v1/{prefix}/namespaces/{coll_name}/tables/{table.name}"] = str(table_endpoint_path)

            # Write standalone metadata
            table_meta_dir = output_path / "data" / coll_name / table.name / "metadata"
            table_meta_dir.mkdir(parents=True, exist_ok=True)
            meta_file = table_meta_dir / "v1.metadata.json"
            with open(meta_file, "w") as f:
                json.dump(metadata, f, indent=2)

            # Generate manifest files
            generate_manifest_files(table, data_base_url, table_meta_dir, table.arrow_schema, table_path=full_table_path)

            if verbose:
                print(f"  Created table: {table.name}")

    print(f"Generated SDI catalog with {len(collections)} collections")
    return all_files
