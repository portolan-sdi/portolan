"""
Tests for catalog sources and federation.
"""

import json
import tempfile
from pathlib import Path

import pytest

from catalog_sources import (
    CatalogSource,
    CatalogSourceStore,
    compute_catalog_hash,
)


class TestCatalogSource:
    """Test suite for CatalogSource dataclass."""

    def test_source_creation(self):
        """Test creating a catalog source."""
        source = CatalogSource(
            name="earth-search",
            type="stac",
            url="https://earth-search.aws.element84.com/v1",
        )
        assert source.name == "earth-search"
        assert source.type == "stac"
        assert source.url == "https://earth-search.aws.element84.com/v1"
        assert source.last_sync is None
        assert source.sync_hash is None
        assert source.filters == {}

    def test_source_with_filters(self):
        """Test creating a catalog source with filters."""
        source = CatalogSource(
            name="sentinel",
            type="stac",
            url="https://example.com/stac",
            filters={"collections": ["sentinel-2-l2a", "sentinel-1-grd"]},
        )
        assert source.filters["collections"] == ["sentinel-2-l2a", "sentinel-1-grd"]

    def test_source_to_dict(self):
        """Test catalog source serialization."""
        source = CatalogSource(
            name="test",
            type="stac",
            url="https://example.com",
            last_sync="2024-01-15T00:00:00Z",
            sync_hash="abc123",
            filters={"collections": ["test"]},
            created_at="2024-01-01T00:00:00Z",
        )
        data = source.to_dict()
        assert data["name"] == "test"
        assert data["type"] == "stac"
        assert data["url"] == "https://example.com"
        assert data["last_sync"] == "2024-01-15T00:00:00Z"
        assert data["sync_hash"] == "abc123"
        assert data["filters"] == {"collections": ["test"]}

    def test_source_from_dict(self):
        """Test catalog source deserialization."""
        data = {
            "name": "earth-search",
            "type": "stac",
            "url": "https://earth-search.aws.element84.com/v1",
            "last_sync": "2024-01-15T00:00:00Z",
            "sync_hash": "def456",
            "filters": {"collections": ["sentinel-2-l2a"]},
        }
        source = CatalogSource.from_dict(data)
        assert source.name == "earth-search"
        assert source.type == "stac"
        assert source.last_sync == "2024-01-15T00:00:00Z"
        assert source.sync_hash == "def456"

    def test_source_roundtrip(self):
        """Test serialization roundtrip."""
        original = CatalogSource(
            name="test",
            type="arcgis",
            url="https://services.arcgis.com/test",
            filters={"bbox": [-180, -90, 180, 90]},
            created_at="2024-01-01T00:00:00Z",
        )
        data = original.to_dict()
        restored = CatalogSource.from_dict(data)

        assert restored.name == original.name
        assert restored.type == original.type
        assert restored.url == original.url
        assert restored.filters == original.filters


class TestCatalogSourceStore:
    """Test suite for CatalogSourceStore."""

    def test_empty_store(self, tmp_path):
        """Test operations on empty store."""
        store = CatalogSourceStore(tmp_path)
        sources = store.list_sources()
        assert sources == []

    def test_add_source(self, tmp_path):
        """Test adding a catalog source."""
        store = CatalogSourceStore(tmp_path)
        source = CatalogSource(
            name="test",
            type="stac",
            url="https://example.com/stac",
        )
        store.add_source(source)

        # Verify it was saved
        sources = store.list_sources()
        assert len(sources) == 1
        assert sources[0].name == "test"

    def test_get_source(self, tmp_path):
        """Test getting a specific source."""
        store = CatalogSourceStore(tmp_path)
        source = CatalogSource(
            name="earth-search",
            type="stac",
            url="https://earth-search.aws.element84.com/v1",
        )
        store.add_source(source)

        retrieved = store.get_source("earth-search")
        assert retrieved is not None
        assert retrieved.name == "earth-search"
        assert retrieved.type == "stac"

    def test_get_nonexistent_source(self, tmp_path):
        """Test getting a source that doesn't exist."""
        store = CatalogSourceStore(tmp_path)
        result = store.get_source("nonexistent")
        assert result is None

    def test_remove_source(self, tmp_path):
        """Test removing a catalog source."""
        store = CatalogSourceStore(tmp_path)
        source = CatalogSource(
            name="to-remove",
            type="stac",
            url="https://example.com",
        )
        store.add_source(source)

        # Verify it exists
        assert store.get_source("to-remove") is not None

        # Remove it
        result = store.remove_source("to-remove")
        assert result is True

        # Verify it's gone
        assert store.get_source("to-remove") is None

    def test_remove_nonexistent_source(self, tmp_path):
        """Test removing a source that doesn't exist."""
        store = CatalogSourceStore(tmp_path)
        result = store.remove_source("nonexistent")
        assert result is False

    def test_update_sync_state(self, tmp_path):
        """Test updating sync state."""
        store = CatalogSourceStore(tmp_path)
        source = CatalogSource(
            name="test",
            type="stac",
            url="https://example.com",
        )
        store.add_source(source)

        # Initially no sync state
        retrieved = store.get_source("test")
        assert retrieved.last_sync is None
        assert retrieved.sync_hash is None

        # Update sync state
        store.update_sync_state("test", "abc123def456")

        # Verify it was updated
        retrieved = store.get_source("test")
        assert retrieved.last_sync is not None
        assert retrieved.sync_hash == "abc123def456"

    def test_multiple_sources(self, tmp_path):
        """Test managing multiple sources."""
        store = CatalogSourceStore(tmp_path)

        sources = [
            CatalogSource(name="source1", type="stac", url="https://example1.com"),
            CatalogSource(name="source2", type="arcgis", url="https://example2.com"),
            CatalogSource(name="source3", type="wfs", url="https://example3.com"),
        ]

        for source in sources:
            store.add_source(source)

        retrieved = store.list_sources()
        assert len(retrieved) == 3

        names = {s.name for s in retrieved}
        assert names == {"source1", "source2", "source3"}


class TestComputeCatalogHash:
    """Test suite for catalog hash computation."""

    def test_hash_empty_list(self):
        """Test hashing an empty list."""
        hash1 = compute_catalog_hash([])
        hash2 = compute_catalog_hash([])
        assert hash1 == hash2

    def test_hash_consistency(self):
        """Test that same items produce same hash."""
        items = [
            {"id": "item1", "title": "First"},
            {"id": "item2", "title": "Second"},
        ]
        hash1 = compute_catalog_hash(items)
        hash2 = compute_catalog_hash(items)
        assert hash1 == hash2

    def test_hash_order_independence(self):
        """Test that item order doesn't affect hash."""
        items1 = [
            {"id": "item1", "title": "First"},
            {"id": "item2", "title": "Second"},
        ]
        items2 = [
            {"id": "item2", "title": "Second"},
            {"id": "item1", "title": "First"},
        ]
        hash1 = compute_catalog_hash(items1)
        hash2 = compute_catalog_hash(items2)
        assert hash1 == hash2

    def test_hash_change_detection(self):
        """Test that different items produce different hash."""
        items1 = [{"id": "item1", "title": "First"}]
        items2 = [{"id": "item1", "title": "Modified"}]
        hash1 = compute_catalog_hash(items1)
        hash2 = compute_catalog_hash(items2)
        assert hash1 != hash2

    def test_hash_addition_detection(self):
        """Test that adding items produces different hash."""
        items1 = [{"id": "item1"}]
        items2 = [{"id": "item1"}, {"id": "item2"}]
        hash1 = compute_catalog_hash(items1)
        hash2 = compute_catalog_hash(items2)
        assert hash1 != hash2

    def test_hash_length(self):
        """Test that hash has expected length."""
        items = [{"id": "test"}]
        hash_result = compute_catalog_hash(items)
        assert len(hash_result) == 16  # We truncate to 16 chars
