"""
Core Iceberg table metadata, type conversion, and manifest generation.

This module handles:
- Arrow-to-Iceberg type conversion (two systems, see note below)
- Iceberg table metadata creation with name-mapping for "lightweight Iceberg"
- Manifest and manifest-list Avro file generation via pyiceberg
- Parquet field ID management

Type Conversion Systems:
    System A (_arrow_type_to_pyiceberg): Returns pyiceberg type objects.
        Used by manifest generation which requires pyiceberg Schema objects.
    System B (_arrow_type_to_iceberg): Returns JSON-serializable dicts.
        Used by REST catalog metadata which needs dict representations.
    Both systems exist because they serve different consumers - pyiceberg's
    manifest writer vs JSON serialization for REST endpoints. They handle
    the same set of Arrow types but return different representations.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from pyiceberg.manifest import (
    DataFile,
    DataFileContent,
    FileFormat,
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


# =============================================================================
# System A: Arrow → pyiceberg types (used by manifest generation)
# =============================================================================


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


# =============================================================================
# System B: Arrow → Iceberg JSON dicts (used by REST catalog metadata)
# =============================================================================


def _arrow_type_to_iceberg(arrow_type) -> dict:
    """Convert PyArrow type to Iceberg type representation (JSON-serializable dict)."""
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


# =============================================================================
# Manifest generation
# =============================================================================


def generate_manifest_files(
    table: IcebergTable,
    data_base_url: str,
    metadata_dir: Path,
    arrow_schema: pa.Schema,
    snapshot_id: int = 1,
    sequence_number: int = 1,
    table_path: str | None = None,
    data_file_path: str | None = None,
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
        data_file_path: Optional full path to the data file. If not provided, constructs from table_path.

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

    # Create data file entry - use provided path or construct default
    if data_file_path is None:
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


# =============================================================================
# Name mapping & table metadata
# =============================================================================


def create_name_mapping(schema: dict) -> str:
    """
    Create Iceberg name-mapping JSON from schema.

    The name mapping tells Iceberg readers how to match columns by name
    when field IDs are not present in the Parquet file. This enables
    "lightweight Iceberg" - registering existing Parquet files without rewriting them.

    Args:
        schema: Iceberg schema dict with "fields" list

    Returns:
        JSON string of name mapping: [{"field-id": 1, "names": ["col1"]}, ...]
    """
    mapping = []
    for field in schema.get("fields", []):
        mapping.append({
            "field-id": field["id"],
            "names": [field["name"]],
        })
    return json.dumps(mapping)


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
            # Name mapping enables "lightweight Iceberg" - no Parquet rewrite needed
            # Readers match columns by name instead of field ID
            "schema.name-mapping.default": create_name_mapping(table.schema),
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


# =============================================================================
# Parquet field ID management
# =============================================================================


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
