"""
Namespace utilities for Portolan.

Namespaces use dots as hierarchy separators (e.g., "europe.spain.madrid").
On disk they're stored as flat directory names with dots in the name.
Different output formats encode them differently:

- Iceberg REST / BigQuery: underscores ("europe_spain_madrid")
- STAC: nested catalog/collection tree
- ISO 19139: nested directory tree
- CLI display: indented tree view
"""

from __future__ import annotations

import re

NAMESPACE_PATTERN = re.compile(r'^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$')


def validate_namespace(namespace: str) -> str | None:
    """Validate a namespace string.

    Returns an error message if invalid, None if valid.

    Rules:
    - Lowercase letters, digits, and underscores, separated by dots
    - Each segment must start with a letter
    - No leading/trailing/consecutive dots
    - At least one character
    """
    if not namespace:
        return "Namespace cannot be empty"

    if not NAMESPACE_PATTERN.match(namespace):
        if ".." in namespace:
            return "Namespace cannot contain consecutive dots"
        if namespace.startswith(".") or namespace.endswith("."):
            return "Namespace cannot start or end with a dot"
        if any(c.isupper() for c in namespace):
            return "Namespace must be lowercase"
        if any(not (c.isalnum() or c in (".", "_")) for c in namespace):
            return "Namespace may only contain lowercase letters, digits, underscores, and dots"
        for segment in namespace.split("."):
            if segment and segment[0].isdigit():
                return f"Each segment must start with a letter, got '{segment}'"
        return "Invalid namespace format (use lowercase letters, digits, underscores, and dots)"

    return None


def namespace_to_iceberg(namespace: str) -> str:
    """Convert dotted namespace to Iceberg-safe underscore format.

    BigQuery only allows letters, numbers, and underscores in dataset names.

    Examples:
        "europe.spain.madrid" → "europe_spain_madrid"
        "default" → "default"
    """
    return namespace.replace(".", "_")


def namespace_parts(namespace: str) -> list[str]:
    """Split namespace into its hierarchy components.

    Examples:
        "europe.spain.madrid" → ["europe", "spain", "madrid"]
        "default" → ["default"]
    """
    return namespace.split(".")


def namespace_depth(namespace: str) -> int:
    """Return the hierarchy depth of a namespace.

    Examples:
        "default" → 1
        "europe.spain" → 2
        "europe.spain.madrid" → 3
    """
    return namespace.count(".") + 1


def build_namespace_tree(namespaces: list[str]) -> dict:
    """Build a tree structure from a list of dot-separated namespaces.

    Used for rendering tree views in CLI and generating nested STAC catalogs.

    Example:
        ["europe.spain.madrid", "europe.france", "default"]
        → {
            "default": {},
            "europe": {
                "france": {},
                "spain": {
                    "madrid": {}
                }
            }
          }
    """
    tree: dict = {}
    for ns in sorted(namespaces):
        node = tree
        for part in namespace_parts(ns):
            node = node.setdefault(part, {})
    return tree


def arcgis_folder_to_namespace(base_namespace: str, folder_path: str) -> str:
    """Convert an ArcGIS server folder path to a dot-separated namespace.

    Args:
        base_namespace: The base namespace (e.g., "arcgis")
        folder_path: The folder path from the ArcGIS server (e.g., "Environment/Water")

    Examples:
        ("arcgis", "Environment/Water") → "arcgis.environment.water"
        ("arcgis", "") → "arcgis"
        ("myserver", "Folder_1/Sub Folder") → "myserver.folder1.subfolder"
    """
    if not folder_path:
        return base_namespace

    # Normalize folder path: lowercase, replace / with ., clean up invalid chars
    parts = folder_path.strip("/").split("/")
    clean_parts = []
    for part in parts:
        # Lowercase, remove non-alphanumeric, ensure starts with letter
        clean = re.sub(r'[^a-z0-9]', '', part.lower())
        if clean and clean[0].isdigit():
            clean = "f" + clean  # Prefix with 'f' if starts with digit
        if clean:
            clean_parts.append(clean)

    if not clean_parts:
        return base_namespace

    return f"{base_namespace}.{'.'.join(clean_parts)}"
