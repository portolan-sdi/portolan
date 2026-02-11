"""
Tests for JSON Schema validation.
"""

import json
import tempfile
from pathlib import Path

import pytest

from schemas import (
    validate_catalog,
    validate_config,
    validate_config_file,
    validate_manifest,
    validate_resource,
    validate_resource_file,
    validate_state,
    validate_state_file,
)


class TestResourceValidation:
    """Test suite for resource schema validation."""

    def test_valid_minimal_resource(self):
        """Test validation of minimal valid resource."""
        data = {"name": "test_resource", "kind": "vector"}
        errors = validate_resource(data)
        assert errors == []

    def test_valid_full_resource(self):
        """Test validation of full resource with all fields."""
        data = {
            "name": "cities",
            "kind": "vector",
            "origin": {"type": "file", "url": "/path/to/data.parquet"},
            "assets": {
                "snapshot": {
                    "href": "data/raw/default/cities/data.parquet",
                    "type": "application/vnd.apache.parquet",
                    "taken_at": "2024-01-01T00:00:00Z",
                    "format": "geoparquet",
                },
                "iceberg": {"metadata": "data/default/cities/metadata/v1.metadata.json"},
            },
            "metadata": {
                "user": {
                    "title": "Major Cities",
                    "description": "Population data for major cities",
                    "tags": ["cities", "population"],
                },
                "derived": {
                    "row_count": 100,
                    "bbox": [-180, -90, 180, 90],
                    "geometry_type": "Point",
                    "crs": "EPSG:4326",
                },
                "sync": {"mode": "manual", "strategy": "update_source_only"},
            },
            "created_at": "2024-01-01T00:00:00Z",
        }
        errors = validate_resource(data)
        assert errors == []

    def test_invalid_name_starts_with_number(self):
        """Test that name starting with number fails."""
        data = {"name": "123invalid", "kind": "vector"}
        errors = validate_resource(data)
        assert len(errors) == 1
        assert "name" in errors[0]
        assert "match" in errors[0].lower() or "pattern" in errors[0].lower()

    def test_invalid_name_uppercase(self):
        """Test that uppercase name fails."""
        data = {"name": "InvalidName", "kind": "vector"}
        errors = validate_resource(data)
        assert len(errors) == 1
        assert "name" in errors[0]

    def test_invalid_kind(self):
        """Test that invalid kind fails."""
        data = {"name": "test", "kind": "unknown"}
        errors = validate_resource(data)
        assert len(errors) == 1
        assert "kind" in errors[0]
        assert "enum" in errors[0].lower() or "unknown" in errors[0]

    def test_missing_required_name(self):
        """Test that missing name fails."""
        data = {"kind": "vector"}
        errors = validate_resource(data)
        assert len(errors) == 1
        assert "name" in errors[0]

    def test_missing_required_kind(self):
        """Test that missing kind fails."""
        data = {"name": "test"}
        errors = validate_resource(data)
        assert len(errors) == 1
        assert "kind" in errors[0]

    def test_invalid_origin_type(self):
        """Test that invalid origin type fails."""
        data = {
            "name": "test",
            "kind": "vector",
            "origin": {"type": "invalid_type"},
        }
        errors = validate_resource(data)
        assert len(errors) == 1
        assert "origin" in errors[0] or "type" in errors[0]

    def test_valid_origin_types(self):
        """Test all valid origin types."""
        valid_types = [
            "file",
            "wfs",
            "arcgis_featureserver",
            "arcgis_imageserver",
            "stac",
            "oracle",
            "postgres",
            "pointcloud",
            "tiles",
        ]
        for origin_type in valid_types:
            data = {
                "name": "test",
                "kind": "vector",
                "origin": {"type": origin_type},
            }
            errors = validate_resource(data)
            assert errors == [], f"Origin type '{origin_type}' should be valid"

    def test_invalid_bbox_length(self):
        """Test that bbox with wrong length fails."""
        data = {
            "name": "test",
            "kind": "vector",
            "metadata": {"derived": {"bbox": [-180, -90, 180]}},  # Missing north
        }
        errors = validate_resource(data)
        assert len(errors) == 1
        assert "bbox" in errors[0]

    def test_invalid_sync_mode(self):
        """Test that invalid sync mode fails."""
        data = {
            "name": "test",
            "kind": "vector",
            "metadata": {"sync": {"mode": "invalid_mode"}},
        }
        errors = validate_resource(data)
        assert len(errors) == 1
        assert "mode" in errors[0]


class TestUserMetadataProperties:
    """Test suite for user metadata properties bag."""

    def test_valid_resource_with_properties(self):
        """Properties bag validates."""
        data = {
            "name": "test",
            "kind": "vector",
            "metadata": {
                "user": {
                    "title": "Test",
                    "properties": {
                        "contact_email": "test@example.com",
                        "topic_category": "boundaries",
                        "spatial_resolution": 100,
                    },
                },
            },
        }
        errors = validate_resource(data)
        assert errors == []

    def test_unknown_top_level_keys_rejected(self):
        """Unknown keys at user metadata level are still rejected."""
        data = {
            "name": "test",
            "kind": "vector",
            "metadata": {
                "user": {
                    "title": "Test",
                    "unknown_field": "should fail",
                },
            },
        }
        errors = validate_resource(data)
        assert len(errors) == 1

    def test_properties_accepts_any_values(self):
        """Properties dict accepts any value types."""
        data = {
            "name": "test",
            "kind": "vector",
            "metadata": {
                "user": {
                    "properties": {
                        "string_val": "hello",
                        "number_val": 42,
                        "bool_val": True,
                        "list_val": ["a", "b"],
                        "nested_val": {"key": "value"},
                    },
                },
            },
        }
        errors = validate_resource(data)
        assert errors == []


class TestDerivedColumnsValidation:
    """Test suite for derived columns schema validation."""

    def test_valid_columns(self):
        """Test resource with valid derived columns."""
        data = {
            "name": "test",
            "kind": "vector",
            "metadata": {
                "derived": {
                    "columns": [
                        {"name": "id", "type": "int64", "nullable": False},
                        {"name": "geom", "type": "geometry", "nullable": True, "geometry_type": "Point", "crs": "EPSG:4326"},
                    ],
                },
            },
        }
        errors = validate_resource(data)
        assert errors == []

    def test_columns_missing_required(self):
        """Test columns entry missing required name/type."""
        data = {
            "name": "test",
            "kind": "vector",
            "metadata": {
                "derived": {
                    "columns": [{"name": "id"}],  # missing type
                },
            },
        }
        errors = validate_resource(data)
        assert len(errors) == 1

    def test_columns_rejects_extra_properties(self):
        """Test that unknown properties in columns are rejected."""
        data = {
            "name": "test",
            "kind": "vector",
            "metadata": {
                "derived": {
                    "columns": [{"name": "id", "type": "int64", "unknown_field": "x"}],
                },
            },
        }
        errors = validate_resource(data)
        assert len(errors) == 1


class TestConfigValidation:
    """Test suite for config schema validation."""

    def test_valid_config(self):
        """Test validation of valid config with nested outputs."""
        data = {
            "outputs": {
                "metadata": {
                    "stac": True,
                    "iso19139": True,
                    "web": True,
                    "iceberg": True,
                },
                "data": {
                    "iceberg": True,
                    "ducklake": True,
                },
            }
        }
        errors = validate_config(data)
        assert errors == []

    def test_valid_partial_config(self):
        """Test validation of partial config."""
        data = {"outputs": {"metadata": {"stac": True}}}
        errors = validate_config(data)
        assert errors == []

    def test_valid_empty_config(self):
        """Test validation of empty config."""
        data = {}
        errors = validate_config(data)
        assert errors == []

    def test_valid_object_output_value(self):
        """Test that object values with 'enabled' are valid."""
        data = {
            "outputs": {
                "data": {
                    "iceberg": {"enabled": True},
                },
            }
        }
        errors = validate_config(data)
        assert errors == []

    def test_invalid_output_type(self):
        """Test that non-boolean, non-object output fails."""
        data = {"outputs": {"metadata": {"stac": "yes"}}}
        errors = validate_config(data)
        assert len(errors) >= 1

    def test_invalid_extra_metadata_output(self):
        """Test that unknown metadata output key fails."""
        data = {"outputs": {"metadata": {"unknown_output": True}}}
        errors = validate_config(data)
        assert len(errors) == 1

    def test_invalid_extra_data_output(self):
        """Test that unknown data output key fails."""
        data = {"outputs": {"data": {"unknown_output": True}}}
        errors = validate_config(data)
        assert len(errors) == 1

    def test_invalid_extra_top_level_output(self):
        """Test that unknown top-level output key fails."""
        data = {"outputs": {"unknown_section": {}}}
        errors = validate_config(data)
        assert len(errors) == 1


class TestStateValidation:
    """Test suite for state schema validation."""

    def test_valid_state(self):
        """Test validation of valid state."""
        data = {
            "remote_url": "gs://bucket/path",
            "base_manifest_hash": "a" * 64,
        }
        errors = validate_state(data)
        assert errors == []

    def test_valid_null_values(self):
        """Test validation of null values."""
        data = {"remote_url": None, "base_manifest_hash": None}
        errors = validate_state(data)
        assert errors == []

    def test_valid_empty_state(self):
        """Test validation of empty state."""
        data = {}
        errors = validate_state(data)
        assert errors == []

    def test_invalid_hash_length(self):
        """Test that invalid hash length fails."""
        data = {"base_manifest_hash": "abc123"}  # Too short
        errors = validate_state(data)
        assert len(errors) == 1
        assert "hash" in errors[0].lower() or "pattern" in errors[0].lower()

    def test_invalid_hash_characters(self):
        """Test that invalid hash characters fail."""
        data = {"base_manifest_hash": "g" * 64}  # 'g' is not hex
        errors = validate_state(data)
        assert len(errors) == 1


class TestManifestValidation:
    """Test suite for manifest schema validation."""

    def test_valid_manifest(self):
        """Test validation of valid manifest."""
        data = {
            "version": 1,
            "files": [
                {"path": "data/test.parquet", "hash": "a" * 64, "size": 1024},
                {"path": "config.json", "hash": "b" * 64, "size": 256},
            ],
            "created_at": "2024-01-01T00:00:00Z",
        }
        errors = validate_manifest(data)
        assert errors == []

    def test_valid_empty_files(self):
        """Test validation of manifest with empty files."""
        data = {"version": 1, "files": []}
        errors = validate_manifest(data)
        assert errors == []

    def test_missing_version(self):
        """Test that missing version fails."""
        data = {"files": []}
        errors = validate_manifest(data)
        assert len(errors) == 1
        assert "version" in errors[0]

    def test_invalid_version(self):
        """Test that invalid version fails."""
        data = {"version": 2, "files": []}  # Only version 1 is valid
        errors = validate_manifest(data)
        assert len(errors) == 1

    def test_invalid_file_entry(self):
        """Test that invalid file entry fails."""
        data = {
            "version": 1,
            "files": [{"path": "test.txt"}],  # Missing hash and size
        }
        errors = validate_manifest(data)
        assert len(errors) >= 1


class TestFileValidation:
    """Test suite for file-level validation."""

    def test_validate_resource_file(self, tmp_path):
        """Test validating a resource file."""
        resource_path = tmp_path / "test.json"
        resource_path.write_text(json.dumps({"name": "test", "kind": "vector"}))

        errors = validate_resource_file(resource_path)
        assert errors == []

    def test_validate_invalid_resource_file(self, tmp_path):
        """Test validating an invalid resource file."""
        resource_path = tmp_path / "test.json"
        resource_path.write_text(json.dumps({"name": "123bad", "kind": "vector"}))

        errors = validate_resource_file(resource_path)
        assert len(errors) == 1

    def test_validate_invalid_json_file(self, tmp_path):
        """Test validating a file with invalid JSON."""
        resource_path = tmp_path / "test.json"
        resource_path.write_text("{invalid json")

        errors = validate_resource_file(resource_path)
        assert len(errors) == 1
        assert "JSON" in errors[0]

    def test_validate_missing_file(self, tmp_path):
        """Test validating a missing file."""
        resource_path = tmp_path / "nonexistent.json"

        errors = validate_resource_file(resource_path)
        assert len(errors) == 1
        assert "not found" in errors[0].lower()

    def test_validate_config_file(self, tmp_path):
        """Test validating a config file."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "outputs": {"metadata": {"iceberg": True}, "data": {"iceberg": True}}
        }))

        errors = validate_config_file(config_path)
        assert errors == []

    def test_validate_state_file(self, tmp_path):
        """Test validating a state file."""
        state_path = tmp_path / "state.json"
        state_path.write_text(json.dumps({"remote_url": "gs://bucket"}))

        errors = validate_state_file(state_path)
        assert errors == []


class TestCatalogValidation:
    """Test suite for catalog-level validation."""

    def test_validate_catalog(self, tmp_path):
        """Test validating a full catalog."""
        portolan_dir = tmp_path / ".portolan"
        portolan_dir.mkdir()

        # Create config
        (portolan_dir / "config.json").write_text(
            json.dumps({"outputs": {"metadata": {"iceberg": True}, "data": {"iceberg": True}}})
        )

        # Create state
        (portolan_dir / "state.json").write_text(
            json.dumps({"remote_url": None})
        )

        # Create resources
        resources_dir = portolan_dir / "resources" / "default"
        resources_dir.mkdir(parents=True)
        (resources_dir / "test.json").write_text(
            json.dumps({"name": "test", "kind": "vector"})
        )

        errors = validate_catalog(portolan_dir)
        assert errors == {}

    def test_validate_catalog_with_errors(self, tmp_path):
        """Test validating a catalog with errors."""
        portolan_dir = tmp_path / ".portolan"
        portolan_dir.mkdir()

        # Create invalid config (unknown top-level key in outputs)
        (portolan_dir / "config.json").write_text(
            json.dumps({"outputs": {"unknown_section": True}})
        )

        # Create invalid resource
        resources_dir = portolan_dir / "resources" / "default"
        resources_dir.mkdir(parents=True)
        (resources_dir / "bad.json").write_text(
            json.dumps({"name": "123bad", "kind": "invalid"})
        )

        errors = validate_catalog(portolan_dir)
        assert len(errors) == 2  # config + resource


class TestOutputsConfig:
    """Test suite for OutputsConfig dataclass."""

    def test_defaults(self):
        """Test default OutputsConfig values."""
        from portolan import OutputsConfig
        config = OutputsConfig()
        assert config.is_enabled("metadata", "iceberg") is True
        assert config.is_enabled("metadata", "stac") is False
        assert config.is_enabled("data", "iceberg") is True
        assert config.is_enabled("data", "ducklake") is False

    def test_is_enabled_with_dict_value(self):
        """Test is_enabled with object value containing 'enabled'."""
        from portolan import OutputsConfig
        config = OutputsConfig(data={"iceberg": {"enabled": True}, "ducklake": {"enabled": False}})
        assert config.is_enabled("data", "iceberg") is True
        assert config.is_enabled("data", "ducklake") is False

    def test_to_dict_roundtrip(self):
        """Test to_dict / from_dict roundtrip."""
        from portolan import OutputsConfig
        original = OutputsConfig()
        restored = OutputsConfig.from_dict(original.to_dict())
        assert original.metadata == restored.metadata
        assert original.data == restored.data

    def test_catalog_config_load_new_format(self, tmp_path):
        """Test that CatalogConfig.load reads new nested format."""
        from portolan import CatalogConfig
        portolan_dir = tmp_path / ".portolan"
        portolan_dir.mkdir()
        config_data = {
            "outputs": {
                "metadata": {"stac": True, "iso19139": False, "web": False, "iceberg": True},
                "data": {"iceberg": True, "ducklake": False},
            }
        }
        (portolan_dir / "config.json").write_text(json.dumps(config_data))
        catalog = CatalogConfig.load(portolan_dir)
        assert catalog.outputs.is_enabled("metadata", "stac") is True
        assert catalog.outputs.is_enabled("data", "iceberg") is True
        assert catalog.outputs.is_enabled("data", "ducklake") is False

    def test_catalog_config_save_new_format(self, tmp_path):
        """Test that CatalogConfig.save writes new nested format."""
        from portolan import CatalogConfig
        portolan_dir = tmp_path / ".portolan"
        portolan_dir.mkdir()
        catalog = CatalogConfig(path=portolan_dir)
        catalog.save()
        with open(portolan_dir / "config.json") as f:
            data = json.load(f)
        assert "metadata" in data["outputs"]
        assert "data" in data["outputs"]
        assert data["outputs"]["metadata"]["iceberg"] is True
        assert data["outputs"]["data"]["iceberg"] is True
