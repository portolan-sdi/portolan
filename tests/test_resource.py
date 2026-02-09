"""
Tests for resource model and lifecycle.
"""

import json
import tempfile
from pathlib import Path

import pytest

from portolan_resource import (
    Assets,
    DerivedMetadata,
    IcebergAsset,
    Origin,
    Resource,
    ResourceMetadata,
    SnapshotAsset,
    SourceMetadata,
    SyncConfig,
    Upstream,
    UserMetadata,
    compute_derived_metadata,
    load_resource,
    save_resource,
)


class TestOrigin:
    """Test suite for Origin dataclass."""

    def test_origin_creation(self):
        """Test creating an origin."""
        origin = Origin(type="file", url="/path/to/file.parquet")
        assert origin.type == "file"
        assert origin.url == "/path/to/file.parquet"

    def test_origin_to_dict(self):
        """Test origin serialization."""
        origin = Origin(
            type="arcgis_featureserver",
            url="https://services.arcgis.com/test/0",
            layer="boundaries",
        )
        data = origin.to_dict()
        assert data["type"] == "arcgis_featureserver"
        assert data["url"] == "https://services.arcgis.com/test/0"
        assert data["layer"] == "boundaries"

    def test_origin_from_dict(self):
        """Test origin deserialization."""
        data = {
            "type": "stac",
            "url": "https://earth-search.aws.element84.com/v1/items/xyz",
            "stac_collection": "sentinel-2-l2a",
        }
        origin = Origin.from_dict(data)
        assert origin.type == "stac"
        assert origin.stac_collection == "sentinel-2-l2a"


class TestAssets:
    """Test suite for Assets dataclass."""

    def test_empty_assets(self):
        """Test empty assets."""
        assets = Assets()
        assert assets.snapshot is None
        assert assets.iceberg is None

    def test_assets_with_snapshot(self):
        """Test assets with snapshot."""
        snapshot = SnapshotAsset(
            href="data/raw/test/data.parquet",
            type="application/vnd.apache.parquet",
            taken_at="2024-01-01T00:00:00Z",
            format="geoparquet",
        )
        assets = Assets(snapshot=snapshot)
        assert assets.snapshot is not None
        assert assets.snapshot.format == "geoparquet"

    def test_assets_to_dict(self):
        """Test assets serialization."""
        assets = Assets(
            snapshot=SnapshotAsset(
                href="data/raw/test/data.parquet",
                type="application/vnd.apache.parquet",
                taken_at="2024-01-01T00:00:00Z",
                format="geoparquet",
            ),
            iceberg=IcebergAsset(metadata="data/test/metadata/v1.metadata.json"),
        )
        data = assets.to_dict()
        assert "snapshot" in data
        assert "iceberg" in data
        assert data["snapshot"]["format"] == "geoparquet"


class TestResourceMetadata:
    """Test suite for ResourceMetadata dataclass."""

    def test_empty_metadata(self):
        """Test empty metadata."""
        meta = ResourceMetadata()
        assert meta.user.title is None
        assert meta.source is None
        assert meta.derived is None

    def test_effective_title_user(self):
        """Test effective title returns user title first."""
        meta = ResourceMetadata(
            user=UserMetadata(title="User Title"),
            source=SourceMetadata(provider="stac", data={"title": "Source Title"}),
        )
        assert meta.get_effective_title() == "User Title"

    def test_effective_title_source(self):
        """Test effective title falls back to source."""
        meta = ResourceMetadata(
            user=UserMetadata(),
            source=SourceMetadata(provider="stac", data={"title": "Source Title"}),
        )
        assert meta.get_effective_title() == "Source Title"

    def test_effective_title_none(self):
        """Test effective title returns None when no title."""
        meta = ResourceMetadata()
        assert meta.get_effective_title() is None

    def test_user_metadata_with_properties(self):
        """Test UserMetadata with custom properties."""
        meta = UserMetadata(
            title="Test",
            properties={"contact_email": "test@example.com", "topic_category": "boundaries"},
        )
        data = meta.to_dict()
        assert data["title"] == "Test"
        assert data["properties"]["contact_email"] == "test@example.com"
        assert data["properties"]["topic_category"] == "boundaries"

    def test_user_metadata_properties_roundtrip(self):
        """Test properties survive serialization roundtrip."""
        meta = UserMetadata(
            title="Test",
            license="CC-BY-4.0",
            properties={"lineage": "Extracted from WFS", "spatial_resolution": 100},
        )
        data = meta.to_dict()
        restored = UserMetadata.from_dict(data)
        assert restored.properties["lineage"] == "Extracted from WFS"
        assert restored.properties["spatial_resolution"] == 100
        assert restored.license == "CC-BY-4.0"

    def test_user_metadata_empty_properties_not_serialized(self):
        """Empty properties dict should not appear in serialization."""
        meta = UserMetadata(title="Test")
        data = meta.to_dict()
        assert "properties" not in data

    def test_get_effective_from_properties(self):
        """get_effective reads from user properties."""
        meta = ResourceMetadata(
            user=UserMetadata(properties={"contact_email": "test@example.com"}),
        )
        assert meta.get_effective("contact_email") == "test@example.com"

    def test_get_effective_user_properties_over_source(self):
        """User properties take precedence over source data."""
        meta = ResourceMetadata(
            user=UserMetadata(properties={"contact_email": "user@example.com"}),
            source=SourceMetadata(provider="stac", data={"contact_email": "source@example.com"}),
        )
        assert meta.get_effective("contact_email") == "user@example.com"

    def test_get_effective_falls_back_to_source(self):
        """get_effective falls back to source.data when not in user."""
        meta = ResourceMetadata(
            user=UserMetadata(),
            source=SourceMetadata(provider="stac", data={"topic_category": "boundaries"}),
        )
        assert meta.get_effective("topic_category") == "boundaries"


class TestDerivedColumns:
    """Test suite for derived column metadata."""

    def test_columns_serialization(self):
        """Test columns survive to_dict/from_dict roundtrip."""
        columns = [
            {"name": "id", "type": "int64", "nullable": False},
            {"name": "name", "type": "string", "nullable": True},
            {"name": "geometry", "type": "geometry", "nullable": True, "geometry_type": "Point", "crs": "EPSG:4326"},
        ]
        derived = DerivedMetadata(row_count=100, columns=columns)
        data = derived.to_dict()
        assert data["columns"] == columns

        restored = DerivedMetadata.from_dict(data)
        assert restored.columns == columns
        assert len(restored.columns) == 3
        assert restored.columns[2]["geometry_type"] == "Point"

    def test_columns_empty_not_serialized(self):
        """Empty columns list should not appear in serialization."""
        derived = DerivedMetadata(row_count=50)
        data = derived.to_dict()
        assert "columns" not in data

    def test_columns_in_resource_roundtrip(self):
        """Columns survive full resource serialization roundtrip."""
        columns = [
            {"name": "pop", "type": "int64", "nullable": True},
            {"name": "geom", "type": "geometry", "nullable": True, "geometry_type": "Polygon", "crs": "EPSG:4326"},
        ]
        resource = Resource(
            name="test",
            kind="vector",
            metadata=ResourceMetadata(
                derived=DerivedMetadata(row_count=10, columns=columns),
            ),
        )
        data = resource.to_dict()
        restored = Resource.from_dict(data)
        assert restored.metadata.derived.columns == columns


class TestComputeDerivedMetadata:
    """Test suite for compute_derived_metadata column extraction."""

    def test_extracts_columns_from_geoparquet(self, sample_geoparquet):
        """Test that columns are extracted from a GeoParquet file."""
        derived = compute_derived_metadata(sample_geoparquet)

        assert derived.columns is not None
        assert len(derived.columns) >= 3  # name, country, population, geometry

        col_names = [c["name"] for c in derived.columns]
        assert "name" in col_names
        assert "country" in col_names
        assert "population" in col_names

        # Check types are simplified
        for col in derived.columns:
            assert "name" in col
            assert "type" in col
            assert "nullable" in col

    def test_geometry_column_enriched(self, sample_geoparquet):
        """Test that geometry columns get geometry_type and crs."""
        derived = compute_derived_metadata(sample_geoparquet)

        geom_cols = [c for c in derived.columns if c["type"] == "geometry"]
        assert len(geom_cols) >= 1
        geom = geom_cols[0]
        assert "geometry_type" in geom

    def test_row_count_and_schema_hash(self, sample_geoparquet):
        """Test that row count and schema hash are still computed."""
        derived = compute_derived_metadata(sample_geoparquet)
        assert derived.row_count == 3
        assert derived.schema_hash is not None


class TestResourceLifecycle:
    """Test suite for resource lifecycle states."""

    def test_registered_state(self):
        """Test resource with only origin is REGISTERED."""
        resource = Resource(
            name="test",
            kind="vector",
            origin=Origin(type="wfs", url="https://example.com/wfs"),
        )
        assert resource.state == "registered"

    def test_ready_with_snapshot(self):
        """Test resource with snapshot is READY."""
        resource = Resource(
            name="test",
            kind="vector",
            origin=Origin(type="wfs", url="https://example.com/wfs"),
            assets=Assets(
                snapshot=SnapshotAsset(
                    href="data/raw/test/data.parquet",
                    type="application/vnd.apache.parquet",
                    taken_at="2024-01-01T00:00:00Z",
                    format="geoparquet",
                ),
            ),
        )
        assert resource.state == "ready"
        assert resource.is_local is True
        assert resource.is_linked is False

    def test_ready_with_iceberg(self):
        """Test resource with iceberg asset is READY."""
        resource = Resource(
            name="test",
            kind="vector",
            origin=Origin(type="wfs", url="https://example.com/wfs"),
            assets=Assets(
                snapshot=SnapshotAsset(
                    href="data/raw/test/data.parquet",
                    type="application/vnd.apache.parquet",
                    taken_at="2024-01-01T00:00:00Z",
                    format="geoparquet",
                ),
                iceberg=IcebergAsset(metadata="data/test/metadata/v1.metadata.json"),
            ),
        )
        assert resource.state == "ready"
        assert resource.is_local is True

    def test_ready_linked(self):
        """Test resource with only iceberg (no snapshot) is READY and linked."""
        resource = Resource(
            name="test",
            kind="vector",
            origin=Origin(type="file", url="s3://bucket/data.parquet"),
            assets=Assets(
                iceberg=IcebergAsset(metadata="data/test/metadata/v1.metadata.json"),
            ),
        )
        assert resource.state == "ready"
        assert resource.is_local is False
        assert resource.is_linked is True

    def test_unknown_state(self):
        """Test resource with no origin is UNKNOWN."""
        resource = Resource(name="test", kind="vector")
        assert resource.state == "unknown"


class TestResourceSerialization:
    """Test suite for resource serialization."""

    def test_to_dict_minimal(self):
        """Test minimal resource serialization."""
        resource = Resource(name="test", kind="vector")
        data = resource.to_dict()
        assert data["name"] == "test"
        assert data["kind"] == "vector"
        assert "assets" in data
        assert "metadata" in data

    def test_to_dict_full(self):
        """Test full resource serialization."""
        resource = Resource(
            name="test",
            kind="vector",
            origin=Origin(type="file", url="/path/to/file.parquet"),
            assets=Assets(
                snapshot=SnapshotAsset(
                    href="data/raw/test/data.parquet",
                    type="application/vnd.apache.parquet",
                    taken_at="2024-01-01T00:00:00Z",
                    format="geoparquet",
                ),
            ),
            metadata=ResourceMetadata(
                user=UserMetadata(title="Test Resource", description="A test"),
                derived=DerivedMetadata(row_count=100, bbox=[-10, 35, 5, 45]),
            ),
            created_at="2024-01-01T00:00:00Z",
        )
        data = resource.to_dict()
        assert data["origin"]["type"] == "file"
        assert data["assets"]["snapshot"]["format"] == "geoparquet"
        assert data["metadata"]["user"]["title"] == "Test Resource"
        assert data["metadata"]["derived"]["row_count"] == 100

    def test_from_dict_new_format(self):
        """Test deserialization of new format."""
        data = {
            "name": "test",
            "kind": "vector",
            "origin": {"type": "file", "url": "/path/to/file.parquet"},
            "assets": {},
            "metadata": {
                "user": {"title": "Test"},
                "sync": {"mode": "manual", "strategy": "update_source_only"},
            },
        }
        resource = Resource.from_dict(data)
        assert resource.name == "test"
        assert resource.origin.type == "file"
        assert resource.metadata.user.title == "Test"

    def test_roundtrip(self):
        """Test serialization roundtrip."""
        original = Resource(
            name="roundtrip_test",
            kind="vector",
            origin=Origin(type="wfs", url="https://example.com/wfs", layer="boundaries"),
            assets=Assets(
                snapshot=SnapshotAsset(
                    href="data/raw/test/data.parquet",
                    type="application/vnd.apache.parquet",
                    taken_at="2024-01-01T00:00:00Z",
                    format="geoparquet",
                ),
            ),
            metadata=ResourceMetadata(
                user=UserMetadata(title="Roundtrip", tags=["test", "example"]),
            ),
            created_at="2024-01-01T00:00:00Z",
        )
        data = original.to_dict()
        restored = Resource.from_dict(data)

        assert restored.name == original.name
        assert restored.kind == original.kind
        assert restored.origin.url == original.origin.url
        assert restored.assets.snapshot.href == original.assets.snapshot.href
        assert restored.metadata.user.title == original.metadata.user.title
        assert restored.metadata.user.tags == original.metadata.user.tags


class TestResourcePersistence:
    """Test suite for resource file operations."""

    def test_save_and_load(self, tmp_path):
        """Test saving and loading a resource."""
        resource = Resource(
            name="persistence_test",
            kind="vector",
            origin=Origin(type="file", url="/path/to/file.parquet"),
            metadata=ResourceMetadata(
                user=UserMetadata(title="Persistence Test"),
            ),
            created_at="2024-01-01T00:00:00Z",
        )

        resource_path = tmp_path / "test.json"
        save_resource(resource, resource_path)

        assert resource_path.exists()

        loaded = load_resource(resource_path)
        assert loaded.name == resource.name
        assert loaded.origin.url == resource.origin.url
        assert loaded.metadata.user.title == resource.metadata.user.title

    def test_save_creates_directory(self, tmp_path):
        """Test that save creates parent directories."""
        resource = Resource(name="test", kind="vector")
        resource_path = tmp_path / "nested" / "dir" / "test.json"

        save_resource(resource, resource_path)

        assert resource_path.exists()
        assert resource_path.parent.exists()


class TestUpstream:
    """Test suite for Upstream dataclass."""

    def test_upstream_creation(self):
        """Test creating upstream reference."""
        upstream = Upstream(
            catalog="planetary-computer",
            type="stac",
            id="sentinel-2-l2a/item123",
        )
        assert upstream.catalog == "planetary-computer"
        assert upstream.type == "stac"

    def test_upstream_roundtrip(self):
        """Test upstream serialization roundtrip."""
        original = Upstream(catalog="test", type="stac", id="item1")
        data = original.to_dict()
        restored = Upstream.from_dict(data)

        assert restored.catalog == original.catalog
        assert restored.type == original.type
        assert restored.id == original.id
