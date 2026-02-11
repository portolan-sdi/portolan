"""
Catalog state management for git-like workflow.

This module implements manifest-based state tracking for remote-first workflow:
- Manifest snapshots with content hashes
- Ahead/behind/dirty detection
- Safe sync with refuse-on-conflict semantics
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# =============================================================================
# Canonical JSON for deterministic hashing
# =============================================================================

def canonical_json(obj: Any) -> str:
    """Convert object to canonical JSON string (sorted keys, stable formatting)."""
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def compute_hash(data: bytes) -> str:
    """Compute SHA256 hash of bytes."""
    return hashlib.sha256(data).hexdigest()


def compute_json_hash(obj: Any) -> str:
    """Compute SHA256 hash of canonical JSON representation."""
    return compute_hash(canonical_json(obj).encode('utf-8'))


def compute_file_hash(path: Path) -> str:
    """Compute SHA256 hash of file contents."""
    with open(path, 'rb') as f:
        return compute_hash(f.read())


# =============================================================================
# Manifest
# =============================================================================

@dataclass
class ResourceEntry:
    """A single resource in the manifest."""
    path: str  # Relative path like "resources/demo/cities.json"
    sha256: str

    def to_dict(self) -> dict:
        return {"path": self.path, "sha256": self.sha256}

    @classmethod
    def from_dict(cls, data: dict) -> ResourceEntry:
        return cls(path=data["path"], sha256=data["sha256"])


@dataclass
class Manifest:
    """Remote catalog manifest - represents a complete snapshot."""
    version: int = 1
    created_at: str = ""
    resources: list[ResourceEntry] = field(default_factory=list)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "created_at": self.created_at,
            "resources": [r.to_dict() for r in self.resources],
        }

    def to_json(self) -> str:
        """Convert to pretty JSON for storage."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    def compute_hash(self) -> str:
        """Compute hash of canonical JSON representation."""
        return compute_json_hash(self.to_dict())

    def get_resource_map(self) -> dict[str, str]:
        """Get mapping of path -> sha256."""
        return {r.path: r.sha256 for r in self.resources}

    @classmethod
    def from_dict(cls, data: dict) -> Manifest:
        return cls(
            version=data.get("version", 1),
            created_at=data.get("created_at", ""),
            resources=[ResourceEntry.from_dict(r) for r in data.get("resources", [])],
        )

    @classmethod
    def from_json(cls, json_str: str) -> Manifest:
        return cls.from_dict(json.loads(json_str))


# =============================================================================
# Local State
# =============================================================================

@dataclass
class LocalState:
    """Local catalog state - tracks base manifest and remote URL."""
    remote_url: str | None = None
    base_manifest_hash: str | None = None  # Hash of last pulled/synced manifest

    def to_dict(self) -> dict:
        return {
            "remote_url": self.remote_url,
            "base_manifest_hash": self.base_manifest_hash,
        }

    def save(self, path: Path):
        """Save state to file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> LocalState:
        """Load state from file."""
        if not path.exists():
            return cls()
        with open(path) as f:
            data = json.load(f)
        return cls(
            remote_url=data.get("remote_url"),
            base_manifest_hash=data.get("base_manifest_hash"),
        )


# =============================================================================
# Diff Computation
# =============================================================================

@dataclass
class CatalogDiff:
    """Difference between two catalog states."""
    added: list[str] = field(default_factory=list)      # New paths
    modified: list[str] = field(default_factory=list)   # Changed paths
    deleted: list[str] = field(default_factory=list)    # Removed paths

    @property
    def is_empty(self) -> bool:
        return not self.added and not self.modified and not self.deleted

    @property
    def total_changes(self) -> int:
        return len(self.added) + len(self.modified) + len(self.deleted)

    def to_dict(self) -> dict:
        return {
            "added": self.added,
            "modified": self.modified,
            "deleted": self.deleted,
        }


def compute_diff(base_resources: dict[str, str], local_resources: dict[str, str]) -> CatalogDiff:
    """
    Compute diff between base manifest and local state.

    Args:
        base_resources: Dict of path -> sha256 from base manifest
        local_resources: Dict of path -> sha256 from local files

    Returns:
        CatalogDiff with added/modified/deleted paths
    """
    base_paths = set(base_resources.keys())
    local_paths = set(local_resources.keys())

    added = sorted(local_paths - base_paths)
    deleted = sorted(base_paths - local_paths)

    # Check for modifications in common paths
    common = base_paths & local_paths
    modified = sorted(p for p in common if base_resources[p] != local_resources[p])

    return CatalogDiff(added=added, modified=modified, deleted=deleted)


def scan_local_resources(resources_dir: Path) -> dict[str, str]:
    """
    Scan local resources directory and compute hashes.

    Returns:
        Dict of relative_path -> sha256
    """
    if not resources_dir.exists():
        return {}

    result = {}
    for file_path in resources_dir.rglob("*.json"):
        if file_path.name.startswith("_"):
            continue  # Skip index files
        relative = str(file_path.relative_to(resources_dir.parent))
        result[relative] = compute_file_hash(file_path)

    return result


# =============================================================================
# Remote Store Abstraction
# =============================================================================

class RemoteStore(ABC):
    """Abstract interface for remote storage backends."""

    @abstractmethod
    def get_manifest(self) -> tuple[Manifest | None, str | None]:
        """
        Get remote manifest.

        Returns:
            Tuple of (manifest, manifest_hash) or (None, None) if not found
        """
        pass

    @abstractmethod
    def put_manifest(self, manifest: Manifest) -> str:
        """
        Upload manifest to remote.

        Returns:
            Hash of uploaded manifest
        """
        pass

    @abstractmethod
    def get_resource(self, path: str) -> bytes | None:
        """Get resource file contents by path."""
        pass

    @abstractmethod
    def put_resource(self, path: str, data: bytes):
        """Upload resource file to remote."""
        pass

    @abstractmethod
    def delete_resource(self, path: str):
        """Delete resource file from remote."""
        pass

    @abstractmethod
    def exists(self) -> bool:
        """Check if remote is accessible."""
        pass


class LocalFilesystemStore(RemoteStore):
    """Remote store using local filesystem (for testing)."""

    def __init__(self, root_path: str):
        # Handle file:// URLs
        if root_path.startswith("file://"):
            root_path = root_path[7:]
        self.root = Path(root_path)

    def get_manifest(self) -> tuple[Manifest | None, str | None]:
        manifest_path = self.root / "manifest.json"
        if not manifest_path.exists():
            return None, None

        content = manifest_path.read_text()
        manifest = Manifest.from_json(content)
        manifest_hash = compute_hash(content.encode('utf-8'))
        return manifest, manifest_hash

    def put_manifest(self, manifest: Manifest) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        content = manifest.to_json()
        manifest_path = self.root / "manifest.json"
        manifest_path.write_text(content)
        return compute_hash(content.encode('utf-8'))

    def get_resource(self, path: str) -> bytes | None:
        file_path = self.root / path
        if not file_path.exists():
            return None
        return file_path.read_bytes()

    def put_resource(self, path: str, data: bytes):
        file_path = self.root / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(data)

    def delete_resource(self, path: str):
        file_path = self.root / path
        if file_path.exists():
            file_path.unlink()

    def exists(self) -> bool:
        return self.root.exists()


def _parse_bucket_prefix(path: str) -> tuple[str, str]:
    """Split 'bucket/some/prefix' into ('bucket', 'some/prefix')."""
    parts = path.split("/", 1)
    bucket = parts[0]
    prefix = parts[1].rstrip("/") if len(parts) > 1 else ""
    return bucket, prefix


def _s3_kwargs(options: dict) -> dict:
    """Map user options to obstore S3Store kwargs."""
    kwargs = {}
    if "region" in options:
        kwargs["region"] = options["region"]
    if "endpoint_url" in options:
        kwargs["endpoint"] = options["endpoint_url"]
        # S3-compatible services default to path-style requests
        kwargs["virtual_hosted_style_request"] = options.get(
            "virtual_hosted_style_request", False
        )
    if "access_key_id" in options:
        kwargs["access_key_id"] = options["access_key_id"]
    if "secret_access_key" in options:
        kwargs["secret_access_key"] = options["secret_access_key"]
    if options.get("anonymous"):
        kwargs["skip_signature"] = True
    # Allow HTTP for local S3-compatible services (e.g., MinIO)
    if options.get("allow_http"):
        kwargs["client_options"] = {"allow_http": True}
    return kwargs


def _gcs_kwargs(options: dict) -> dict:
    """Map user options to obstore GCSStore kwargs."""
    kwargs = {}
    if "service_account_path" in options:
        kwargs["service_account_path"] = options["service_account_path"]
    if options.get("anonymous"):
        kwargs["skip_signature"] = True
    return kwargs


def _azure_kwargs(options: dict) -> dict:
    """Map user options to obstore AzureStore kwargs."""
    kwargs = {}
    if "account_name" in options:
        kwargs["account_name"] = options["account_name"]
    if "account_key" in options:
        kwargs["account_key"] = options["account_key"]
    if "sas_token" in options:
        kwargs["sas_token"] = options["sas_token"]
    if options.get("anonymous"):
        kwargs["skip_signature"] = True
    return kwargs


def _build_obstore(url: str, options: dict):
    """Create an obstore store instance from a URL and options dict.

    Supports:
    - s3://bucket/prefix (and S3-compatible via endpoint_url option)
    - gs://bucket/prefix
    - az://container/prefix
    - https://storage.googleapis.com/bucket/prefix (auto-detected as GCS)
    """
    from obstore.store import AzureStore as ObAzure
    from obstore.store import GCSStore as ObGCS
    from obstore.store import S3Store as ObS3

    if url.startswith("s3://"):
        bucket, prefix = _parse_bucket_prefix(url[5:])
        kwargs = _s3_kwargs(options)
        return ObS3(bucket, prefix=prefix or None, **kwargs)

    if url.startswith("gs://"):
        bucket, prefix = _parse_bucket_prefix(url[5:])
        kwargs = _gcs_kwargs(options)
        return ObGCS(bucket, prefix=prefix or None, **kwargs)

    if url.startswith("az://"):
        container, prefix = _parse_bucket_prefix(url[5:])
        kwargs = _azure_kwargs(options)
        return ObAzure(container, prefix=prefix or None, **kwargs)

    if url.startswith("https://storage.googleapis.com/"):
        bucket_path = url.replace("https://storage.googleapis.com/", "")
        bucket, prefix = _parse_bucket_prefix(bucket_path)
        kwargs = _gcs_kwargs(options)
        return ObGCS(bucket, prefix=prefix or None, **kwargs)

    raise ValueError(f"Unsupported remote URL for obstore: {url}")


class ObstoreRemoteStore(RemoteStore):
    """Remote store backed by obstore (S3, GCS, Azure, and S3-compatible services).

    Works with AWS S3, Google Cloud Storage, Azure Blob Storage,
    and any S3-compatible service (Cloudflare R2, MinIO, OVH, Wasabi,
    DigitalOcean Spaces, Backblaze B2, etc.) via the endpoint_url option.
    """

    def __init__(self, url: str, options: dict | None = None, _store=None):
        self.url = url
        self.options = options or {}
        self._store = _store or _build_obstore(url, self.options)

    def get_manifest(self) -> tuple[Manifest | None, str | None]:
        import obstore as obs

        try:
            result = obs.get(self._store, "manifest.json")
            content = result.bytes().to_bytes().decode("utf-8")
            manifest = Manifest.from_json(content)
            manifest_hash = compute_hash(content.encode("utf-8"))
            return manifest, manifest_hash
        except FileNotFoundError:
            return None, None

    def put_manifest(self, manifest: Manifest) -> str:
        import obstore as obs

        content = manifest.to_json()
        obs.put(self._store, "manifest.json", content.encode("utf-8"))
        return compute_hash(content.encode("utf-8"))

    def get_resource(self, path: str) -> bytes | None:
        import obstore as obs

        try:
            result = obs.get(self._store, path)
            return result.bytes().to_bytes()
        except FileNotFoundError:
            return None

    def put_resource(self, path: str, data: bytes):
        import obstore as obs

        obs.put(self._store, path, data)

    def delete_resource(self, path: str):
        import obstore as obs

        try:
            obs.delete(self._store, path)
        except FileNotFoundError:
            pass  # Already gone

    def exists(self) -> bool:
        import obstore as obs

        try:
            # Try listing root — if bucket/container doesn't exist, this raises
            list(obs.list(self._store, prefix=""))
            return True
        except Exception:
            return False


def get_remote_store(url: str, options: dict | None = None) -> RemoteStore:
    """Factory function to create appropriate remote store for URL.

    Supports:
    - file:// or absolute paths → LocalFilesystemStore
    - s3://, gs://, az:// → ObstoreRemoteStore (native support)
    - https://storage.googleapis.com/ → ObstoreRemoteStore (auto-detected as GCS)

    For S3-compatible services (R2, MinIO, OVH, etc.), pass endpoint_url in options:
        options={"endpoint_url": "https://<account>.r2.cloudflarestorage.com"}
    """
    if url.startswith("file://") or url.startswith("/"):
        return LocalFilesystemStore(url)
    if url.startswith(("gs://", "s3://", "az://", "https://storage.googleapis.com/")):
        return ObstoreRemoteStore(url, options)
    raise ValueError(f"Unsupported remote URL: {url}")


# =============================================================================
# Status Computation
# =============================================================================

@dataclass
class CatalogStatus:
    """Current catalog status."""
    remote_url: str | None
    base_manifest_hash: str | None
    remote_manifest_hash: str | None
    is_behind: bool  # Remote has changes we don't have
    is_ahead: bool   # We have local changes
    is_dirty: bool   # Same as is_ahead (local modifications exist)
    diff: CatalogDiff
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "remote_url": self.remote_url,
            "base_manifest_hash": self.base_manifest_hash,
            "remote_manifest_hash": self.remote_manifest_hash,
            "is_behind": self.is_behind,
            "is_ahead": self.is_ahead,
            "is_dirty": self.is_dirty,
            "diff": self.diff.to_dict(),
            "error": self.error,
        }


def compute_status(
    catalog_path: Path,
    state: LocalState,
    remote_store: RemoteStore | None = None,
) -> CatalogStatus:
    """
    Compute current catalog status.

    Args:
        catalog_path: Path to .portolan directory
        state: Local state with base_manifest_hash
        remote_store: Optional remote store (created from state.remote_url if not provided)

    Returns:
        CatalogStatus with ahead/behind/dirty info
    """
    # Scan local resources
    resources_dir = catalog_path / "resources"
    local_resources = scan_local_resources(resources_dir)

    # Get base manifest resources (what we last synced from)
    base_resources: dict[str, str] = {}
    if state.base_manifest_hash:
        # Try to load cached base manifest
        base_manifest_path = catalog_path / "base_manifest.json"
        if base_manifest_path.exists():
            base_manifest = Manifest.from_json(base_manifest_path.read_text())
            base_resources = base_manifest.get_resource_map()

    # Compute diff from base
    diff = compute_diff(base_resources, local_resources)
    is_ahead = not diff.is_empty
    is_dirty = is_ahead

    # Check remote if configured
    remote_manifest_hash: str | None = None
    is_behind = False
    error: str | None = None

    if state.remote_url:
        try:
            if remote_store is None:
                remote_store = get_remote_store(state.remote_url)

            remote_manifest, remote_manifest_hash = remote_store.get_manifest()

            if remote_manifest_hash and state.base_manifest_hash:
                is_behind = remote_manifest_hash != state.base_manifest_hash
            elif remote_manifest_hash and not state.base_manifest_hash:
                # Remote has content but we have no base - we're behind
                is_behind = True

        except Exception as e:
            error = f"Could not fetch remote status: {e}"

    return CatalogStatus(
        remote_url=state.remote_url,
        base_manifest_hash=state.base_manifest_hash,
        remote_manifest_hash=remote_manifest_hash,
        is_behind=is_behind,
        is_ahead=is_ahead,
        is_dirty=is_dirty,
        diff=diff,
        error=error,
    )
