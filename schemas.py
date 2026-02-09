"""
JSON Schema definitions and validation for Portolan data models.

This module provides:
- Schema definitions for Resource, CatalogConfig, LocalState, and Manifest
- Validation functions that return lists of error messages
- File-level validation utilities
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError


# =============================================================================
# Schema Definitions
# =============================================================================

ORIGIN_SCHEMA = {
    "type": "object",
    "required": ["type"],
    "properties": {
        "type": {
            "type": "string",
            "enum": [
                "file",
                "wfs",
                "arcgis_featureserver",
                "arcgis_imageserver",
                "stac",
                "oracle",
                "postgres",
                "pointcloud",
            ],
        },
        "url": {"type": "string"},
        "layer": {"type": "string"},
        "connection_ref": {"type": "string"},
        "stac_collection": {"type": "string"},
        "stac_item_id": {"type": "string"},
    },
    "additionalProperties": False,
}

SNAPSHOT_ASSET_SCHEMA = {
    "type": "object",
    "required": ["href", "type", "taken_at", "format"],
    "properties": {
        "href": {"type": "string"},
        "type": {"type": "string"},
        "taken_at": {"type": "string"},
        "format": {"type": "string", "enum": ["geoparquet", "cog", "zarr", "parquet", "raquet"]},
        "source_fingerprint": {"type": "object"},
    },
    "additionalProperties": False,
}

ICEBERG_ASSET_SCHEMA = {
    "type": "object",
    "required": ["metadata"],
    "properties": {
        "metadata": {"type": "string"},
    },
    "additionalProperties": False,
}

ASSETS_SCHEMA = {
    "type": "object",
    "properties": {
        "snapshot": SNAPSHOT_ASSET_SCHEMA,
        "iceberg": ICEBERG_ASSET_SCHEMA,
        "data": {"type": "object"},  # Legacy field
    },
    "additionalProperties": False,
}

USER_METADATA_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "license": {"type": "string"},
        "attribution": {"type": "string"},
        "properties": {"type": "object"},
    },
    "additionalProperties": False,
}

SOURCE_METADATA_SCHEMA = {
    "type": "object",
    "required": ["provider"],
    "properties": {
        "provider": {"type": "string"},
        "ref": {"type": "object"},
        "fetched_at": {"type": "string"},
        "hash": {"type": "string"},
        "data": {"type": "object"},
    },
    "additionalProperties": False,
}

DERIVED_METADATA_SCHEMA = {
    "type": "object",
    "properties": {
        "schema_hash": {"type": "string"},
        "previous_schema_hash": {"type": "string"},
        "schema_changed_at": {"type": "string", "format": "date-time"},
        "row_count": {"type": "integer", "minimum": 0},
        "bbox": {
            "type": "array",
            "items": {"type": "number"},
            "minItems": 4,
            "maxItems": 4,
        },
        "geometry_type": {"type": "string"},
        "crs": {"type": "string"},
        "files": {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "minimum": 0},
                "bytes": {"type": "integer", "minimum": 0},
            },
        },
    },
    "additionalProperties": False,
}

SYNC_CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "mode": {"type": "string", "enum": ["manual", "auto"]},
        "strategy": {"type": "string", "enum": ["update_source_only", "update_missing_fields"]},
    },
    "additionalProperties": False,
}

RESOURCE_METADATA_SCHEMA = {
    "type": "object",
    "properties": {
        "user": USER_METADATA_SCHEMA,
        "source": SOURCE_METADATA_SCHEMA,
        "derived": DERIVED_METADATA_SCHEMA,
        "sync": SYNC_CONFIG_SCHEMA,
    },
    "additionalProperties": False,
}

UPSTREAM_SCHEMA = {
    "type": "object",
    "required": ["catalog", "type", "id"],
    "properties": {
        "catalog": {"type": "string"},
        "type": {"type": "string"},
        "id": {"type": "string"},
    },
    "additionalProperties": False,
}

RESOURCE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://portolan.dev/schemas/resource.schema.json",
    "title": "Portolan Resource",
    "description": "A resource in the Portolan catalog with lifecycle states",
    "type": "object",
    "required": ["name", "kind"],
    "properties": {
        "name": {
            "type": "string",
            "pattern": "^[a-z][a-z0-9_]*$",
            "description": "Resource identifier (lowercase letters, numbers, underscores; must start with letter)",
        },
        "kind": {
            "type": "string",
            "enum": ["vector", "raster", "table", "collection"],
            "description": "Type of spatial data",
        },
        "origin": {"$ref": "#/$defs/Origin"},
        "assets": {"$ref": "#/$defs/Assets"},
        "metadata": {"$ref": "#/$defs/ResourceMetadata"},
        "upstream": {"$ref": "#/$defs/Upstream"},
        "created_at": {"type": "string", "format": "date-time"},
        "updated_at": {"type": "string", "format": "date-time"},
    },
    "$defs": {
        "Origin": ORIGIN_SCHEMA,
        "Assets": ASSETS_SCHEMA,
        "ResourceMetadata": RESOURCE_METADATA_SCHEMA,
        "Upstream": UPSTREAM_SCHEMA,
    },
}

SYNC_POLICY_SCHEMA = {
    "type": "object",
    "description": "Control plane policy for sync operations",
    "properties": {
        "max_retries": {"type": "integer", "minimum": 0, "default": 3},
        "retry_backoff": {
            "type": "string",
            "enum": ["exponential", "linear", "fixed"],
            "default": "exponential",
        },
        "retry_delay_seconds": {"type": "number", "minimum": 0, "default": 2.0},
        "timeout_seconds": {"type": "number", "minimum": 0, "default": 300.0},
        "on_failure": {
            "type": "string",
            "enum": ["log", "webhook"],
            "default": "log",
        },
        "webhook_url": {"type": "string", "format": "uri"},
    },
    "additionalProperties": False,
}

CONFIG_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://portolan.dev/schemas/config.schema.json",
    "title": "Portolan Catalog Config",
    "description": "Configuration for a Portolan catalog",
    "type": "object",
    "properties": {
        "outputs": {
            "type": "object",
            "description": "Which output formats to generate",
            "properties": {
                "iceberg": {"type": "boolean", "default": True},
                "stac": {"type": "boolean", "default": True},
                "iso19139": {"type": "boolean", "default": True},
                "ducklake": {"type": "boolean", "default": True},
                "web": {"type": "boolean", "default": True},
            },
            "additionalProperties": False,
        },
        "sync_policy": SYNC_POLICY_SCHEMA,
    },
    "additionalProperties": False,
}

STATE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://portolan.dev/schemas/state.schema.json",
    "title": "Portolan Local State",
    "description": "Local state for sync operations",
    "type": "object",
    "properties": {
        "remote_url": {
            "type": ["string", "null"],
            "description": "Remote storage URL (gs://, s3://, file://, or https://)",
        },
        "base_manifest_hash": {
            "type": ["string", "null"],
            "pattern": "^[a-f0-9]{64}$",
            "description": "SHA-256 hash of the base manifest",
        },
    },
    "additionalProperties": False,
}

MANIFEST_ENTRY_SCHEMA = {
    "type": "object",
    "required": ["path", "hash", "size"],
    "properties": {
        "path": {"type": "string"},
        "hash": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "size": {"type": "integer", "minimum": 0},
    },
    "additionalProperties": False,
}

MANIFEST_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://portolan.dev/schemas/manifest.schema.json",
    "title": "Portolan Manifest",
    "description": "File manifest for sync operations",
    "type": "object",
    "required": ["version", "files"],
    "properties": {
        "version": {"type": "integer", "const": 1},
        "files": {
            "type": "array",
            "items": MANIFEST_ENTRY_SCHEMA,
        },
        "created_at": {"type": "string", "format": "date-time"},
    },
    "additionalProperties": False,
}


# =============================================================================
# Validators (cached for performance)
# =============================================================================

_resource_validator: Draft202012Validator | None = None
_config_validator: Draft202012Validator | None = None
_state_validator: Draft202012Validator | None = None
_manifest_validator: Draft202012Validator | None = None


def _get_resource_validator() -> Draft202012Validator:
    global _resource_validator
    if _resource_validator is None:
        _resource_validator = Draft202012Validator(RESOURCE_SCHEMA)
    return _resource_validator


def _get_config_validator() -> Draft202012Validator:
    global _config_validator
    if _config_validator is None:
        _config_validator = Draft202012Validator(CONFIG_SCHEMA)
    return _config_validator


def _get_state_validator() -> Draft202012Validator:
    global _state_validator
    if _state_validator is None:
        _state_validator = Draft202012Validator(STATE_SCHEMA)
    return _state_validator


def _get_manifest_validator() -> Draft202012Validator:
    global _manifest_validator
    if _manifest_validator is None:
        _manifest_validator = Draft202012Validator(MANIFEST_SCHEMA)
    return _manifest_validator


# =============================================================================
# Validation Functions
# =============================================================================


def validate_resource(data: dict[str, Any]) -> list[str]:
    """
    Validate a resource dictionary against the schema.

    Args:
        data: Resource data as a dictionary

    Returns:
        List of error messages (empty if valid)
    """
    validator = _get_resource_validator()
    errors = []
    for error in validator.iter_errors(data):
        path = ".".join(str(p) for p in error.absolute_path) if error.absolute_path else "root"
        errors.append(f"{path}: {error.message}")
    return errors


def validate_config(data: dict[str, Any]) -> list[str]:
    """
    Validate a catalog config dictionary against the schema.

    Args:
        data: Config data as a dictionary

    Returns:
        List of error messages (empty if valid)
    """
    validator = _get_config_validator()
    errors = []
    for error in validator.iter_errors(data):
        path = ".".join(str(p) for p in error.absolute_path) if error.absolute_path else "root"
        errors.append(f"{path}: {error.message}")
    return errors


def validate_state(data: dict[str, Any]) -> list[str]:
    """
    Validate a local state dictionary against the schema.

    Args:
        data: State data as a dictionary

    Returns:
        List of error messages (empty if valid)
    """
    validator = _get_state_validator()
    errors = []
    for error in validator.iter_errors(data):
        path = ".".join(str(p) for p in error.absolute_path) if error.absolute_path else "root"
        errors.append(f"{path}: {error.message}")
    return errors


def validate_manifest(data: dict[str, Any]) -> list[str]:
    """
    Validate a manifest dictionary against the schema.

    Args:
        data: Manifest data as a dictionary

    Returns:
        List of error messages (empty if valid)
    """
    validator = _get_manifest_validator()
    errors = []
    for error in validator.iter_errors(data):
        path = ".".join(str(p) for p in error.absolute_path) if error.absolute_path else "root"
        errors.append(f"{path}: {error.message}")
    return errors


# =============================================================================
# Namespace Validation
# =============================================================================


def validate_namespace_name(namespace: str) -> list[str]:
    """
    Validate a namespace string.

    Args:
        namespace: Namespace identifier (e.g., "default", "europe.spain.madrid")

    Returns:
        List of error messages (empty if valid)
    """
    from namespace_utils import validate_namespace

    error = validate_namespace(namespace)
    return [error] if error else []


# =============================================================================
# File Validation Functions
# =============================================================================


def validate_resource_file(path: Path) -> list[str]:
    """
    Load and validate a resource JSON file.

    Args:
        path: Path to the resource JSON file

    Returns:
        List of error messages (empty if valid)
    """
    try:
        with open(path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return [f"Invalid JSON: {e}"]
    except FileNotFoundError:
        return [f"File not found: {path}"]

    return validate_resource(data)


def validate_config_file(path: Path) -> list[str]:
    """
    Load and validate a config JSON file.

    Args:
        path: Path to the config JSON file

    Returns:
        List of error messages (empty if valid)
    """
    try:
        with open(path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return [f"Invalid JSON: {e}"]
    except FileNotFoundError:
        return [f"File not found: {path}"]

    return validate_config(data)


def validate_state_file(path: Path) -> list[str]:
    """
    Load and validate a state JSON file.

    Args:
        path: Path to the state JSON file

    Returns:
        List of error messages (empty if valid)
    """
    try:
        with open(path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return [f"Invalid JSON: {e}"]
    except FileNotFoundError:
        return [f"File not found: {path}"]

    return validate_state(data)


def validate_catalog(portolan_dir: Path) -> dict[str, list[str]]:
    """
    Validate all files in a Portolan catalog.

    Args:
        portolan_dir: Path to the .portolan directory

    Returns:
        Dictionary mapping file paths to their validation errors
        (only includes files with errors)
    """
    all_errors: dict[str, list[str]] = {}

    # Validate config.json
    config_path = portolan_dir / "config.json"
    if config_path.exists():
        errors = validate_config_file(config_path)
        if errors:
            all_errors[str(config_path)] = errors

    # Validate state.json
    state_path = portolan_dir / "state.json"
    if state_path.exists():
        errors = validate_state_file(state_path)
        if errors:
            all_errors[str(state_path)] = errors

    # Validate all resource files
    resources_dir = portolan_dir / "resources"
    if resources_dir.exists():
        for resource_file in resources_dir.rglob("*.json"):
            errors = validate_resource_file(resource_file)
            if errors:
                all_errors[str(resource_file)] = errors

    return all_errors
