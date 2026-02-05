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


class GCSStore(RemoteStore):
    """Remote store using Google Cloud Storage."""

    def __init__(self, url: str, options: dict | None = None):
        # Parse gs://bucket/prefix
        if url.startswith("gs://"):
            url = url[5:]
        parts = url.split("/", 1)
        self.bucket = parts[0]
        self.prefix = parts[1] if len(parts) > 1 else ""
        self.options = options or {}

        # Convert to HTTPS URL for fetching
        self.base_url = f"https://storage.googleapis.com/{self.bucket}"
        if self.prefix:
            self.base_url += f"/{self.prefix}"

    def _get_path(self, path: str) -> str:
        """Get full path with prefix."""
        if self.prefix:
            return f"{self.prefix}/{path}"
        return path

    def get_manifest(self) -> tuple[Manifest | None, str | None]:
        import time

        import httpx

        # Add cache-busting query param to avoid stale cached responses
        url = f"{self.base_url}/manifest.json?_t={int(time.time())}"
        headers = {"Cache-Control": "no-cache"}
        try:
            response = httpx.get(url, follow_redirects=True, timeout=30, headers=headers)
            if response.status_code == 404:
                return None, None
            response.raise_for_status()
            content = response.text
            manifest = Manifest.from_json(content)
            manifest_hash = compute_hash(content.encode('utf-8'))
            return manifest, manifest_hash
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None, None
            raise

    def put_manifest(self, manifest: Manifest) -> str:
        import subprocess
        import tempfile

        content = manifest.to_json()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            gcs_path = f"gs://{self.bucket}/{self._get_path('manifest.json')}"
            subprocess.run(
                ["gsutil", "cp", temp_path, gcs_path],
                capture_output=True,
                check=True
            )
        finally:
            Path(temp_path).unlink()

        return compute_hash(content.encode('utf-8'))

    def get_resource(self, path: str) -> bytes | None:
        import time

        import httpx

        # Add cache-busting query param
        url = f"{self.base_url}/{path}?_t={int(time.time())}"
        headers = {"Cache-Control": "no-cache"}
        try:
            response = httpx.get(url, follow_redirects=True, timeout=30, headers=headers)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.content
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    def put_resource(self, path: str, data: bytes):
        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile(mode='wb', delete=False) as f:
            f.write(data)
            temp_path = f.name

        try:
            gcs_path = f"gs://{self.bucket}/{self._get_path(path)}"
            subprocess.run(
                ["gsutil", "cp", temp_path, gcs_path],
                capture_output=True,
                check=True
            )
        finally:
            Path(temp_path).unlink()

    def delete_resource(self, path: str):
        import subprocess

        gcs_path = f"gs://{self.bucket}/{self._get_path(path)}"
        subprocess.run(
            ["gsutil", "rm", "-f", gcs_path],
            capture_output=True,
            check=False  # Don't fail if file doesn't exist
        )

    def exists(self) -> bool:
        import subprocess

        result = subprocess.run(
            ["gsutil", "ls", f"gs://{self.bucket}"],
            capture_output=True
        )
        return result.returncode == 0


class S3Store(RemoteStore):
    """Remote store using Amazon S3."""

    def __init__(self, url: str, options: dict | None = None):
        # Parse s3://bucket/prefix
        if url.startswith("s3://"):
            url = url[5:]
        parts = url.split("/", 1)
        self.bucket = parts[0]
        self.prefix = parts[1] if len(parts) > 1 else ""
        self.options = options or {}
        self.region = options.get("region", "us-east-1") if options else "us-east-1"

    def _get_path(self, path: str) -> str:
        if self.prefix:
            return f"{self.prefix}/{path}"
        return path

    def get_manifest(self) -> tuple[Manifest | None, str | None]:
        import subprocess

        s3_path = f"s3://{self.bucket}/{self._get_path('manifest.json')}"
        result = subprocess.run(
            ["aws", "s3", "cp", s3_path, "-"],
            capture_output=True
        )

        if result.returncode != 0:
            return None, None

        content = result.stdout.decode('utf-8')
        manifest = Manifest.from_json(content)
        manifest_hash = compute_hash(content.encode('utf-8'))
        return manifest, manifest_hash

    def put_manifest(self, manifest: Manifest) -> str:
        import subprocess
        import tempfile

        content = manifest.to_json()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            s3_path = f"s3://{self.bucket}/{self._get_path('manifest.json')}"
            subprocess.run(
                ["aws", "s3", "cp", temp_path, s3_path],
                capture_output=True,
                check=True
            )
        finally:
            Path(temp_path).unlink()

        return compute_hash(content.encode('utf-8'))

    def get_resource(self, path: str) -> bytes | None:
        import subprocess

        s3_path = f"s3://{self.bucket}/{self._get_path(path)}"
        result = subprocess.run(
            ["aws", "s3", "cp", s3_path, "-"],
            capture_output=True
        )

        if result.returncode != 0:
            return None
        return result.stdout

    def put_resource(self, path: str, data: bytes):
        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile(mode='wb', delete=False) as f:
            f.write(data)
            temp_path = f.name

        try:
            s3_path = f"s3://{self.bucket}/{self._get_path(path)}"
            subprocess.run(
                ["aws", "s3", "cp", temp_path, s3_path],
                capture_output=True,
                check=True
            )
        finally:
            Path(temp_path).unlink()

    def delete_resource(self, path: str):
        import subprocess

        s3_path = f"s3://{self.bucket}/{self._get_path(path)}"
        subprocess.run(
            ["aws", "s3", "rm", s3_path],
            capture_output=True,
            check=False
        )

    def exists(self) -> bool:
        import subprocess

        result = subprocess.run(
            ["aws", "s3", "ls", f"s3://{self.bucket}"],
            capture_output=True
        )
        return result.returncode == 0


def get_remote_store(url: str, options: dict | None = None) -> RemoteStore:
    """Factory function to create appropriate remote store for URL."""
    if url.startswith("file://") or url.startswith("/"):
        return LocalFilesystemStore(url)
    elif url.startswith("gs://"):
        return GCSStore(url, options)
    elif url.startswith("s3://"):
        return S3Store(url, options)
    elif url.startswith("https://storage.googleapis.com/"):
        # Convert to gs:// format
        bucket_path = url.replace("https://storage.googleapis.com/", "")
        return GCSStore(f"gs://{bucket_path}", options)
    else:
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
