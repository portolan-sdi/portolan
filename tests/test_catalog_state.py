"""
Tests for catalog state management.
"""

import json
import tempfile
from pathlib import Path

import pytest

from catalog_state import (
    CatalogDiff,
    LocalState,
    Manifest,
    ResourceEntry,
    canonical_json,
    compute_diff,
    compute_file_hash,
    compute_hash,
    compute_json_hash,
    get_remote_store,
    scan_local_resources,
    LocalFilesystemStore,
)


class TestHashing:
    """Test suite for hashing functions."""

    def test_compute_hash_deterministic(self):
        """Test that hash is deterministic."""
        data = b"hello world"
        hash1 = compute_hash(data)
        hash2 = compute_hash(data)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex length

    def test_compute_hash_different_input(self):
        """Test that different inputs produce different hashes."""
        hash1 = compute_hash(b"hello")
        hash2 = compute_hash(b"world")
        assert hash1 != hash2

    def test_canonical_json_sorted(self):
        """Test that canonical JSON has sorted keys."""
        obj = {"z": 1, "a": 2, "m": 3}
        result = canonical_json(obj)
        # Keys should be sorted
        assert result == '{"a":2,"m":3,"z":1}'

    def test_compute_json_hash_deterministic(self):
        """Test that JSON hash is deterministic regardless of key order."""
        obj1 = {"a": 1, "b": 2}
        obj2 = {"b": 2, "a": 1}
        hash1 = compute_json_hash(obj1)
        hash2 = compute_json_hash(obj2)
        assert hash1 == hash2

    def test_compute_file_hash(self, tmp_path):
        """Test file hash computation."""
        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"test content")

        hash1 = compute_file_hash(test_file)
        hash2 = compute_file_hash(test_file)
        assert hash1 == hash2
        assert len(hash1) == 64


class TestManifest:
    """Test suite for Manifest class."""

    def test_manifest_creation(self):
        """Test creating a manifest."""
        manifest = Manifest()
        assert manifest.version == 1
        assert manifest.resources == []
        assert manifest.created_at != ""

    def test_manifest_with_resources(self):
        """Test manifest with resources."""
        resources = [
            ResourceEntry(path="a.json", sha256="abc123"),
            ResourceEntry(path="b.json", sha256="def456"),
        ]
        manifest = Manifest(resources=resources)
        assert len(manifest.resources) == 2

    def test_manifest_to_dict(self):
        """Test manifest serialization."""
        manifest = Manifest(
            resources=[ResourceEntry(path="test.json", sha256="abc")]
        )
        data = manifest.to_dict()
        assert "version" in data
        assert "created_at" in data
        assert "resources" in data
        assert len(data["resources"]) == 1

    def test_manifest_from_dict(self):
        """Test manifest deserialization."""
        data = {
            "version": 1,
            "created_at": "2024-01-01T00:00:00Z",
            "resources": [{"path": "test.json", "sha256": "abc"}],
        }
        manifest = Manifest.from_dict(data)
        assert manifest.version == 1
        assert len(manifest.resources) == 1
        assert manifest.resources[0].path == "test.json"

    def test_manifest_roundtrip(self):
        """Test manifest JSON roundtrip."""
        original = Manifest(
            resources=[
                ResourceEntry(path="a.json", sha256="abc"),
                ResourceEntry(path="b.json", sha256="def"),
            ]
        )
        json_str = original.to_json()
        restored = Manifest.from_json(json_str)

        assert restored.version == original.version
        assert len(restored.resources) == len(original.resources)
        assert restored.resources[0].path == original.resources[0].path

    def test_manifest_hash_deterministic(self):
        """Test that manifest hash is deterministic."""
        manifest = Manifest(
            created_at="2024-01-01T00:00:00Z",
            resources=[ResourceEntry(path="test.json", sha256="abc")],
        )
        hash1 = manifest.compute_hash()
        hash2 = manifest.compute_hash()
        assert hash1 == hash2

    def test_manifest_resource_map(self):
        """Test getting resource map from manifest."""
        manifest = Manifest(
            resources=[
                ResourceEntry(path="a.json", sha256="hash_a"),
                ResourceEntry(path="b.json", sha256="hash_b"),
            ]
        )
        resource_map = manifest.get_resource_map()
        assert resource_map == {"a.json": "hash_a", "b.json": "hash_b"}


class TestLocalState:
    """Test suite for LocalState class."""

    def test_local_state_creation(self):
        """Test creating local state."""
        state = LocalState()
        assert state.remote_url is None
        assert state.base_manifest_hash is None

    def test_local_state_with_values(self):
        """Test local state with values."""
        state = LocalState(
            remote_url="gs://bucket/path",
            base_manifest_hash="abc123",
        )
        assert state.remote_url == "gs://bucket/path"
        assert state.base_manifest_hash == "abc123"

    def test_local_state_save_load(self, tmp_path):
        """Test saving and loading local state."""
        state_file = tmp_path / "state.json"

        original = LocalState(
            remote_url="gs://test/path",
            base_manifest_hash="hash123",
        )
        original.save(state_file)

        loaded = LocalState.load(state_file)
        assert loaded.remote_url == original.remote_url
        assert loaded.base_manifest_hash == original.base_manifest_hash

    def test_local_state_load_missing(self, tmp_path):
        """Test loading state from missing file returns default."""
        state_file = tmp_path / "nonexistent.json"
        state = LocalState.load(state_file)
        assert state.remote_url is None
        assert state.base_manifest_hash is None


class TestCatalogDiff:
    """Test suite for diff computation."""

    def test_empty_diff(self):
        """Test empty diff."""
        diff = CatalogDiff()
        assert diff.is_empty
        assert diff.total_changes == 0

    def test_diff_with_changes(self):
        """Test diff with changes."""
        diff = CatalogDiff(
            added=["a.json", "b.json"],
            modified=["c.json"],
            deleted=["d.json"],
        )
        assert not diff.is_empty
        assert diff.total_changes == 4

    def test_compute_diff_added(self):
        """Test computing diff with added files."""
        base = {}
        local = {"a.json": "hash_a", "b.json": "hash_b"}
        diff = compute_diff(base, local)

        assert set(diff.added) == {"a.json", "b.json"}
        assert diff.modified == []
        assert diff.deleted == []

    def test_compute_diff_deleted(self):
        """Test computing diff with deleted files."""
        base = {"a.json": "hash_a", "b.json": "hash_b"}
        local = {}
        diff = compute_diff(base, local)

        assert diff.added == []
        assert diff.modified == []
        assert set(diff.deleted) == {"a.json", "b.json"}

    def test_compute_diff_modified(self):
        """Test computing diff with modified files."""
        base = {"a.json": "old_hash"}
        local = {"a.json": "new_hash"}
        diff = compute_diff(base, local)

        assert diff.added == []
        assert diff.modified == ["a.json"]
        assert diff.deleted == []

    def test_compute_diff_mixed(self):
        """Test computing diff with mixed changes."""
        base = {"keep.json": "same", "modify.json": "old", "delete.json": "hash"}
        local = {"keep.json": "same", "modify.json": "new", "add.json": "new"}
        diff = compute_diff(base, local)

        assert diff.added == ["add.json"]
        assert diff.modified == ["modify.json"]
        assert diff.deleted == ["delete.json"]


class TestScanLocalResources:
    """Test suite for scanning local resources."""

    def test_scan_empty_dir(self, tmp_path):
        """Test scanning empty directory."""
        resources_dir = tmp_path / "resources"
        resources_dir.mkdir()
        result = scan_local_resources(resources_dir)
        assert result == {}

    def test_scan_with_resources(self, tmp_path):
        """Test scanning directory with resources."""
        resources_dir = tmp_path / "resources"
        ns_dir = resources_dir / "test"
        ns_dir.mkdir(parents=True)

        # Create a test resource
        resource_file = ns_dir / "item.json"
        resource_file.write_text('{"name": "test"}')

        # Need to call from parent of resources_dir
        result = scan_local_resources(resources_dir)
        assert len(result) == 1
        assert "resources/test/item.json" in result

    def test_scan_skips_underscore_files(self, tmp_path):
        """Test that files starting with _ are skipped."""
        resources_dir = tmp_path / "resources"
        ns_dir = resources_dir / "test"
        ns_dir.mkdir(parents=True)

        # Create normal and underscore files
        (ns_dir / "normal.json").write_text("{}")
        (ns_dir / "_index.json").write_text("{}")

        result = scan_local_resources(resources_dir)
        assert len(result) == 1
        assert any("normal.json" in k for k in result)
        assert not any("_index.json" in k for k in result)


class TestRemoteStore:
    """Test suite for remote store implementations."""

    def test_local_filesystem_store_put_get(self, tmp_path):
        """Test LocalFilesystemStore put and get."""
        store = LocalFilesystemStore(str(tmp_path))

        # Put a resource
        store.put_resource("test/file.json", b'{"test": true}')

        # Get it back
        data = store.get_resource("test/file.json")
        assert data == b'{"test": true}'

    def test_local_filesystem_store_manifest(self, tmp_path):
        """Test LocalFilesystemStore manifest operations."""
        store = LocalFilesystemStore(str(tmp_path))

        # Put manifest
        manifest = Manifest(
            resources=[ResourceEntry(path="test.json", sha256="abc")]
        )
        hash1 = store.put_manifest(manifest)

        # Get manifest
        loaded, hash2 = store.get_manifest()
        assert loaded is not None
        assert len(loaded.resources) == 1
        assert hash1 == hash2

    def test_local_filesystem_store_delete(self, tmp_path):
        """Test LocalFilesystemStore delete."""
        store = LocalFilesystemStore(str(tmp_path))

        # Put and delete
        store.put_resource("test.json", b"data")
        assert store.get_resource("test.json") is not None

        store.delete_resource("test.json")
        assert store.get_resource("test.json") is None

    def test_get_remote_store_local(self, tmp_path):
        """Test factory creates correct store for local path."""
        store = get_remote_store(f"file://{tmp_path}")
        assert isinstance(store, LocalFilesystemStore)

    def test_get_remote_store_gs(self):
        """Test factory creates GCS store for gs:// URL."""
        from catalog_state import GCSStore
        store = get_remote_store("gs://bucket/path")
        assert isinstance(store, GCSStore)

    def test_get_remote_store_s3(self):
        """Test factory creates S3 store for s3:// URL."""
        from catalog_state import S3Store
        store = get_remote_store("s3://bucket/path")
        assert isinstance(store, S3Store)
