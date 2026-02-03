#!/usr/bin/env python3
"""
Portolan CLI - Manage datasets, users, and access for geospatial data infrastructure.

This CLI manages:
- Datasets: Add raquet/parquet files to the catalog
- Users: Create MinIO users with scoped access
- Policies: Grant/revoke access to datasets

Usage:
    portolan init                           # Initialize MinIO connection
    portolan dataset add <file> [options]   # Add a dataset
    portolan dataset list                   # List datasets
    portolan user add <name>                # Create a user
    portolan user list                      # List users
    portolan access grant <user> <dataset>  # Grant access
    portolan access revoke <user> <dataset> # Revoke access
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

# Config file location
CONFIG_DIR = Path.home() / ".portolan"
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class PortolanConfig:
    """Portolan configuration."""
    endpoint: str = "127.0.0.1:9000"
    access_key: str = "minioadmin"
    secret_key: str = "minioadmin123"
    bucket: str = "warehouse"
    use_ssl: bool = False
    mc_alias: str = "portolan"

    @classmethod
    def load(cls) -> "PortolanConfig":
        """Load config from file or return defaults."""
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE) as f:
                data = json.load(f)
                return cls(**data)
        return cls()

    def save(self):
        """Save config to file."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(asdict(self), f, indent=2)
        print(f"Config saved to {CONFIG_FILE}")


def run_mc(args: list[str], config: PortolanConfig, capture: bool = False) -> subprocess.CompletedProcess:
    """Run mc (MinIO client) command."""
    cmd = ["mc"] + args
    if capture:
        return subprocess.run(cmd, capture_output=True, text=True)
    return subprocess.run(cmd)


def ensure_mc_alias(config: PortolanConfig):
    """Ensure mc alias is configured."""
    protocol = "https" if config.use_ssl else "http"
    url = f"{protocol}://{config.endpoint}"
    run_mc([
        "alias", "set", config.mc_alias, url,
        config.access_key, config.secret_key
    ], config)


# ============== INIT ==============

def cmd_init(args, config: PortolanConfig):
    """Initialize Portolan configuration."""
    print("Portolan Configuration")
    print("=" * 40)

    # Prompt for values with defaults
    config.endpoint = input(f"MinIO endpoint [{config.endpoint}]: ").strip() or config.endpoint
    config.access_key = input(f"Access key [{config.access_key}]: ").strip() or config.access_key
    config.secret_key = input(f"Secret key [{config.secret_key}]: ").strip() or config.secret_key
    config.bucket = input(f"Bucket [{config.bucket}]: ").strip() or config.bucket
    use_ssl_input = input(f"Use SSL? [{'y' if config.use_ssl else 'n'}]: ").strip().lower()
    if use_ssl_input:
        config.use_ssl = use_ssl_input in ('y', 'yes', 'true', '1')

    config.save()

    # Configure mc alias
    ensure_mc_alias(config)

    # Ensure bucket exists
    result = run_mc(["ls", f"{config.mc_alias}/{config.bucket}"], config, capture=True)
    if result.returncode != 0:
        print(f"Creating bucket: {config.bucket}")
        run_mc(["mb", f"{config.mc_alias}/{config.bucket}"], config)

    # Create public prefix with anonymous access
    run_mc(["anonymous", "set", "download", f"{config.mc_alias}/{config.bucket}/public"], config)

    print("\nPortolan initialized successfully!")
    print(f"  Endpoint: {config.endpoint}")
    print(f"  Bucket: {config.bucket}")
    print(f"  Public prefix: s3://{config.bucket}/public/")
    print(f"  Private prefix: s3://{config.bucket}/private/")


# ============== DATASET ==============

def cmd_dataset_add(args, config: PortolanConfig):
    """Add a dataset to the catalog."""
    from iceberg_catalog import generate_sdi_catalog, extract_parquet_metadata

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        return 1

    # Determine visibility and path
    visibility = "public" if args.public else "private"
    tenant = args.tenant or "default"
    collection = args.collection or "datasets"
    dataset_id = args.id or file_path.stem

    if visibility == "public":
        base_path = f"public/{collection}"
    else:
        base_path = f"private/{tenant}/{collection}"

    base_url = f"s3://{config.bucket}/{base_path}"

    # Create local catalog
    output_dir = Path(f"/tmp/portolan_upload_{dataset_id}")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Extract metadata and generate catalog (auto-detects Raquet vs GeoParquet)
    metadata = extract_parquet_metadata(str(file_path))
    file_type = metadata.get("type", "geoparquet")
    format_name = metadata.get("format_name", "Parquet")
    spatial_representation = metadata.get("spatial_representation", "vector")
    raquet_info = metadata.get("raquet_info", {})
    geoparquet_info = metadata.get("geoparquet_info", {})
    stac_info = metadata.get("stac_info", {})

    # Use bounds from metadata if available
    bounds = metadata.get("bounds", stac_info.get("bbox", []))
    if bounds:
        stac_info["bbox"] = bounds

    collections_config = [{
        "name": collection,
        "title": args.title or f"{collection.title()} Collection",
        "items": [{
            "id": dataset_id,
            "title": args.title or f"{dataset_id}",
            "asset_path": str(file_path),
            "stac_info": stac_info,
            "iso_info": {
                "abstract": args.description or f"Dataset: {dataset_id}",
                "topic_category": args.topic or "imageryBaseMapsEarthCover",
                "format_name": format_name,
                "spatial_representation": spatial_representation,
                "license": args.license or "CC-BY-4.0",
            },
            "raquet_info": raquet_info if file_type == "raquet" else {},
            "geoparquet_info": geoparquet_info if file_type == "geoparquet" else {},
        }]
    }]

    generate_sdi_catalog(
        collections=collections_config,
        output_dir=str(output_dir),
        data_base_url=base_url,
        verbose=args.verbose,
    )

    # Upload to MinIO
    ensure_mc_alias(config)

    print(f"\nUploading to {base_url}...")
    run_mc([
        "cp", "--recursive",
        str(output_dir / "data") + "/",
        f"{config.mc_alias}/{config.bucket}/{base_path}/data/"
    ], config)

    run_mc([
        "cp", "--recursive",
        str(output_dir / "v1") + "/",
        f"{config.mc_alias}/{config.bucket}/{base_path}/v1/"
    ], config)

    # Cleanup
    import shutil
    shutil.rmtree(output_dir)

    print(f"\nDataset added successfully!")
    print(f"  ID: {dataset_id}")
    print(f"  Type: {format_name}")
    print(f"  Visibility: {visibility}")
    print(f"  Items table: {base_url}/data/{collection}/items/metadata/v1.metadata.json")
    print(f"  Data file: {base_url}/data/{collection}/{dataset_id}/{dataset_id}.parquet")

    if visibility == "private":
        print(f"\n  To grant access: portolan access grant <user> {tenant}/{collection}/{dataset_id}")

    return 0


def cmd_dataset_list(args, config: PortolanConfig):
    """List datasets in the catalog."""
    ensure_mc_alias(config)

    print("Public datasets:")
    print("-" * 40)
    result = run_mc([
        "ls", "--recursive", f"{config.mc_alias}/{config.bucket}/public/"
    ], config, capture=True)

    # Parse and show only metadata.json files (indicate tables)
    for line in result.stdout.splitlines():
        if "v1.metadata.json" in line:
            # Extract path
            parts = line.split()
            if len(parts) >= 5:
                path = parts[-1]
                # Extract collection/table from path
                print(f"  {path}")

    print("\nPrivate datasets:")
    print("-" * 40)
    result = run_mc([
        "ls", "--recursive", f"{config.mc_alias}/{config.bucket}/private/"
    ], config, capture=True)

    for line in result.stdout.splitlines():
        if "v1.metadata.json" in line:
            parts = line.split()
            if len(parts) >= 5:
                path = parts[-1]
                print(f"  {path}")

    return 0


# ============== USER ==============

def cmd_user_add(args, config: PortolanConfig):
    """Create a new user."""
    ensure_mc_alias(config)

    username = args.username
    password = args.password

    if not password:
        import secrets
        password = secrets.token_urlsafe(16)
        print(f"Generated password: {password}")

    # Create user
    result = run_mc([
        "admin", "user", "add", config.mc_alias, username, password
    ], config)

    if result.returncode == 0:
        print(f"\nUser '{username}' created successfully!")
        print(f"  Access key: {username}")
        print(f"  Secret key: {password}")
        print(f"\n  To grant access: portolan access grant {username} <tenant>/<collection>/<dataset>")

    return result.returncode


def cmd_user_list(args, config: PortolanConfig):
    """List users."""
    ensure_mc_alias(config)
    run_mc(["admin", "user", "ls", config.mc_alias], config)
    return 0


def cmd_user_remove(args, config: PortolanConfig):
    """Remove a user."""
    ensure_mc_alias(config)
    run_mc(["admin", "user", "rm", config.mc_alias, args.username], config)
    return 0


# ============== ACCESS ==============

def cmd_access_grant(args, config: PortolanConfig):
    """Grant user access to a dataset path."""
    ensure_mc_alias(config)

    username = args.username
    path = args.path  # e.g., "carto/imagery/europe" or "tenant/collection/dataset"

    # Create policy name from path
    policy_name = f"access-{path.replace('/', '-')}"

    # Create policy JSON
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{config.bucket}/private/{path}/*"]
            },
            {
                "Effect": "Allow",
                "Action": ["s3:ListBucket"],
                "Resource": [f"arn:aws:s3:::{config.bucket}"],
                "Condition": {
                    "StringLike": {"s3:prefix": [f"private/{path}/*"]}
                }
            }
        ]
    }

    # Write policy to temp file
    policy_file = Path(f"/tmp/portolan-policy-{policy_name}.json")
    with open(policy_file, "w") as f:
        json.dump(policy, f, indent=2)

    # Create or update policy
    run_mc(["admin", "policy", "create", config.mc_alias, policy_name, str(policy_file)], config)

    # Attach policy to user
    result = run_mc([
        "admin", "policy", "attach", config.mc_alias, policy_name, "--user", username
    ], config)

    # Cleanup
    policy_file.unlink()

    if result.returncode == 0:
        print(f"\nAccess granted!")
        print(f"  User: {username}")
        print(f"  Path: private/{path}/*")
        print(f"  Policy: {policy_name}")

    return result.returncode


def cmd_access_revoke(args, config: PortolanConfig):
    """Revoke user access to a dataset path."""
    ensure_mc_alias(config)

    path = args.path
    policy_name = f"access-{path.replace('/', '-')}"

    # Detach policy from user
    result = run_mc([
        "admin", "policy", "detach", config.mc_alias, policy_name, "--user", args.username
    ], config)

    if result.returncode == 0:
        print(f"Access revoked: {args.username} -> {path}")

    return result.returncode


def cmd_access_list(args, config: PortolanConfig):
    """List access policies."""
    ensure_mc_alias(config)

    if args.username:
        # Show policies for specific user
        run_mc(["admin", "user", "info", config.mc_alias, args.username], config)
    else:
        # List all policies
        run_mc(["admin", "policy", "ls", config.mc_alias], config)

    return 0


# ============== MANIFEST ==============

def cmd_manifest_update(args, config: PortolanConfig):
    """Update the manifest.json file with all discovered catalogs."""
    ensure_mc_alias(config)

    from datetime import datetime

    manifest = {
        "version": "1.0",
        "updated": datetime.utcnow().isoformat() + "Z",
        "catalogs": {
            "public": [],
            "private": []
        }
    }

    # Scan for items tables
    result = run_mc([
        "find", f"{config.mc_alias}/{config.bucket}",
        "--name", "v1.metadata.json",
        "--path", "*/items/metadata/*"
    ], config, capture=True)

    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        # Parse path: portolan/warehouse/public/imagery/data/imagery/items/metadata/v1.metadata.json
        path = line.replace(f"{config.mc_alias}/{config.bucket}/", "")

        if path.startswith("public/"):
            # Extract collection from path
            parts = path.split("/")
            if "data" in parts:
                idx = parts.index("data")
                collection = parts[idx + 1] if idx + 1 < len(parts) else "unknown"
            else:
                collection = parts[1] if len(parts) > 1 else "unknown"

            manifest["catalogs"]["public"].append({
                "path": path,
                "collection": collection
            })

        elif path.startswith("private/"):
            parts = path.split("/")
            tenant = parts[1] if len(parts) > 1 else "unknown"
            if "data" in parts:
                idx = parts.index("data")
                collection = parts[idx + 1] if idx + 1 < len(parts) else "unknown"
            else:
                collection = parts[2] if len(parts) > 2 else "unknown"

            manifest["catalogs"]["private"].append({
                "path": path,
                "tenant": tenant,
                "collection": collection
            })

    # Write manifest to temp file
    manifest_file = Path("/tmp/portolan-manifest.json")
    with open(manifest_file, "w") as f:
        json.dump(manifest, f, indent=2)

    # Upload to MinIO
    run_mc([
        "cp", str(manifest_file), f"{config.mc_alias}/{config.bucket}/manifest.json"
    ], config)

    # Make it public
    run_mc([
        "anonymous", "set", "download", f"{config.mc_alias}/{config.bucket}/manifest.json"
    ], config)

    manifest_file.unlink()

    print(f"Manifest updated with {len(manifest['catalogs']['public'])} public and {len(manifest['catalogs']['private'])} private catalogs")
    return 0


# ============== WEB ==============

def get_web_dir() -> Path:
    """Get the web directory path."""
    # Check if we're in the project directory
    web_dir = Path(__file__).parent / "web"
    if web_dir.exists():
        return web_dir
    # Fallback to current directory
    return Path.cwd() / "web"


def cmd_web_serve(args, config: PortolanConfig):
    """Serve the web UI locally."""
    import http.server
    import socketserver

    web_dir = get_web_dir()
    if not web_dir.exists():
        print(f"Error: Web directory not found at {web_dir}", file=sys.stderr)
        return 1

    port = args.port

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(web_dir), **kwargs)

    print(f"Serving web UI at http://127.0.0.1:{port}")
    print(f"MinIO endpoint: {config.endpoint}")
    print(f"Bucket: {config.bucket}")
    print(f"\nPress Ctrl+C to stop")

    with socketserver.TCPServer(("", port), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped")

    return 0


def cmd_web_deploy(args, config: PortolanConfig):
    """Deploy web UI to storage."""
    ensure_mc_alias(config)

    web_dir = get_web_dir()
    if not web_dir.exists():
        print(f"Error: Web directory not found at {web_dir}", file=sys.stderr)
        return 1

    # Upload index.html
    index_file = web_dir / "index.html"
    if index_file.exists():
        run_mc([
            "cp", str(index_file), f"{config.mc_alias}/{config.bucket}/index.html"
        ], config)
        run_mc([
            "anonymous", "set", "download", f"{config.mc_alias}/{config.bucket}/index.html"
        ], config)

    # Update manifest
    cmd_manifest_update(args, config)

    protocol = "https" if config.use_ssl else "http"
    print(f"\nWeb UI deployed!")
    print(f"  URL: {protocol}://{config.endpoint}/{config.bucket}/index.html")

    return 0


# ============== STATUS ==============

def cmd_status(args, config: PortolanConfig):
    """Show Portolan status."""
    print("Portolan Status")
    print("=" * 40)
    print(f"Config file: {CONFIG_FILE}")
    print(f"Endpoint: {config.endpoint}")
    print(f"Bucket: {config.bucket}")
    print(f"SSL: {config.use_ssl}")
    print()

    ensure_mc_alias(config)

    print("MinIO connection:")
    result = run_mc(["admin", "info", config.mc_alias], config, capture=True)
    if result.returncode == 0:
        print("  Connected successfully")
        # Show bucket info
        run_mc(["ls", f"{config.mc_alias}/{config.bucket}"], config)
    else:
        print("  Connection failed")
        print(result.stderr)

    return 0


# ============== MAIN ==============

def main():
    parser = argparse.ArgumentParser(
        description="Portolan CLI - Manage geospatial data infrastructure",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # init
    init_parser = subparsers.add_parser("init", help="Initialize Portolan configuration")
    init_parser.set_defaults(func=cmd_init)

    # status
    status_parser = subparsers.add_parser("status", help="Show Portolan status")
    status_parser.set_defaults(func=cmd_status)

    # manifest
    manifest_parser = subparsers.add_parser("manifest", help="Manage web manifest")
    manifest_sub = manifest_parser.add_subparsers(dest="manifest_command")

    manifest_update = manifest_sub.add_parser("update", help="Update manifest.json for web UI")
    manifest_update.set_defaults(func=cmd_manifest_update)

    # web
    web_parser = subparsers.add_parser("web", help="Web UI management")
    web_sub = web_parser.add_subparsers(dest="web_command")

    web_serve = web_sub.add_parser("serve", help="Serve web UI locally")
    web_serve.add_argument("--port", "-p", type=int, default=8080, help="Port (default: 8080)")
    web_serve.set_defaults(func=cmd_web_serve)

    web_deploy = web_sub.add_parser("deploy", help="Deploy web UI to storage")
    web_deploy.set_defaults(func=cmd_web_deploy)

    # dataset
    dataset_parser = subparsers.add_parser("dataset", help="Manage datasets")
    dataset_sub = dataset_parser.add_subparsers(dest="dataset_command")

    # dataset add
    dataset_add = dataset_sub.add_parser("add", help="Add a dataset")
    dataset_add.add_argument("file", help="Path to raquet/parquet file")
    dataset_add.add_argument("--id", help="Dataset ID (default: filename)")
    dataset_add.add_argument("--title", help="Dataset title")
    dataset_add.add_argument("--description", help="Dataset description")
    dataset_add.add_argument("--collection", "-c", default="datasets", help="Collection name")
    dataset_add.add_argument("--tenant", "-t", default="default", help="Tenant (for private datasets)")
    dataset_add.add_argument("--public", action="store_true", help="Make dataset public")
    dataset_add.add_argument("--topic", default="imageryBaseMapsEarthCover", help="ISO topic category")
    dataset_add.add_argument("--license", default="CC-BY-4.0", help="License")
    dataset_add.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    dataset_add.set_defaults(func=cmd_dataset_add)

    # dataset list
    dataset_list = dataset_sub.add_parser("list", help="List datasets")
    dataset_list.set_defaults(func=cmd_dataset_list)

    # user
    user_parser = subparsers.add_parser("user", help="Manage users")
    user_sub = user_parser.add_subparsers(dest="user_command")

    # user add
    user_add = user_sub.add_parser("add", help="Add a user")
    user_add.add_argument("username", help="Username")
    user_add.add_argument("--password", "-p", help="Password (auto-generated if not provided)")
    user_add.set_defaults(func=cmd_user_add)

    # user list
    user_list = user_sub.add_parser("list", help="List users")
    user_list.set_defaults(func=cmd_user_list)

    # user remove
    user_rm = user_sub.add_parser("remove", help="Remove a user")
    user_rm.add_argument("username", help="Username")
    user_rm.set_defaults(func=cmd_user_remove)

    # access
    access_parser = subparsers.add_parser("access", help="Manage access control")
    access_sub = access_parser.add_subparsers(dest="access_command")

    # access grant
    access_grant = access_sub.add_parser("grant", help="Grant access to a dataset")
    access_grant.add_argument("username", help="Username")
    access_grant.add_argument("path", help="Dataset path (tenant/collection/dataset)")
    access_grant.set_defaults(func=cmd_access_grant)

    # access revoke
    access_revoke = access_sub.add_parser("revoke", help="Revoke access")
    access_revoke.add_argument("username", help="Username")
    access_revoke.add_argument("path", help="Dataset path")
    access_revoke.set_defaults(func=cmd_access_revoke)

    # access list
    access_list = access_sub.add_parser("list", help="List access policies")
    access_list.add_argument("--user", "-u", dest="username", help="Show policies for user")
    access_list.set_defaults(func=cmd_access_list)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    config = PortolanConfig.load()

    if hasattr(args, 'func'):
        return args.func(args, config)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
