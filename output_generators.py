"""
Output generators for compatibility layers.

This module generates static catalog files in various formats:
- STAC (SpatioTemporal Asset Catalog)
- ISO 19139 (XML metadata)
- OGC API Records (future)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from portolan import CatalogConfig


def _normalize_resource(resource: dict) -> dict:
    """Normalize a resource dict to the common format expected by output generators.

    Handles both old format (flat dict with 'type', 'format', 'spatial_extent')
    and new format (Resource dataclass with 'origin', 'metadata', 'assets').
    """
    # Detect new format by checking if origin is a dict (old format has origin as string)
    if isinstance(resource.get("origin"), dict):
        # New Resource format
        metadata = resource.get("metadata", {})
        user_meta = metadata.get("user", {})
        derived = metadata.get("derived", {})

        # Build spatial_extent from bbox
        spatial_extent = None
        bbox = derived.get("bbox")
        if bbox and len(bbox) >= 4:
            spatial_extent = {
                "west": bbox[0],
                "south": bbox[1],
                "east": bbox[2],
                "north": bbox[3],
            }

        # Build assets dict for output generators
        assets = {}
        resource_assets = resource.get("assets", {})
        snapshot = resource_assets.get("snapshot")
        if isinstance(snapshot, dict) and snapshot.get("href"):
            assets["data"] = {
                "href": snapshot["href"],
                "type": snapshot.get("type", "application/vnd.apache.parquet"),
                "title": "Snapshot data",
            }
        iceberg = resource_assets.get("iceberg")
        if isinstance(iceberg, dict) and iceberg.get("metadata"):
            assets["iceberg"] = {
                "href": iceberg["metadata"],
                "type": "application/json",
                "title": "Iceberg metadata",
            }

        user_properties = user_meta.get("properties", {})

        return {
            "name": resource.get("name", "unknown"),
            "title": user_meta.get("title", resource.get("name", "unknown")),
            "abstract": user_meta.get("description", ""),
            "type": resource.get("kind", "vector"),
            "format": resource.get("kind", "unknown"),
            "spatial_extent": spatial_extent,
            "crs": derived.get("crs"),
            "temporal_extent": None,
            "created_at": resource.get("created_at"),
            "updated_at": resource.get("updated_at"),
            "assets": assets,
            "properties": {
                "row_count": derived.get("row_count"),
                "column_count": derived.get("column_count"),
            },
            "tags": user_meta.get("tags", []),
            "license": user_meta.get("license"),
            "attribution": user_meta.get("attribution"),
            "user_properties": user_properties,
        }

    # Old format - pass through unchanged
    return resource


# =============================================================================
# STAC Generator
# =============================================================================

def generate_stac_catalog(catalog: CatalogConfig, verbose: bool = False) -> dict[str, Path]:
    """
    Generate a static STAC catalog from Portolan resources.

    Creates:
    - catalog.json (root catalog)
    - collections/{namespace}/collection.json (per namespace)
    - collections/{namespace}/items/{id}.json (per resource)

    Args:
        catalog: CatalogConfig with path to .portolan directory
        verbose: Print progress

    Returns:
        Dict mapping STAC paths to created files
    """
    stac_dir = catalog.stac_dir
    stac_dir.mkdir(parents=True, exist_ok=True)

    resources_dir = catalog.path / "resources"
    if not resources_dir.exists():
        if verbose:
            print("No resources found, skipping STAC generation")
        return {}

    files_created = {}

    # Collect all namespaces and their resources
    namespaces = {}
    for namespace_dir in resources_dir.iterdir():
        if not namespace_dir.is_dir():
            continue

        namespace = namespace_dir.name
        namespaces[namespace] = []

        for resource_file in namespace_dir.glob("*.json"):
            if resource_file.name.startswith("_"):
                continue

            try:
                with open(resource_file) as f:
                    resource = json.load(f)
                namespaces[namespace].append(_normalize_resource(resource))
            except Exception as e:
                if verbose:
                    print(f"  Error reading {resource_file}: {e}")

    if not namespaces:
        if verbose:
            print("No resources found in any namespace")
        return {}

    from namespace_utils import namespace_parts

    # Build a tree of namespace parts to determine hierarchy
    # Each dotted namespace becomes a nested path: europe.spain.madrid → europe/spain/madrid
    # Intermediate nodes are STAC Catalogs, leaf nodes with resources are STAC Collections

    # Determine top-level children for root catalog
    top_level_parts = sorted({namespace_parts(ns)[0] for ns in namespaces})

    # Create root catalog
    root_catalog = {
        "type": "Catalog",
        "stac_version": "1.0.0",
        "id": "portolan-catalog",
        "title": "Portolan Catalog",
        "description": "Geospatial data catalog generated by Portolan",
        "links": [
            {"rel": "self", "href": "./catalog.json", "type": "application/json"},
            {"rel": "root", "href": "./catalog.json", "type": "application/json"},
        ]
    }

    for top in top_level_parts:
        # Check if this top-level is a leaf namespace (has resources directly)
        if top in namespaces:
            root_catalog["links"].append({
                "rel": "child",
                "href": f"./collections/{top}/collection.json",
                "type": "application/json",
                "title": top.replace("_", " ").title(),
            })
        else:
            root_catalog["links"].append({
                "rel": "child",
                "href": f"./collections/{top}/catalog.json",
                "type": "application/json",
                "title": top.replace("_", " ").title(),
            })

    # Write root catalog
    catalog_path = stac_dir / "catalog.json"
    with open(catalog_path, "w") as f:
        json.dump(root_catalog, f, indent=2)
    files_created["catalog.json"] = catalog_path

    if verbose:
        print(f"Created STAC catalog: {catalog_path}")

    # Create intermediate catalogs and leaf collections
    # First, collect all intermediate paths that need catalog.json files
    intermediate_paths: set[tuple[str, ...]] = set()
    for ns in namespaces:
        parts = namespace_parts(ns)
        # All prefixes except the full namespace are intermediate
        for i in range(1, len(parts)):
            prefix = tuple(parts[:i])
            # Only add as intermediate if this prefix isn't itself a leaf namespace
            if ".".join(prefix) not in namespaces:
                intermediate_paths.add(prefix)

    # Write intermediate catalog files
    for parts_tuple in sorted(intermediate_paths):
        inter_dir = stac_dir / "collections" / "/".join(parts_tuple)
        inter_dir.mkdir(parents=True, exist_ok=True)

        depth = len(parts_tuple)
        root_rel = "../" * (depth + 1) + "catalog.json"
        parent_rel = "../catalog.json" if depth > 1 else "../../catalog.json"

        inter_catalog = {
            "type": "Catalog",
            "stac_version": "1.0.0",
            "id": ".".join(parts_tuple),
            "title": parts_tuple[-1].replace("_", " ").title(),
            "description": f"Catalog for {'.'.join(parts_tuple)}",
            "links": [
                {"rel": "self", "href": "./catalog.json", "type": "application/json"},
                {"rel": "root", "href": root_rel, "type": "application/json"},
                {"rel": "parent", "href": parent_rel, "type": "application/json"},
            ],
        }

        # Find children of this intermediate node
        prefix_str = ".".join(parts_tuple) + "."
        child_names = set()
        for ns in namespaces:
            if ns.startswith(prefix_str):
                remainder = ns[len(prefix_str):]
                child_name = remainder.split(".")[0]
                child_names.add(child_name)

        for child_name in sorted(child_names):
            child_ns = f"{'.'.join(parts_tuple)}.{child_name}"
            if child_ns in namespaces:
                inter_catalog["links"].append({
                    "rel": "child",
                    "href": f"./{child_name}/collection.json",
                    "type": "application/json",
                    "title": child_name.replace("_", " ").title(),
                })
            else:
                inter_catalog["links"].append({
                    "rel": "child",
                    "href": f"./{child_name}/catalog.json",
                    "type": "application/json",
                    "title": child_name.replace("_", " ").title(),
                })

        inter_path = inter_dir / "catalog.json"
        with open(inter_path, "w") as f:
            json.dump(inter_catalog, f, indent=2)
        files_created[f"collections/{'/'.join(parts_tuple)}/catalog.json"] = inter_path

        if verbose:
            print(f"Created STAC intermediate catalog: {'.'.join(parts_tuple)}")

    # Create leaf collections and items
    for namespace, ns_resources in namespaces.items():
        parts = namespace_parts(namespace)
        collection_dir = stac_dir / "collections" / "/".join(parts)
        items_dir = collection_dir / "items"
        items_dir.mkdir(parents=True, exist_ok=True)

        depth = len(parts)
        root_rel = "../" * (depth + 1) + "catalog.json"
        parent_rel = "../catalog.json" if depth > 1 else "../../catalog.json"

        # Calculate collection extent from resources
        bbox = _calculate_collection_bbox(ns_resources)
        temporal = _calculate_collection_temporal(ns_resources)

        # Create collection
        collection = {
            "type": "Collection",
            "stac_version": "1.0.0",
            "id": namespace,
            "title": parts[-1].replace("_", " ").title(),
            "description": f"Collection of {len(ns_resources)} resources in {namespace}",
            "license": "various",
            "extent": {
                "spatial": {"bbox": [bbox] if bbox else [[]]},
                "temporal": {"interval": [[temporal["start"], temporal["end"]]] if temporal else [[None, None]]},
            },
            "links": [
                {"rel": "self", "href": "./collection.json", "type": "application/json"},
                {"rel": "root", "href": root_rel, "type": "application/json"},
                {"rel": "parent", "href": parent_rel, "type": "application/json"},
            ],
        }

        # Add item links
        for resource in ns_resources:
            name = resource.get("name", "unknown")
            collection["links"].append({
                "rel": "item",
                "href": f"./items/{name}.json",
                "type": "application/geo+json",
                "title": resource.get("title", name),
            })

        # Write collection
        collection_path = collection_dir / "collection.json"
        with open(collection_path, "w") as f:
            json.dump(collection, f, indent=2)
        col_rel_path = "/".join(parts)
        files_created[f"collections/{col_rel_path}/collection.json"] = collection_path

        if verbose:
            print(f"Created STAC collection: {namespace} ({len(ns_resources)} items)")

        # Create items
        for resource in ns_resources:
            item = _resource_to_stac_item(resource, namespace, depth)
            item_path = items_dir / f"{resource.get('name', 'unknown')}.json"
            with open(item_path, "w") as f:
                json.dump(item, f, indent=2)
            files_created[f"collections/{col_rel_path}/items/{resource.get('name')}.json"] = item_path

    if verbose:
        print(f"Generated STAC catalog with {len(files_created)} files")

    return files_created


def _resource_to_stac_item(resource: dict, collection: str, depth: int = 1) -> dict:
    """Convert a Portolan resource to a STAC Item.

    Args:
        resource: Normalized resource dict
        collection: Collection ID (dotted namespace)
        depth: Namespace depth (number of segments), used for relative root link
    """
    name = resource.get("name", "unknown")
    spatial = resource.get("spatial_extent", {}) or {}

    # Build bbox
    bbox = None
    if all(k in spatial for k in ["west", "south", "east", "north"]):
        bbox = [spatial["west"], spatial["south"], spatial["east"], spatial["north"]]

    # Build geometry from bbox
    geometry = None
    if bbox:
        geometry = {
            "type": "Polygon",
            "coordinates": [[
                [bbox[0], bbox[1]],
                [bbox[2], bbox[1]],
                [bbox[2], bbox[3]],
                [bbox[0], bbox[3]],
                [bbox[0], bbox[1]],
            ]]
        }

    # Build properties
    properties = {
        "title": resource.get("title", name),
        "description": resource.get("abstract", ""),
        "datetime": resource.get("created_at") or datetime.now(timezone.utc).isoformat(),
        "portolan:type": resource.get("type", "external"),
        "portolan:format": resource.get("format", "unknown"),
    }

    # Add license and keywords from user metadata
    if resource.get("license"):
        properties["license"] = resource["license"]
    if resource.get("tags"):
        properties["keywords"] = resource["tags"]

    # Map well-known user properties to STAC properties
    user_props = resource.get("user_properties", {})
    stac_field_map = {
        "start_datetime": "start_datetime",
        "end_datetime": "end_datetime",
    }
    for src_key, stac_key in stac_field_map.items():
        if user_props.get(src_key):
            properties[stac_key] = user_props[src_key]

    # Pass through remaining user properties as portolan: extension
    skip_keys = set(stac_field_map.keys())
    for k, v in user_props.items():
        if k not in skip_keys:
            properties[f"portolan:{k}"] = v

    # Add temporal if available (from old format)
    temporal = resource.get("temporal_extent", {}) or {}
    if temporal.get("start") and "start_datetime" not in properties:
        properties["start_datetime"] = temporal["start"]
    if temporal.get("end") and "end_datetime" not in properties:
        properties["end_datetime"] = temporal["end"]

    # Build assets
    assets = {}
    resource_assets = resource.get("assets", {})
    for asset_key, asset_info in resource_assets.items():
        if isinstance(asset_info, dict):
            assets[asset_key] = {
                "href": asset_info.get("href", ""),
                "type": asset_info.get("type", "application/octet-stream"),
                "title": asset_info.get("title", asset_key),
            }

    # items/ is one level below collection, then depth levels to collections/, then root
    root_rel = "../" * (depth + 2) + "catalog.json"

    item = {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": name,
        "geometry": geometry,
        "bbox": bbox,
        "properties": properties,
        "assets": assets,
        "collection": collection,
        "links": [
            {"rel": "self", "href": f"./{name}.json", "type": "application/geo+json"},
            {"rel": "collection", "href": "../collection.json", "type": "application/json"},
            {"rel": "root", "href": root_rel, "type": "application/json"},
        ],
    }

    return item


def _calculate_collection_bbox(resources: list[dict]) -> list | None:
    """Calculate bounding box that covers all resources."""
    west, south, east, north = float('inf'), float('inf'), float('-inf'), float('-inf')
    has_bbox = False

    for r in resources:
        spatial = r.get("spatial_extent", {}) or {}
        if all(k in spatial for k in ["west", "south", "east", "north"]):
            west = min(west, spatial["west"])
            south = min(south, spatial["south"])
            east = max(east, spatial["east"])
            north = max(north, spatial["north"])
            has_bbox = True

    return [west, south, east, north] if has_bbox else None


def _calculate_collection_temporal(resources: list[dict]) -> dict | None:
    """Calculate temporal extent that covers all resources."""
    start_dates = []
    end_dates = []

    for r in resources:
        temporal = r.get("temporal_extent", {}) or {}
        if temporal.get("start"):
            start_dates.append(temporal["start"])
        if temporal.get("end"):
            end_dates.append(temporal["end"])

    if start_dates or end_dates:
        return {
            "start": min(start_dates) if start_dates else None,
            "end": max(end_dates) if end_dates else None,
        }
    return None


def update_stac_for_resource(catalog: CatalogConfig, resource: dict, namespace: str, verbose: bool = False):
    """
    Update STAC catalog with a single resource (incremental update).

    This is called when a new resource is added, avoiding full regeneration.
    For dotted namespaces, this triggers a full regeneration to ensure the
    intermediate catalog hierarchy is correctly built.
    """
    stac_dir = catalog.stac_dir

    # Check if root catalog exists, create if not
    catalog_path = stac_dir / "catalog.json"
    if not catalog_path.exists() or "." in namespace:
        # Full generation needed for nested namespaces or first-time setup
        generate_stac_catalog(catalog, verbose=verbose)
        return

    resource = _normalize_resource(resource)

    # Simple (flat) namespace — incremental update
    collection_dir = stac_dir / "collections" / namespace
    items_dir = collection_dir / "items"
    items_dir.mkdir(parents=True, exist_ok=True)

    # Update/create item
    item = _resource_to_stac_item(resource, namespace)
    item_path = items_dir / f"{resource.get('name', 'unknown')}.json"
    with open(item_path, "w") as f:
        json.dump(item, f, indent=2)

    if verbose:
        print(f"Updated STAC item: {item_path}")

    # Update collection to include new item
    collection_path = collection_dir / "collection.json"
    if collection_path.exists():
        with open(collection_path) as f:
            collection = json.load(f)

        # Add item link if not already present
        item_href = f"./items/{resource.get('name')}.json"
        existing_hrefs = [link.get("href") for link in collection.get("links", [])]
        if item_href not in existing_hrefs:
            collection["links"].append({
                "rel": "item",
                "href": item_href,
                "type": "application/geo+json",
                "title": resource.get("title", resource.get("name")),
            })
            with open(collection_path, "w") as f:
                json.dump(collection, f, indent=2)
    else:
        # Need to create collection - do full regeneration
        generate_stac_catalog(catalog, verbose=verbose)
        return

    # Update root catalog to include collection if new
    with open(catalog_path) as f:
        root = json.load(f)

    collection_href = f"./collections/{namespace}/collection.json"
    existing_hrefs = [link.get("href") for link in root.get("links", [])]
    if collection_href not in existing_hrefs:
        root["links"].append({
            "rel": "child",
            "href": collection_href,
            "type": "application/json",
            "title": namespace.replace("_", " ").title(),
        })
        with open(catalog_path, "w") as f:
            json.dump(root, f, indent=2)


# =============================================================================
# ISO 19139 Generator
# =============================================================================


def generate_iso19139_catalog(catalog: CatalogConfig, verbose: bool = False) -> dict[str, Path]:
    """
    Generate ISO 19139 XML metadata files from Portolan resources.

    Creates one XML file per resource following ISO 19115/19139 schema.

    Args:
        catalog: CatalogConfig with path to .portolan directory
        verbose: Print progress

    Returns:
        Dict mapping paths to created files
    """
    iso_dir = catalog.iso_dir
    iso_dir.mkdir(parents=True, exist_ok=True)

    resources_dir = catalog.path / "resources"
    if not resources_dir.exists():
        if verbose:
            print("No resources found, skipping ISO 19139 generation")
        return {}

    files_created = {}

    from namespace_utils import namespace_parts as ns_parts

    for namespace_dir in resources_dir.iterdir():
        if not namespace_dir.is_dir():
            continue

        namespace = namespace_dir.name
        # Split dotted namespace into nested directory path
        parts = ns_parts(namespace)
        ns_dir = iso_dir
        for part in parts:
            ns_dir = ns_dir / part
        ns_dir.mkdir(parents=True, exist_ok=True)

        for resource_file in namespace_dir.glob("*.json"):
            if resource_file.name.startswith("_"):
                continue

            try:
                with open(resource_file) as f:
                    resource = _normalize_resource(json.load(f))

                xml_content = _resource_to_iso19139(resource)
                xml_path = ns_dir / f"{resource.get('name', 'unknown')}.xml"

                with open(xml_path, "w", encoding="utf-8") as f:
                    f.write(xml_content)

                rel_path = "/".join(parts) + f"/{resource.get('name')}.xml"
                files_created[rel_path] = xml_path

                if verbose:
                    print(f"Created ISO 19139: {xml_path}")

            except Exception as e:
                if verbose:
                    print(f"  Error processing {resource_file}: {e}")

    if verbose:
        print(f"Generated {len(files_created)} ISO 19139 metadata files")

    return files_created


def _resource_to_iso19139(resource: dict) -> str:
    """Convert a Portolan resource to ISO 19139 XML."""
    name = resource.get("name", "unknown")
    title = resource.get("title", name)
    abstract = resource.get("abstract", "")
    spatial = resource.get("spatial_extent", {}) or {}
    user_props = resource.get("user_properties", {})

    # Extract ISO-relevant fields from user properties
    contact_org = user_props.get("contact_organization", "")
    contact_email = user_props.get("contact_email", "")
    contact_role = user_props.get("contact_role", "pointOfContact")
    topic_category = user_props.get("topic_category", "geoscientificInformation")
    keywords = resource.get("tags", [])
    license_text = resource.get("license", "")
    use_constraints = user_props.get("use_constraints", "")
    lineage = user_props.get("lineage", "")

    # Build optional XML blocks
    contact_xml = ""
    if contact_org or contact_email:
        contact_xml = f'''
    <gmd:contact>
        <gmd:CI_ResponsibleParty>
            <gmd:organisationName>
                <gco:CharacterString>{_xml_escape(contact_org)}</gco:CharacterString>
            </gmd:organisationName>
            <gmd:contactInfo>
                <gmd:CI_Contact>
                    <gmd:address>
                        <gmd:CI_Address>
                            <gmd:electronicMailAddress>
                                <gco:CharacterString>{_xml_escape(contact_email)}</gco:CharacterString>
                            </gmd:electronicMailAddress>
                        </gmd:CI_Address>
                    </gmd:address>
                </gmd:CI_Contact>
            </gmd:contactInfo>
            <gmd:role>
                <gmd:CI_RoleCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#CI_RoleCode" codeListValue="{_xml_escape(contact_role)}">{_xml_escape(contact_role)}</gmd:CI_RoleCode>
            </gmd:role>
        </gmd:CI_ResponsibleParty>
    </gmd:contact>'''

    keywords_xml = ""
    if keywords:
        kw_items = "\n".join(
            f'                    <gmd:keyword><gco:CharacterString>{_xml_escape(kw)}</gco:CharacterString></gmd:keyword>'
            for kw in keywords
        )
        keywords_xml = f'''
            <gmd:descriptiveKeywords>
                <gmd:MD_Keywords>
{kw_items}
                </gmd:MD_Keywords>
            </gmd:descriptiveKeywords>'''

    constraints_xml = ""
    if license_text or use_constraints:
        parts = []
        if license_text:
            parts.append(f'                    <gmd:useLimitation><gco:CharacterString>{_xml_escape(license_text)}</gco:CharacterString></gmd:useLimitation>')
        if use_constraints:
            parts.append(f'                    <gmd:useConstraints><gmd:MD_RestrictionCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_RestrictionCode" codeListValue="otherRestrictions">{_xml_escape(use_constraints)}</gmd:MD_RestrictionCode></gmd:useConstraints>')
        constraints_xml = f'''
            <gmd:resourceConstraints>
                <gmd:MD_LegalConstraints>
{chr(10).join(parts)}
                </gmd:MD_LegalConstraints>
            </gmd:resourceConstraints>'''

    lineage_xml = ""
    if lineage:
        lineage_xml = f'''
    <gmd:dataQualityInfo>
        <gmd:DQ_DataQuality>
            <gmd:scope>
                <gmd:DQ_Scope>
                    <gmd:level>
                        <gmd:MD_ScopeCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_ScopeCode" codeListValue="dataset">dataset</gmd:MD_ScopeCode>
                    </gmd:level>
                </gmd:DQ_Scope>
            </gmd:scope>
            <gmd:lineage>
                <gmd:LI_Lineage>
                    <gmd:statement>
                        <gco:CharacterString>{_xml_escape(lineage)}</gco:CharacterString>
                    </gmd:statement>
                </gmd:LI_Lineage>
            </gmd:lineage>
        </gmd:DQ_DataQuality>
    </gmd:dataQualityInfo>'''

    # Build XML using string templates (avoiding complex XML library dependencies)
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<gmd:MD_Metadata
    xmlns:gmd="http://www.isotc211.org/2005/gmd"
    xmlns:gco="http://www.isotc211.org/2005/gco"
    xmlns:gml="http://www.opengis.net/gml/3.2"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.isotc211.org/2005/gmd http://schemas.opengis.net/iso/19139/20070417/gmd/gmd.xsd">

    <!-- File Identifier -->
    <gmd:fileIdentifier>
        <gco:CharacterString>{name}</gco:CharacterString>
    </gmd:fileIdentifier>

    <!-- Language -->
    <gmd:language>
        <gmd:LanguageCode codeList="http://www.loc.gov/standards/iso639-2/" codeListValue="eng">English</gmd:LanguageCode>
    </gmd:language>

    <!-- Hierarchy Level -->
    <gmd:hierarchyLevel>
        <gmd:MD_ScopeCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_ScopeCode" codeListValue="dataset">dataset</gmd:MD_ScopeCode>
    </gmd:hierarchyLevel>
{contact_xml}
    <!-- Date Stamp -->
    <gmd:dateStamp>
        <gco:DateTime>{datetime.now(timezone.utc).isoformat()}</gco:DateTime>
    </gmd:dateStamp>

    <!-- Metadata Standard -->
    <gmd:metadataStandardName>
        <gco:CharacterString>ISO 19115:2003/19139</gco:CharacterString>
    </gmd:metadataStandardName>
    <gmd:metadataStandardVersion>
        <gco:CharacterString>1.0</gco:CharacterString>
    </gmd:metadataStandardVersion>

    <!-- Identification Info -->
    <gmd:identificationInfo>
        <gmd:MD_DataIdentification>
            <gmd:citation>
                <gmd:CI_Citation>
                    <gmd:title>
                        <gco:CharacterString>{_xml_escape(title)}</gco:CharacterString>
                    </gmd:title>
                    <gmd:date>
                        <gmd:CI_Date>
                            <gmd:date>
                                <gco:DateTime>{resource.get("created_at", datetime.now(timezone.utc).isoformat())}</gco:DateTime>
                            </gmd:date>
                            <gmd:dateType>
                                <gmd:CI_DateTypeCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#CI_DateTypeCode" codeListValue="creation">creation</gmd:CI_DateTypeCode>
                            </gmd:dateType>
                        </gmd:CI_Date>
                    </gmd:date>
                </gmd:CI_Citation>
            </gmd:citation>
            <gmd:abstract>
                <gco:CharacterString>{_xml_escape(abstract)}</gco:CharacterString>
            </gmd:abstract>
            <gmd:status>
                <gmd:MD_ProgressCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#MD_ProgressCode" codeListValue="completed">completed</gmd:MD_ProgressCode>
            </gmd:status>
{keywords_xml}{constraints_xml}
            <!-- Resource Format -->
            <gmd:resourceFormat>
                <gmd:MD_Format>
                    <gmd:name>
                        <gco:CharacterString>{resource.get("format", "unknown")}</gco:CharacterString>
                    </gmd:name>
                    <gmd:version>
                        <gco:CharacterString>1.0</gco:CharacterString>
                    </gmd:version>
                </gmd:MD_Format>
            </gmd:resourceFormat>

            <!-- Spatial Extent -->
            {_generate_bbox_xml(spatial)}

            <!-- Topic Category -->
            <gmd:topicCategory>
                <gmd:MD_TopicCategoryCode>{_xml_escape(topic_category)}</gmd:MD_TopicCategoryCode>
            </gmd:topicCategory>

        </gmd:MD_DataIdentification>
    </gmd:identificationInfo>

    <!-- Distribution Info -->
    <gmd:distributionInfo>
        <gmd:MD_Distribution>
            {_generate_distribution_xml(resource)}
        </gmd:MD_Distribution>
    </gmd:distributionInfo>
{lineage_xml}
</gmd:MD_Metadata>'''

    return xml


def _xml_escape(text: str) -> str:
    """Escape special XML characters."""
    if not text:
        return ""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))


def _generate_bbox_xml(spatial: dict) -> str:
    """Generate ISO 19139 bounding box XML."""
    if not all(k in spatial for k in ["west", "south", "east", "north"]):
        return ""

    return f'''<gmd:extent>
                <gmd:EX_Extent>
                    <gmd:geographicElement>
                        <gmd:EX_GeographicBoundingBox>
                            <gmd:westBoundLongitude>
                                <gco:Decimal>{spatial["west"]}</gco:Decimal>
                            </gmd:westBoundLongitude>
                            <gmd:eastBoundLongitude>
                                <gco:Decimal>{spatial["east"]}</gco:Decimal>
                            </gmd:eastBoundLongitude>
                            <gmd:southBoundLatitude>
                                <gco:Decimal>{spatial["south"]}</gco:Decimal>
                            </gmd:southBoundLatitude>
                            <gmd:northBoundLatitude>
                                <gco:Decimal>{spatial["north"]}</gco:Decimal>
                            </gmd:northBoundLatitude>
                        </gmd:EX_GeographicBoundingBox>
                    </gmd:geographicElement>
                </gmd:EX_Extent>
            </gmd:extent>'''


def _generate_distribution_xml(resource: dict) -> str:
    """Generate ISO 19139 distribution info XML."""
    assets = resource.get("assets", {})

    if not assets:
        return ""

    transfers = []
    for asset_key, asset_info in assets.items():
        if isinstance(asset_info, dict) and asset_info.get("href"):
            transfers.append(f'''<gmd:transferOptions>
                <gmd:MD_DigitalTransferOptions>
                    <gmd:onLine>
                        <gmd:CI_OnlineResource>
                            <gmd:linkage>
                                <gmd:URL>{_xml_escape(asset_info["href"])}</gmd:URL>
                            </gmd:linkage>
                            <gmd:name>
                                <gco:CharacterString>{_xml_escape(asset_info.get("title", asset_key))}</gco:CharacterString>
                            </gmd:name>
                            <gmd:function>
                                <gmd:CI_OnLineFunctionCode codeList="http://standards.iso.org/iso/19139/resources/gmxCodelists.xml#CI_OnLineFunctionCode" codeListValue="download">download</gmd:CI_OnLineFunctionCode>
                            </gmd:function>
                        </gmd:CI_OnlineResource>
                    </gmd:onLine>
                </gmd:MD_DigitalTransferOptions>
            </gmd:transferOptions>''')

    return "\n".join(transfers)


def update_iso19139_for_resource(catalog: CatalogConfig, resource: dict, namespace: str, verbose: bool = False):
    """
    Update ISO 19139 catalog with a single resource (incremental update).
    """
    from namespace_utils import namespace_parts

    resource = _normalize_resource(resource)
    iso_dir = catalog.iso_dir
    # Split dotted namespace into nested directory path
    ns_dir = iso_dir
    for part in namespace_parts(namespace):
        ns_dir = ns_dir / part
    ns_dir.mkdir(parents=True, exist_ok=True)

    xml_content = _resource_to_iso19139(resource)
    xml_path = ns_dir / f"{resource.get('name', 'unknown')}.xml"

    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(xml_content)

    if verbose:
        print(f"Updated ISO 19139: {xml_path}")


# =============================================================================
# DuckLake Generator
# =============================================================================

def generate_ducklake_catalog(catalog: CatalogConfig, verbose: bool = False) -> Path | None:
    """
    Generate a DuckLake catalog from Portolan resources.

    Creates a .ducklake file that can be attached to DuckDB for querying.
    The DuckLake catalog references the parquet files in the data directory.

    Usage in DuckDB:
        INSTALL ducklake;
        ATTACH 'ducklake:catalog.ducklake' AS catalog (DATA_PATH 'data/');
        SELECT * FROM catalog.main.table_name;

    Args:
        catalog: CatalogConfig with path to .portolan directory
        verbose: Print progress

    Returns:
        Path to created .ducklake file, or None if DuckDB not available
    """
    try:
        import duckdb
    except ImportError:
        if verbose:
            print("DuckDB not installed, skipping DuckLake generation")
            print("Install with: pip install duckdb")
        return None

    ducklake_path = catalog.path / "catalog.ducklake"
    data_dir = catalog.data_dir

    # Check if data directory has parquet files
    parquet_files = list(data_dir.rglob("*.parquet")) if data_dir.exists() else []
    if not parquet_files:
        if verbose:
            print("No parquet files found in data directory, skipping DuckLake generation")
        return None

    if verbose:
        print(f"Generating DuckLake catalog with {len(parquet_files)} tables...")

    # Remove existing catalog to start fresh
    if ducklake_path.exists():
        ducklake_path.unlink()

    # Create DuckLake catalog
    try:
        conn = duckdb.connect()

        # Install and load DuckLake extension
        conn.execute("INSTALL ducklake")
        conn.execute("LOAD ducklake")

        # Attach as DuckLake catalog with data path
        # Use absolute path for data directory
        data_path = str(data_dir.absolute())
        ducklake_file = str(ducklake_path.absolute())

        conn.execute(f"""
            ATTACH 'ducklake:{ducklake_file}' AS portolan (DATA_PATH '{data_path}/')
        """)

        # Create tables for each parquet file
        tables_created = 0
        for parquet_file in parquet_files:
            table_name = parquet_file.stem
            # Sanitize table name
            table_name = table_name.replace("-", "_").replace(" ", "_")

            try:
                # Create table from parquet file
                conn.execute(f"""
                    CREATE TABLE portolan.main.{table_name} AS
                    SELECT * FROM read_parquet('{parquet_file.absolute()}')
                """)
                tables_created += 1
                if verbose:
                    print(f"  Created table: {table_name}")
            except Exception as e:
                if verbose:
                    print(f"  Error creating table {table_name}: {e}")

        conn.close()

        if verbose:
            print(f"Created DuckLake catalog: {ducklake_path}")
            print(f"  Tables: {tables_created}")
            print()
            print("Connect with DuckDB:")
            print(f"  ATTACH 'ducklake:{ducklake_path}' AS catalog;")
            print("  SHOW ALL TABLES;")

        return ducklake_path

    except Exception as e:
        if verbose:
            print(f"Error creating DuckLake catalog: {e}")
        return None


def update_ducklake_for_resource(catalog: CatalogConfig, resource: dict, namespace: str, verbose: bool = False):
    """
    Update DuckLake catalog with a single resource.

    For DuckLake, we regenerate the entire catalog since it's a single file.
    """
    generate_ducklake_catalog(catalog, verbose=verbose)


# =============================================================================
# Web UI Generator
# =============================================================================

def generate_web_catalog(catalog: CatalogConfig, verbose: bool = False) -> dict[str, Path]:
    """
    Generate a static web UI for browsing the Portolan catalog.

    Creates an index.html that can browse resources, with links to data files
    and metadata in various formats.

    Args:
        catalog: CatalogConfig with path to .portolan directory
        verbose: Print progress

    Returns:
        Dict mapping paths to created files
    """
    web_dir = catalog.path / "web"
    web_dir.mkdir(parents=True, exist_ok=True)

    resources_dir = catalog.path / "resources"
    files_created = {}

    # Collect all resources
    all_resources = []
    namespaces = {}

    if resources_dir.exists():
        for namespace_dir in resources_dir.iterdir():
            if not namespace_dir.is_dir():
                continue

            namespace = namespace_dir.name
            namespaces[namespace] = []

            for resource_file in namespace_dir.glob("*.json"):
                if resource_file.name.startswith("_"):
                    continue

                try:
                    with open(resource_file) as f:
                        raw = json.load(f)
                    resource = _normalize_resource(raw)
                    resource["_namespace"] = namespace
                    resource["_kind"] = raw.get("kind", "vector")
                    # Derive state from raw assets
                    raw_assets = raw.get("assets", {})
                    if raw_assets.get("iceberg"):
                        resource["_state"] = "materialized"
                    elif raw_assets.get("snapshot"):
                        resource["_state"] = "cached"
                    else:
                        resource["_state"] = "external"
                    all_resources.append(resource)
                    namespaces[namespace].append(resource)
                except Exception as e:
                    if verbose:
                        print(f"  Error reading {resource_file}: {e}")

    # Generate index.html
    html_content = _generate_web_html(all_resources, namespaces, catalog)
    index_path = web_dir / "index.html"
    with open(index_path, "w") as f:
        f.write(html_content)
    files_created["index.html"] = index_path

    if verbose:
        print(f"Generated web UI: {index_path}")
        print(f"  Resources: {len(all_resources)}")
        print(f"  Namespaces: {len(namespaces)}")

    return files_created


def _generate_web_html(resources: list[dict], namespaces: dict, catalog: CatalogConfig) -> str:
    """Generate the HTML content for the web UI with hierarchical namespace tree."""
    from namespace_utils import build_namespace_tree

    # Build the namespace tree and attach resources at leaf nodes
    ns_tree = build_namespace_tree(list(namespaces.keys()))

    # Build tree HTML recursively
    def render_tree(tree: dict, resources_by_ns: dict, prefix: str = "", depth: int = 0) -> str:
        html_parts = []
        for folder_name in sorted(tree.keys()):
            children = tree[folder_name]
            full_ns = f"{prefix}.{folder_name}" if prefix else folder_name
            # Get resources at this exact namespace
            ns_resources = resources_by_ns.get(full_ns, [])
            has_children = bool(children)
            has_resources = bool(ns_resources)

            if not has_children and not has_resources:
                continue

            html_parts.append(f'<details class="ns-folder" open data-ns="{_html_escape(full_ns)}">')
            html_parts.append(f'<summary class="ns-header depth-{min(depth, 3)}">')
            html_parts.append(f'<span class="folder-icon"></span> {_html_escape(folder_name)}/')
            count = len(ns_resources)
            if has_children:
                # Count all descendant resources
                count = _count_descendants(full_ns, resources_by_ns)
            if count:
                html_parts.append(f' <span class="ns-count">{count}</span>')
            html_parts.append('</summary>')
            html_parts.append('<div class="ns-content">')

            # Render resources at this node
            for r in sorted(ns_resources, key=lambda x: x.get("name", "")):
                html_parts.append(_render_resource_row(r))

            # Recurse into children
            if has_children:
                html_parts.append(render_tree(children, resources_by_ns, full_ns, depth + 1))

            html_parts.append('</div></details>')

        return "\n".join(html_parts)

    # Build namespace→resources lookup
    resources_by_ns = {}
    for r in resources:
        ns = r.get("_namespace", "default")
        resources_by_ns.setdefault(ns, []).append(r)

    tree_html = render_tree(ns_tree, resources_by_ns)

    # Build namespace stats
    namespace_stats = []
    for ns, items in sorted(namespaces.items()):
        namespace_stats.append(f'<span class="badge">{ns}: {len(items)}</span>')
    stats_html = " ".join(namespace_stats)

    # Check which outputs are enabled
    outputs_enabled = []
    if catalog.outputs.get("stac"):
        outputs_enabled.append('<a href="../stac/catalog.json" class="output-link">STAC</a>')
    if catalog.outputs.get("iso19139"):
        outputs_enabled.append('<a href="../iso19139/" class="output-link">ISO 19139</a>')
    if catalog.outputs.get("ducklake"):
        outputs_enabled.append('<span class="output-link">DuckLake</span>')
    outputs_html = " | ".join(outputs_enabled) if outputs_enabled else "None"

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Portolan Catalog</title>
    <style>
        :root {{
            --primary: #2563eb;
            --bg: #f8fafc;
            --card: #ffffff;
            --text: #1e293b;
            --muted: #64748b;
            --border: #e2e8f0;
            --green: #16a34a;
            --amber: #d97706;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 2rem; }}
        header {{
            background: var(--primary);
            color: white;
            padding: 2rem;
            margin-bottom: 2rem;
        }}
        header h1 {{ font-size: 2rem; margin-bottom: 0.5rem; }}
        header p {{ opacity: 0.9; }}
        .stats {{
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1rem;
            margin-bottom: 1.5rem;
            display: flex;
            gap: 2rem;
            flex-wrap: wrap;
        }}
        .stat-label {{ font-size: 0.875rem; color: var(--muted); }}
        .stat-value {{ font-size: 1.25rem; font-weight: 600; }}
        .badge {{
            display: inline-block;
            background: var(--primary);
            color: white;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
        }}
        .search-box {{
            width: 100%;
            padding: 0.75rem 1rem;
            border: 1px solid var(--border);
            border-radius: 8px;
            font-size: 1rem;
            margin-bottom: 1rem;
        }}
        .search-box:focus {{ outline: none; border-color: var(--primary); }}
        .output-link {{ color: var(--primary); text-decoration: none; }}
        .output-link:hover {{ text-decoration: underline; }}

        /* Tree */
        .ns-tree {{
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1rem 1.5rem;
        }}
        .ns-folder {{ margin: 0; }}
        .ns-folder > .ns-content {{ padding-left: 1.25rem; }}
        .ns-header {{
            cursor: pointer;
            padding: 0.375rem 0.5rem;
            border-radius: 4px;
            font-weight: 600;
            font-size: 0.9375rem;
            list-style: none;
            display: flex;
            align-items: center;
            gap: 0.25rem;
        }}
        .ns-header::-webkit-details-marker {{ display: none; }}
        .ns-header:hover {{ background: var(--bg); }}
        .ns-header .folder-icon::before {{ content: "\\25BE"; font-size: 0.75rem; color: var(--muted); }}
        details:not([open]) > .ns-header .folder-icon::before {{ content: "\\25B8"; }}
        .ns-count {{
            background: var(--bg);
            color: var(--muted);
            font-size: 0.75rem;
            font-weight: 400;
            padding: 0.125rem 0.375rem;
            border-radius: 10px;
            margin-left: 0.25rem;
        }}

        /* Resource rows */
        .resource-row {{
            display: grid;
            grid-template-columns: auto 1fr auto;
            gap: 0.75rem;
            align-items: baseline;
            padding: 0.5rem 0.5rem 0.5rem 1.5rem;
            border-radius: 4px;
        }}
        .resource-row:hover {{ background: var(--bg); }}
        .resource-name {{
            font-weight: 500;
            white-space: nowrap;
        }}
        .resource-desc {{
            color: var(--muted);
            font-size: 0.875rem;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .resource-meta {{
            display: flex;
            gap: 0.375rem;
            align-items: center;
            white-space: nowrap;
        }}
        .kind-badge {{
            display: inline-block;
            padding: 0.125rem 0.375rem;
            border-radius: 3px;
            font-size: 0.6875rem;
            font-weight: 500;
            background: #e2e8f0;
            color: var(--text);
        }}
        .kind-badge.vector {{ background: #dbeafe; color: #1e40af; }}
        .kind-badge.raster {{ background: #fef3c7; color: #92400e; }}
        .kind-badge.collection {{ background: #f3e8ff; color: #6b21a8; }}
        .state-icon {{ font-size: 0.75rem; }}
        .state-icon.materialized {{ color: var(--green); }}
        .state-icon.cached {{ color: var(--amber); }}
        .state-icon.external {{ color: var(--muted); }}
        .asset-link {{
            display: inline-block;
            background: #e2e8f0;
            color: var(--text);
            padding: 0.125rem 0.375rem;
            border-radius: 3px;
            font-size: 0.6875rem;
            text-decoration: none;
        }}
        .asset-link:hover {{ background: #cbd5e1; }}

        footer {{
            margin-top: 2rem;
            padding: 1rem;
            text-align: center;
            color: var(--muted);
            font-size: 0.875rem;
        }}
    </style>
</head>
<body>
    <header>
        <div class="container">
            <h1>Portolan Catalog</h1>
            <p>Geospatial data infrastructure</p>
        </div>
    </header>

    <div class="container">
        <div class="stats">
            <div class="stat-item">
                <div class="stat-label">Resources</div>
                <div class="stat-value">{len(resources)}</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">Namespaces</div>
                <div class="stat-value">{len(namespaces)}</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">Collections</div>
                <div class="stat-value">{stats_html}</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">Outputs</div>
                <div class="stat-value">{outputs_html}</div>
            </div>
        </div>

        <input type="text" class="search-box" placeholder="Search resources..." id="search" oninput="filterTree()">

        <div class="ns-tree" id="ns-tree">
            {tree_html}
        </div>
    </div>

    <footer>
        Generated by <a href="https://github.com/portolan-sdi/portolan">Portolan</a> &bull;
        {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    </footer>

    <script>
        function filterTree() {{
            const query = document.getElementById('search').value.toLowerCase();
            const rows = document.querySelectorAll('.resource-row');
            const folders = document.querySelectorAll('.ns-folder');

            if (!query) {{
                rows.forEach(r => r.style.display = '');
                folders.forEach(f => {{ f.style.display = ''; f.open = true; }});
                return;
            }}

            // Hide all first
            rows.forEach(r => r.style.display = 'none');
            folders.forEach(f => f.style.display = 'none');

            // Show matching rows and their ancestor folders
            rows.forEach(row => {{
                const text = row.textContent.toLowerCase();
                if (text.includes(query)) {{
                    row.style.display = '';
                    let el = row.parentElement;
                    while (el) {{
                        if (el.classList && el.classList.contains('ns-folder')) {{
                            el.style.display = '';
                            el.open = true;
                        }}
                        el = el.parentElement;
                    }}
                }}
            }});

            // Also match folder names
            folders.forEach(f => {{
                const summary = f.querySelector(':scope > summary');
                if (summary && summary.textContent.toLowerCase().includes(query)) {{
                    f.style.display = '';
                    f.open = true;
                    f.querySelectorAll('.resource-row').forEach(r => r.style.display = '');
                    f.querySelectorAll('.ns-folder').forEach(sf => {{ sf.style.display = ''; sf.open = true; }});
                    let el = f.parentElement;
                    while (el) {{
                        if (el.classList && el.classList.contains('ns-folder')) {{
                            el.style.display = '';
                            el.open = true;
                        }}
                        el = el.parentElement;
                    }}
                }}
            }});
        }}
    </script>
</body>
</html>'''

    return html


def _count_descendants(prefix: str, resources_by_ns: dict) -> int:
    """Count all resources in a namespace and its descendants."""
    count = 0
    for ns, items in resources_by_ns.items():
        if ns == prefix or ns.startswith(prefix + "."):
            count += len(items)
    return count


def _render_resource_row(r: dict) -> str:
    """Render a single resource as an HTML row in the tree."""
    name = r.get("name", "unknown")
    title = r.get("title", name)
    kind = r.get("_kind", "vector")
    state = r.get("_state", "external")
    abstract = r.get("abstract", "")[:120]
    if len(r.get("abstract", "")) > 120:
        abstract += "..."

    # State indicator
    state_icons = {"materialized": "&#9679;", "cached": "&#9681;", "external": "&#9675;"}
    state_titles = {"materialized": "Materialized", "cached": "Cached", "external": "External"}
    state_icon = f'<span class="state-icon {state}" title="{state_titles.get(state, state)}">{state_icons.get(state, "&#9675;")}</span>'

    # Asset links
    asset_links = []
    for asset_key, asset_info in r.get("assets", {}).items():
        if isinstance(asset_info, dict) and asset_info.get("href"):
            href = asset_info["href"]
            asset_links.append(f'<a href="{href}" class="asset-link">{asset_key}</a>')
    assets_html = " ".join(asset_links)

    return f'''<div class="resource-row" data-name="{_html_escape(name)}">
        <div class="resource-name">{state_icon} {_html_escape(title)}<br><small style="color:var(--muted);font-weight:400">{_html_escape(name)}</small></div>
        <div class="resource-desc">{_html_escape(abstract)}</div>
        <div class="resource-meta"><span class="kind-badge {kind}">{kind}</span> {assets_html}</div>
    </div>'''


def _html_escape(text: str) -> str:
    """Escape special HTML characters."""
    if not text:
        return ""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def update_web_for_resource(catalog: CatalogConfig, resource: dict, namespace: str, verbose: bool = False):
    """
    Update web UI with a single resource.

    For web UI, we regenerate the entire index since it's a single file.
    """
    generate_web_catalog(catalog, verbose=verbose)


# =============================================================================
# Main Update Function
# =============================================================================

def update_all_outputs(catalog: CatalogConfig, resource: dict, namespace: str, verbose: bool = False):
    """
    Update all enabled output formats for a resource.

    Called when a new resource is added via `dataset add` or `import`.
    """
    outputs = catalog.outputs

    # Iceberg is always updated by the main code

    if outputs.get("stac"):
        update_stac_for_resource(catalog, resource, namespace, verbose=verbose)

    if outputs.get("iso19139"):
        update_iso19139_for_resource(catalog, resource, namespace, verbose=verbose)

    if outputs.get("ducklake"):
        update_ducklake_for_resource(catalog, resource, namespace, verbose=verbose)

    if outputs.get("web"):
        update_web_for_resource(catalog, resource, namespace, verbose=verbose)


def regenerate_all_outputs(catalog: CatalogConfig, verbose: bool = False):
    """
    Regenerate all enabled output formats from scratch.

    Called by `portolan rebuild`.
    """
    outputs = catalog.outputs

    if outputs.get("stac"):
        if verbose:
            print("Regenerating STAC catalog...")
        generate_stac_catalog(catalog, verbose=verbose)

    if outputs.get("iso19139"):
        if verbose:
            print("Regenerating ISO 19139 metadata...")
        generate_iso19139_catalog(catalog, verbose=verbose)

    if outputs.get("ducklake"):
        if verbose:
            print("Regenerating DuckLake catalog...")
        generate_ducklake_catalog(catalog, verbose=verbose)

    if outputs.get("web"):
        if verbose:
            print("Regenerating web UI...")
        generate_web_catalog(catalog, verbose=verbose)
