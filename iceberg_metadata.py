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
    ListType,
    LongType,
    MapType,
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
    counter = [0]  # mutable counter for unique field IDs

    def next_id():
        counter[0] += 1
        return counter[0]

    fields = []
    for field in arrow_schema:
        iceberg_type = _arrow_type_to_pyiceberg(field.type, next_id)
        if iceberg_type is not None:
            fields.append(
                NestedField(
                    field_id=next_id(),
                    name=field.name,
                    field_type=iceberg_type,
                    required=not field.nullable,
                )
            )
    return Schema(*fields)


def _arrow_type_to_pyiceberg(arrow_type, next_id):
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
        for subfield in arrow_type:
            subtype = _arrow_type_to_pyiceberg(subfield.type, next_id)
            if subtype is not None:
                nested_fields.append(
                    NestedField(
                        field_id=next_id(),
                        name=subfield.name,
                        field_type=subtype,
                        required=not subfield.nullable,
                    )
                )
        return StructType(*nested_fields) if nested_fields else None
    if pa.types.is_list(arrow_type) or pa.types.is_large_list(arrow_type):
        element_type = _arrow_type_to_pyiceberg(arrow_type.value_type, next_id)
        if element_type is None:
            element_type = StringType()
        return ListType(
            element_id=next_id(),
            element_type=element_type,
            element_required=False,
        )
    if pa.types.is_map(arrow_type):
        key_type = _arrow_type_to_pyiceberg(arrow_type.key_type, next_id)
        key_id = next_id()
        value_type = _arrow_type_to_pyiceberg(arrow_type.item_type, next_id)
        value_id = next_id()
        if key_type is None:
            key_type = StringType()
        if value_type is None:
            value_type = StringType()
        return MapType(
            key_id=key_id,
            key_type=key_type,
            value_id=value_id,
            value_type=value_type,
            value_required=False,
        )
    # Default fallback for unknown types
    return StringType()


# =============================================================================
# System B: Arrow → Iceberg JSON dicts (used by REST catalog metadata)
# =============================================================================


def _arrow_type_to_iceberg(arrow_type, next_id) -> dict | str:
    """Convert PyArrow type to Iceberg type representation (JSON-serializable).

    Returns a string for primitive types (e.g., "string", "int") or a dict
    for complex types (struct, list, map).
    """
    if pa.types.is_boolean(arrow_type):
        return "boolean"
    if pa.types.is_int8(arrow_type) or pa.types.is_int16(arrow_type):
        return "int"
    if pa.types.is_int32(arrow_type):
        return "int"
    if pa.types.is_int64(arrow_type):
        return "long"
    if pa.types.is_uint8(arrow_type) or pa.types.is_uint16(arrow_type):
        return "int"
    if pa.types.is_uint32(arrow_type):
        return "long"
    if pa.types.is_uint64(arrow_type):
        return "long"
    if pa.types.is_float16(arrow_type) or pa.types.is_float32(arrow_type):
        return "float"
    if pa.types.is_float64(arrow_type):
        return "double"
    if pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type):
        return "string"
    if pa.types.is_binary(arrow_type) or pa.types.is_large_binary(arrow_type):
        return "binary"
    if pa.types.is_date(arrow_type):
        return "date"
    if pa.types.is_timestamp(arrow_type):
        return "timestamp"
    if pa.types.is_time(arrow_type):
        return "time"

    if pa.types.is_list(arrow_type) or pa.types.is_large_list(arrow_type):
        element_type = _arrow_type_to_iceberg(arrow_type.value_type, next_id)
        return {
            "type": "list",
            "element-id": next_id(),
            "element": element_type,
            "element-required": False,
        }

    if pa.types.is_struct(arrow_type):
        fields = []
        for field in arrow_type:
            field_type = _arrow_type_to_iceberg(field.type, next_id)
            fields.append({
                "id": next_id(),
                "name": field.name,
                "required": not field.nullable,
                "type": field_type,
            })
        return {"type": "struct", "fields": fields}

    if pa.types.is_map(arrow_type):
        key_type = _arrow_type_to_iceberg(arrow_type.key_type, next_id)
        key_id = next_id()
        value_type = _arrow_type_to_iceberg(arrow_type.item_type, next_id)
        value_id = next_id()
        return {
            "type": "map",
            "key-id": key_id,
            "key": key_type,
            "value-id": value_id,
            "value": value_type,
            "value-required": False,
        }

    return "string"


def _arrow_schema_to_iceberg(schema) -> dict:
    """Convert PyArrow schema to Iceberg schema format."""
    counter = [0]

    def next_id():
        counter[0] += 1
        return counter[0]

    fields = []
    for field in schema:
        iceberg_type = _arrow_type_to_iceberg(field.type, next_id)
        fields.append({
            "id": next_id(),
            "name": field.name,
            "required": not field.nullable,
            "type": iceberg_type,
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
    data_files: list[dict] | None = None,
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
        data_files: Optional list of dicts with {path, size, record_count} for multi-file datasets.
                    When provided, overrides data_file_path and table's file info.

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

    # Build manifest entries
    manifest_entries = []

    if data_files:
        # Multi-file dataset (e.g., remote partitioned Parquet)
        for df in data_files:
            data_file = DataFile.from_args(
                content=DataFileContent.DATA,
                file_path=df["path"],
                file_format=FileFormat.PARQUET,
                partition=Record(),
                record_count=df.get("record_count", 0),
                file_size_in_bytes=df.get("size", 0),
            )
            manifest_entries.append(ManifestEntry.from_args(
                status=ManifestEntryStatus.ADDED,
                snapshot_id=snapshot_id,
                sequence_number=sequence_number,
                file_sequence_number=sequence_number,
                data_file=data_file,
            ))
    else:
        # Single-file dataset
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
        manifest_entries.append(ManifestEntry.from_args(
            status=ManifestEntryStatus.ADDED,
            snapshot_id=snapshot_id,
            sequence_number=sequence_number,
            file_sequence_number=sequence_number,
            data_file=data_file,
        ))

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
        for entry in manifest_entries:
            manifest_writer.add_entry(entry)
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


def _max_field_id(schema: dict) -> int:
    """Find the maximum field ID in an Iceberg schema (including nested fields)."""
    max_id = 0
    for field in schema.get("fields", []):
        max_id = max(max_id, field.get("id", 0))
        field_type = field.get("type")
        if isinstance(field_type, dict):
            max_id = max(max_id, _max_field_id_from_type(field_type))
    return max_id


def _max_field_id_from_type(type_def: dict) -> int:
    """Recursively find max field ID in a type definition."""
    max_id = 0
    if type_def.get("type") == "struct":
        for f in type_def.get("fields", []):
            max_id = max(max_id, f.get("id", 0))
            if isinstance(f.get("type"), dict):
                max_id = max(max_id, _max_field_id_from_type(f["type"]))
    elif type_def.get("type") == "list":
        max_id = max(max_id, type_def.get("element-id", 0))
        if isinstance(type_def.get("element"), dict):
            max_id = max(max_id, _max_field_id_from_type(type_def["element"]))
    elif type_def.get("type") == "map":
        max_id = max(max_id, type_def.get("key-id", 0), type_def.get("value-id", 0))
        if isinstance(type_def.get("key"), dict):
            max_id = max(max_id, _max_field_id_from_type(type_def["key"]))
        if isinstance(type_def.get("value"), dict):
            max_id = max(max_id, _max_field_id_from_type(type_def["value"]))
    return max_id


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
    _collect_name_mappings(schema.get("fields", []), mapping)
    return json.dumps(mapping)


def _collect_name_mappings(fields: list[dict], mapping: list[dict]):
    """Recursively collect name mappings for all fields including nested ones."""
    for field in fields:
        entry = {"field-id": field["id"], "names": [field["name"]]}
        field_type = field.get("type")
        if isinstance(field_type, dict):
            nested = []
            _collect_type_mappings(field_type, nested)
            if nested:
                entry["fields"] = nested
        mapping.append(entry)


def _collect_type_mappings(type_def: dict, mapping: list[dict]):
    """Recursively collect name mappings from a type definition."""
    type_name = type_def.get("type")
    if type_name == "struct":
        for f in type_def.get("fields", []):
            entry = {"field-id": f["id"], "names": [f["name"]]}
            ft = f.get("type")
            if isinstance(ft, dict):
                nested = []
                _collect_type_mappings(ft, nested)
                if nested:
                    entry["fields"] = nested
            mapping.append(entry)
    elif type_name == "list":
        elem = type_def.get("element")
        entry = {"field-id": type_def["element-id"], "names": ["element"]}
        if isinstance(elem, dict):
            nested = []
            _collect_type_mappings(elem, nested)
            if nested:
                entry["fields"] = nested
        mapping.append(entry)
    elif type_name == "map":
        key = type_def.get("key")
        key_entry = {"field-id": type_def["key-id"], "names": ["key"]}
        if isinstance(key, dict):
            nested = []
            _collect_type_mappings(key, nested)
            if nested:
                key_entry["fields"] = nested
        mapping.append(key_entry)
        value = type_def.get("value")
        value_entry = {"field-id": type_def["value-id"], "names": ["value"]}
        if isinstance(value, dict):
            nested = []
            _collect_type_mappings(value, nested)
            if nested:
                value_entry["fields"] = nested
        mapping.append(value_entry)


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
        "last-column-id": _max_field_id(table.schema),
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
