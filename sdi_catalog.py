"""
STAC + ISO 19115 SDI Catalog Support.

This module handles:
- STAC + ISO 19115 schema definition for items tables
- Metadata record creation (combining STAC core with ISO 19115 fields)
- Parquet metadata extraction (auto-detecting Raquet vs GeoParquet)
- Multi-collection SDI catalog generation with Iceberg backing
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from iceberg_metadata import (
    IcebergTable,
    add_iceberg_field_ids,
    create_table_metadata,
    generate_manifest_files,
    parquet_to_iceberg_table,
)
from iceberg_rest_catalog import (
    create_catalog_config,
    create_load_table_response,
    create_namespace_detail,
    create_namespaces_list,
    create_tables_list,
)


def create_stac_iso_schema() -> pa.Schema:
    """
    Create PyArrow schema for STAC + ISO 19115 items table.

    This schema combines STAC core fields with standard-depth ISO 19115 metadata
    for SDI compliance. Uses Iceberg-compatible types.

    Returns:
        PyArrow schema for the items table
    """
    return pa.schema([
        # Primary identifier
        pa.field("id", pa.string(), nullable=False),

        # STAC core fields
        pa.field("geometry", pa.binary()),  # WKB geometry (Iceberg geometry support varies)
        pa.field("bbox_west", pa.float64()),
        pa.field("bbox_south", pa.float64()),
        pa.field("bbox_east", pa.float64()),
        pa.field("bbox_north", pa.float64()),
        pa.field("datetime", pa.timestamp("us", tz="UTC")),
        pa.field("start_datetime", pa.timestamp("us", tz="UTC")),
        pa.field("end_datetime", pa.timestamp("us", tz="UTC")),

        # STAC assets and links (JSON as string)
        pa.field("assets", pa.string()),
        pa.field("links", pa.string()),

        # ISO 19115 Core Identification
        pa.field("title", pa.string(), nullable=False),
        pa.field("abstract", pa.string()),
        pa.field("topic_category", pa.string()),
        pa.field("keywords", pa.string()),  # JSON array

        # ISO 19115 Spatial Reference
        pa.field("spatial_resolution", pa.float64()),
        pa.field("spatial_resolution_unit", pa.string()),
        pa.field("reference_system", pa.string()),
        pa.field("spatial_representation", pa.string()),

        # ISO 19115 Contact
        pa.field("contact_organization", pa.string()),
        pa.field("contact_email", pa.string()),
        pa.field("contact_role", pa.string()),

        # ISO 19115 Distribution
        pa.field("format_name", pa.string()),
        pa.field("format_version", pa.string()),
        pa.field("access_url", pa.string()),

        # ISO 19115 Quality & Lineage
        pa.field("lineage", pa.string()),
        pa.field("quality_scope", pa.string()),

        # ISO 19115 Constraints
        pa.field("license", pa.string()),
        pa.field("use_constraints", pa.string()),
        pa.field("access_constraints", pa.string()),

        # Metadata Admin
        pa.field("metadata_date", pa.timestamp("us", tz="UTC")),
        pa.field("created_at", pa.timestamp("us", tz="UTC")),
        pa.field("updated_at", pa.timestamp("us", tz="UTC")),

        # Raquet-specific fields (for raster items)
        pa.field("raquet_num_bands", pa.int32()),
        pa.field("raquet_band_names", pa.string()),  # JSON array
        pa.field("raquet_compression", pa.string()),
        pa.field("raquet_block_size", pa.int32()),
        pa.field("raquet_min_zoom", pa.int32()),
        pa.field("raquet_max_zoom", pa.int32()),
        pa.field("raquet_bounds", pa.string()),  # JSON array [west, south, east, north]
    ])


def create_stac_iso_record(
    item_id: str,
    title: str,
    stac_info: dict | None = None,
    iso_info: dict | None = None,
    raquet_info: dict | None = None,
) -> dict:
    """
    Create a single STAC + ISO 19115 metadata record.

    Args:
        item_id: Unique identifier for the item
        title: Dataset title (required)
        stac_info: STAC fields dict with keys:
            - geometry: WKB bytes or WKT string
            - bbox: [west, south, east, north]
            - datetime: ISO timestamp string or datetime
            - start_datetime, end_datetime: for temporal ranges
            - assets: dict of assets {"name": {"href": "...", "type": "..."}}
            - links: list of link dicts
        iso_info: ISO 19115 fields dict with keys:
            - abstract, topic_category, keywords (list)
            - spatial_resolution, spatial_resolution_unit, reference_system
            - contact_organization, contact_email, contact_role
            - format_name, format_version, access_url
            - lineage, quality_scope
            - license, use_constraints, access_constraints
        raquet_info: Raquet-specific fields dict with keys:
            - num_bands, band_names (list), compression
            - block_size, min_zoom, max_zoom, bounds

    Returns:
        Dict ready for PyArrow table creation
    """
    from datetime import datetime, timezone

    stac = stac_info or {}
    iso = iso_info or {}
    raquet = raquet_info or {}

    now = datetime.now(timezone.utc)

    # Parse bbox
    bbox = stac.get("bbox", [None, None, None, None])

    # Handle datetime parsing
    def parse_dt(val):
        if val is None:
            return None
        if isinstance(val, datetime):
            return val
        if isinstance(val, str):
            try:
                return datetime.fromisoformat(val.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    return {
        # Primary identifier
        "id": item_id,

        # STAC core
        "geometry": stac.get("geometry"),  # WKB bytes or None
        "bbox_west": bbox[0] if len(bbox) > 0 else None,
        "bbox_south": bbox[1] if len(bbox) > 1 else None,
        "bbox_east": bbox[2] if len(bbox) > 2 else None,
        "bbox_north": bbox[3] if len(bbox) > 3 else None,
        "datetime": parse_dt(stac.get("datetime")),
        "start_datetime": parse_dt(stac.get("start_datetime")),
        "end_datetime": parse_dt(stac.get("end_datetime")),

        # STAC assets/links as JSON strings
        "assets": json.dumps(stac.get("assets", {})) if stac.get("assets") else None,
        "links": json.dumps(stac.get("links", [])) if stac.get("links") else None,

        # ISO 19115 Core Identification
        "title": title,
        "abstract": iso.get("abstract"),
        "topic_category": iso.get("topic_category"),
        "keywords": json.dumps(iso.get("keywords", [])) if iso.get("keywords") else None,

        # ISO 19115 Spatial Reference
        "spatial_resolution": iso.get("spatial_resolution"),
        "spatial_resolution_unit": iso.get("spatial_resolution_unit"),
        "reference_system": iso.get("reference_system"),
        "spatial_representation": iso.get("spatial_representation"),

        # ISO 19115 Contact
        "contact_organization": iso.get("contact_organization"),
        "contact_email": iso.get("contact_email"),
        "contact_role": iso.get("contact_role"),

        # ISO 19115 Distribution
        "format_name": iso.get("format_name"),
        "format_version": iso.get("format_version"),
        "access_url": iso.get("access_url"),

        # ISO 19115 Quality & Lineage
        "lineage": iso.get("lineage"),
        "quality_scope": iso.get("quality_scope"),

        # ISO 19115 Constraints
        "license": iso.get("license"),
        "use_constraints": iso.get("use_constraints"),
        "access_constraints": iso.get("access_constraints"),

        # Metadata Admin
        "metadata_date": parse_dt(iso.get("metadata_date")) or now,
        "created_at": now,
        "updated_at": now,

        # Raquet-specific
        "raquet_num_bands": raquet.get("num_bands"),
        "raquet_band_names": json.dumps(raquet.get("band_names", [])) if raquet.get("band_names") else None,
        "raquet_compression": raquet.get("compression"),
        "raquet_block_size": raquet.get("block_size"),
        "raquet_min_zoom": raquet.get("min_zoom"),
        "raquet_max_zoom": raquet.get("max_zoom"),
        "raquet_bounds": json.dumps(raquet.get("bounds", [])) if raquet.get("bounds") else None,
    }


def create_items_table(
    records: list[dict],
    output_dir: str | Path,
    collection: str,
) -> IcebergTable:
    """
    Create an Iceberg items table from STAC+ISO metadata records.

    Args:
        records: List of metadata record dicts (from create_stac_iso_record)
        output_dir: Base output directory for the catalog
        collection: Collection/namespace name

    Returns:
        IcebergTable for the items table
    """
    output_path = Path(output_dir)
    schema = create_stac_iso_schema()

    # Create PyArrow table from records
    arrays = {}
    for field in schema:
        values = [r.get(field.name) for r in records]
        arrays[field.name] = values

    table = pa.table(arrays, schema=schema)

    # Write to parquet
    items_dir = output_path / "data" / collection / "items"
    items_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = items_dir / "items.parquet"
    pq.write_table(table, parquet_path, compression="zstd")

    # Add Iceberg field IDs
    add_iceberg_field_ids(parquet_path)

    # Create IcebergTable
    return parquet_to_iceberg_table(
        str(parquet_path),
        table_name="items",
    )


def extract_raquet_metadata(parquet_path: str | Path) -> dict:
    """
    Extract metadata from a raquet file for STAC+ISO record creation.

    Args:
        parquet_path: Path to raquet parquet file

    Returns:
        Dict with raquet_info and stac bbox/bounds
    """
    import pyarrow.compute as pc

    table = pq.read_table(parquet_path)

    # Find metadata row (block = 0)
    metadata_rows = table.filter(pc.equal(table.column("block"), 0))

    if len(metadata_rows) > 0:
        metadata_json = metadata_rows.column("metadata")[0].as_py()
        if metadata_json:
            metadata = json.loads(metadata_json)

            bands = metadata.get("bands", [])
            bounds = metadata.get("bounds", [])

            return {
                "raquet_info": {
                    "num_bands": len(bands),
                    "band_names": [b.get("name", f"band_{i+1}") for i, b in enumerate(bands)],
                    "compression": metadata.get("compression"),
                    "block_size": metadata.get("block_width", 256),
                    "min_zoom": metadata.get("minresolution"),
                    "max_zoom": metadata.get("maxresolution"),
                    "bounds": bounds,
                },
                "stac_info": {
                    "bbox": bounds,
                },
            }

    return {"raquet_info": {}, "stac_info": {}}


def extract_geoparquet_metadata(parquet_path: str) -> dict:
    """
    Extract metadata from a GeoParquet file.

    Returns:
        Dict with geoparquet_info and stac bbox/bounds
    """
    import geopandas as gpd

    gdf = gpd.read_parquet(parquet_path)

    # Get bounds [minx, miny, maxx, maxy]
    bounds = gdf.total_bounds.tolist()

    # Get geometry types
    geom_types = gdf.geometry.geom_type.unique().tolist()

    # Determine spatial representation
    point_types = {"Point", "MultiPoint"}
    line_types = {"LineString", "MultiLineString"}
    poly_types = {"Polygon", "MultiPolygon"}

    if all(g in point_types for g in geom_types):
        spatial_rep = "point"
    elif all(g in line_types for g in geom_types):
        spatial_rep = "line"
    elif all(g in poly_types for g in geom_types):
        spatial_rep = "polygon"
    else:
        spatial_rep = "mixed"

    return {
        "geoparquet_info": {
            "num_features": len(gdf),
            "geometry_types": geom_types,
            "columns": [c for c in gdf.columns if c != "geometry"],
            "crs": str(gdf.crs) if gdf.crs else "EPSG:4326",
        },
        "stac_info": {
            "bbox": bounds,
        },
        "spatial_representation": spatial_rep,
        "bounds": bounds,
    }


def detect_parquet_type(parquet_path: str) -> str:
    """
    Detect whether a parquet file is Raquet (raster) or GeoParquet (vector).

    Returns:
        "raquet" or "geoparquet"
    """
    pf = pq.ParquetFile(parquet_path)
    columns = pf.schema_arrow.names

    if "block" in columns and "metadata" in columns:
        return "raquet"
    elif "geometry" in columns:
        return "geoparquet"
    else:
        # Default to geoparquet for other parquet files
        return "geoparquet"


def extract_parquet_metadata(parquet_path: str) -> dict:
    """
    Extract metadata from a parquet file, auto-detecting type (Raquet or GeoParquet).

    Returns:
        Dict with file type, metadata info, and stac info
    """
    file_type = detect_parquet_type(parquet_path)

    if file_type == "raquet":
        meta = extract_raquet_metadata(parquet_path)
        return {
            "type": "raquet",
            "format_name": "Raquet",
            "spatial_representation": "grid",
            **meta,
        }
    else:
        meta = extract_geoparquet_metadata(parquet_path)
        return {
            "type": "geoparquet",
            "format_name": "GeoParquet",
            "spatial_representation": meta.get("spatial_representation", "vector"),
            "geoparquet_info": meta.get("geoparquet_info", {}),
            "stac_info": meta.get("stac_info", {}),
            "bounds": meta.get("bounds", []),
        }


def generate_sdi_catalog(
    collections: list[dict],
    output_dir: str,
    data_base_url: str,
    prefix: str = "catalog",
    verbose: bool = False,
) -> dict[str, str]:
    """
    Generate a complete SDI catalog with multiple collections/namespaces.

    Each collection becomes an Iceberg namespace containing:
    - An 'items' table with STAC+ISO metadata
    - Individual tables for each raquet asset

    Args:
        collections: List of collection definitions:
            [
                {
                    "name": "imagery",
                    "title": "Satellite Imagery",
                    "items": [
                        {
                            "id": "europe_rgb",
                            "title": "Europe RGB",
                            "asset_path": "/path/to/file.parquet",
                            "stac_info": {...},
                            "iso_info": {...},
                        }
                    ]
                }
            ]
        output_dir: Directory to write catalog files
        data_base_url: Base URL where data will be served
        prefix: Catalog prefix (default: "catalog")
        verbose: Print progress

    Returns:
        Dict mapping URL paths to created files
    """
    output_path = Path(output_dir)
    all_files = {}

    # Collect all namespaces
    all_namespaces = [c["name"] for c in collections]

    # Create base catalog structure
    v1_dir = output_path / "v1"
    catalog_dir = v1_dir / prefix
    ns_dir = catalog_dir / "namespaces"
    ns_dir.mkdir(parents=True, exist_ok=True)

    # Write /v1/config
    config_data = create_catalog_config(prefix)
    config_path = v1_dir / "config"
    with open(config_path, "w") as f:
        json.dump(config_data, f, indent=2)
    all_files["/v1/config"] = str(config_path)

    # Write /v1/{prefix}/namespaces with all collections
    namespaces_data = create_namespaces_list(all_namespaces)
    namespaces_path = ns_dir / "__list__"
    with open(namespaces_path, "w") as f:
        json.dump(namespaces_data, f, indent=2)
    all_files[f"/v1/{prefix}/namespaces"] = str(namespaces_path)

    # Process each collection
    for collection in collections:
        coll_name = collection["name"]
        coll_title = collection.get("title", coll_name)
        items_config = collection.get("items", [])

        if verbose:
            print(f"Processing collection: {coll_name}")

        # Create namespace directory
        coll_ns_dir = ns_dir / coll_name
        tables_dir = coll_ns_dir / "tables"
        tables_dir.mkdir(parents=True, exist_ok=True)

        # Write namespace detail
        ns_detail = create_namespace_detail(coll_name, {"title": coll_title})
        ns_detail_path = coll_ns_dir / "__detail__"
        with open(ns_detail_path, "w") as f:
            json.dump(ns_detail, f, indent=2)
        all_files[f"/v1/{prefix}/namespaces/{coll_name}"] = str(ns_detail_path)

        # Process items and create metadata records
        metadata_records = []
        raquet_tables = []

        for item in items_config:
            item_id = item["id"]
            item_title = item["title"]
            asset_path = item.get("asset_path")

            if verbose:
                print(f"  Processing item: {item_id}")

            # Extract metadata if asset exists (auto-detects Raquet vs GeoParquet)
            raquet_meta = {}
            stac_from_file = {}
            file_type = "unknown"
            if asset_path and Path(asset_path).exists():
                extracted = extract_parquet_metadata(asset_path)
                file_type = extracted.get("type", "geoparquet")
                raquet_meta = extracted.get("raquet_info", {})
                stac_from_file = extracted.get("stac_info", {})

                # Copy raquet file to output
                asset_name = item_id.lower().replace(" ", "_").replace("-", "_")
                asset_dir = output_path / "data" / coll_name / asset_name
                asset_dir.mkdir(parents=True, exist_ok=True)
                dest_path = asset_dir / f"{asset_name}.parquet"
                shutil.copy(asset_path, dest_path)

                # Add field IDs and create table
                add_iceberg_field_ids(dest_path)
                raquet_table = parquet_to_iceberg_table(str(dest_path), table_name=asset_name)
                raquet_tables.append(raquet_table)

                # Update asset URL in STAC info
                asset_url = f"{data_base_url.rstrip('/')}/data/{coll_name}/{asset_name}/{asset_name}.parquet"
                stac_info = item.get("stac_info", {})
                stac_info.setdefault("assets", {})
                stac_info["assets"]["data"] = {
                    "href": asset_url,
                    "type": "application/x-parquet",
                    "title": item_title,
                }
                # Merge bbox from file if not provided
                if not stac_info.get("bbox") and stac_from_file.get("bbox"):
                    stac_info["bbox"] = stac_from_file["bbox"]

                item["stac_info"] = stac_info

            # Merge raquet info
            item_raquet = {**raquet_meta, **item.get("raquet_info", {})}

            # Create metadata record
            record = create_stac_iso_record(
                item_id=item_id,
                title=item_title,
                stac_info=item.get("stac_info"),
                iso_info=item.get("iso_info"),
                raquet_info=item_raquet if item_raquet else None,
            )
            metadata_records.append(record)

        # Create items table from metadata records
        if metadata_records:
            items_table = create_items_table(metadata_records, output_dir, coll_name)
            all_tables = [items_table] + raquet_tables
        else:
            all_tables = raquet_tables

        # Write tables list
        table_names = [t.name for t in all_tables]
        tables_list = create_tables_list(table_names, coll_name)
        tables_list_path = coll_ns_dir / "tables__list__"
        with open(tables_list_path, "w") as f:
            json.dump(tables_list, f, indent=2)
        all_files[f"/v1/{prefix}/namespaces/{coll_name}/tables"] = str(tables_list_path)

        # Write each table's metadata
        for table in all_tables:
            table_uuid = str(uuid.uuid4())
            # Include collection name in table path
            full_table_path = f"{coll_name}/{table.name}"
            metadata = create_table_metadata(table, data_base_url, table_uuid, table_path=full_table_path)
            metadata_location = f"{data_base_url.rstrip('/')}/data/{coll_name}/{table.name}/metadata/v1.metadata.json"
            load_response = create_load_table_response(table, metadata, metadata_location)

            # Write table endpoint
            table_endpoint_path = tables_dir / table.name
            with open(table_endpoint_path, "w") as f:
                json.dump(load_response, f, indent=2)
            all_files[f"/v1/{prefix}/namespaces/{coll_name}/tables/{table.name}"] = str(table_endpoint_path)

            # Write standalone metadata
            table_meta_dir = output_path / "data" / coll_name / table.name / "metadata"
            table_meta_dir.mkdir(parents=True, exist_ok=True)
            meta_file = table_meta_dir / "v1.metadata.json"
            with open(meta_file, "w") as f:
                json.dump(metadata, f, indent=2)

            # Generate manifest files
            generate_manifest_files(table, data_base_url, table_meta_dir, table.arrow_schema, table_path=full_table_path)

            if verbose:
                print(f"  Created table: {table.name}")

    print(f"Generated SDI catalog with {len(collections)} collections")
    return all_files
