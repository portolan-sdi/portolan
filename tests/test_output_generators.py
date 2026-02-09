"""
Tests for output generators (STAC, ISO 19139, DuckLake, Web).
"""

import json
from pathlib import Path

import pytest

from output_generators import (
    generate_stac_catalog,
    generate_iso19139_catalog,
    generate_web_catalog,
    generate_ducklake_catalog,
    _normalize_resource,
    _resource_to_stac_item,
    _resource_to_iso19139,
    _calculate_collection_bbox,
    _xml_escape,
    _html_escape,
)


class TestSTACGenerator:
    """Test suite for STAC catalog generation."""

    def test_stac_empty_catalog(self, initialized_catalog):
        """Test STAC generation on empty catalog."""
        result = generate_stac_catalog(initialized_catalog, verbose=False)
        assert result == {}

    def test_stac_with_resources(self, catalog_with_resource):
        """Test STAC generation with resources."""
        result = generate_stac_catalog(catalog_with_resource, verbose=False)

        assert len(result) > 0
        assert "catalog.json" in result

        # Check catalog.json exists and is valid
        catalog_path = catalog_with_resource.stac_dir / "catalog.json"
        assert catalog_path.exists()

        with open(catalog_path) as f:
            catalog = json.load(f)

        assert catalog["type"] == "Catalog"
        assert catalog["stac_version"] == "1.0.0"
        assert "links" in catalog

    def test_stac_collection_created(self, catalog_with_resource):
        """Test that STAC collection is created."""
        generate_stac_catalog(catalog_with_resource, verbose=False)

        # Check collection exists
        collection_path = (
            catalog_with_resource.stac_dir / "collections" / "test" / "collection.json"
        )
        assert collection_path.exists()

        with open(collection_path) as f:
            collection = json.load(f)

        assert collection["type"] == "Collection"
        assert collection["id"] == "test"

    def test_stac_item_created(self, catalog_with_resource):
        """Test that STAC items are created."""
        generate_stac_catalog(catalog_with_resource, verbose=False)

        # Check item exists
        item_path = (
            catalog_with_resource.stac_dir
            / "collections"
            / "test"
            / "items"
            / "sample.json"
        )
        assert item_path.exists()

        with open(item_path) as f:
            item = json.load(f)

        assert item["type"] == "Feature"
        assert item["stac_version"] == "1.0.0"
        assert "geometry" in item
        assert "properties" in item


class TestResourceToSTACItem:
    """Test suite for resource to STAC item conversion."""

    def test_basic_conversion(self):
        """Test basic resource to STAC item conversion."""
        resource = {
            "name": "test_item",
            "title": "Test Item",
            "abstract": "A test item",
            "spatial_extent": {
                "west": -10.0,
                "south": 35.0,
                "east": 5.0,
                "north": 45.0,
            },
        }

        item = _resource_to_stac_item(resource, "test_collection")

        assert item["type"] == "Feature"
        assert item["id"] == "test_item"
        assert item["collection"] == "test_collection"
        assert item["bbox"] == [-10.0, 35.0, 5.0, 45.0]
        assert item["geometry"]["type"] == "Polygon"

    def test_conversion_without_spatial(self):
        """Test conversion without spatial extent."""
        resource = {"name": "no_spatial", "title": "No Spatial"}

        item = _resource_to_stac_item(resource, "collection")

        assert item["bbox"] is None
        assert item["geometry"] is None


class TestCalculateBbox:
    """Test suite for bbox calculation."""

    def test_single_resource(self):
        """Test bbox from single resource."""
        resources = [
            {"spatial_extent": {"west": 0, "south": 0, "east": 10, "north": 10}}
        ]
        bbox = _calculate_collection_bbox(resources)
        assert bbox == [0, 0, 10, 10]

    def test_multiple_resources(self):
        """Test bbox from multiple resources."""
        resources = [
            {"spatial_extent": {"west": 0, "south": 0, "east": 5, "north": 5}},
            {"spatial_extent": {"west": 5, "south": 5, "east": 10, "north": 10}},
        ]
        bbox = _calculate_collection_bbox(resources)
        assert bbox == [0, 0, 10, 10]

    def test_no_spatial_resources(self):
        """Test bbox when no resources have spatial extent."""
        resources = [{"name": "no_spatial"}]
        bbox = _calculate_collection_bbox(resources)
        assert bbox is None


class TestISO19139Generator:
    """Test suite for ISO 19139 generation."""

    def test_iso_empty_catalog(self, initialized_catalog):
        """Test ISO generation on empty catalog."""
        result = generate_iso19139_catalog(initialized_catalog, verbose=False)
        assert result == {}

    def test_iso_with_resources(self, catalog_with_resource):
        """Test ISO generation with resources."""
        result = generate_iso19139_catalog(catalog_with_resource, verbose=False)

        assert len(result) > 0

        # Check XML file exists
        xml_path = catalog_with_resource.iso_dir / "test" / "sample.xml"
        assert xml_path.exists()

        # Check it's valid XML
        content = xml_path.read_text()
        assert '<?xml version="1.0"' in content
        assert "gmd:MD_Metadata" in content

    def test_iso_contains_title(self, catalog_with_resource):
        """Test that ISO XML contains the title."""
        generate_iso19139_catalog(catalog_with_resource, verbose=False)

        xml_path = catalog_with_resource.iso_dir / "test" / "sample.xml"
        content = xml_path.read_text()

        assert "Sample Cities" in content


class TestRichMetadataInOutputs:
    """Test rich user metadata flows through to outputs."""

    def test_normalize_passes_through_user_properties(self):
        """_normalize_resource includes tags, license, and user_properties."""
        resource = {
            "name": "test",
            "kind": "vector",
            "origin": {"type": "file"},
            "assets": {},
            "metadata": {
                "user": {
                    "title": "Test",
                    "tags": ["boundaries", "admin"],
                    "license": "CC-BY-4.0",
                    "properties": {"contact_email": "test@example.com"},
                },
            },
        }
        normalized = _normalize_resource(resource)
        assert normalized["tags"] == ["boundaries", "admin"]
        assert normalized["license"] == "CC-BY-4.0"
        assert normalized["user_properties"]["contact_email"] == "test@example.com"

    def test_stac_item_includes_keywords_and_license(self):
        """STAC item includes tags as keywords and license."""
        normalized = {
            "name": "test",
            "title": "Test",
            "abstract": "",
            "type": "vector",
            "format": "vector",
            "spatial_extent": None,
            "crs": None,
            "temporal_extent": None,
            "created_at": "2024-01-01T00:00:00Z",
            "assets": {},
            "properties": {},
            "tags": ["boundaries", "admin"],
            "license": "CC-BY-4.0",
            "attribution": None,
            "user_properties": {"contact_organization": "Survey Corp"},
        }
        item = _resource_to_stac_item(normalized, "test_collection")
        assert item["properties"]["keywords"] == ["boundaries", "admin"]
        assert item["properties"]["license"] == "CC-BY-4.0"
        assert item["properties"]["portolan:contact_organization"] == "Survey Corp"

    def test_iso_includes_contact_and_keywords(self):
        """ISO 19139 XML includes contact info and keywords from user properties."""
        normalized = {
            "name": "test",
            "title": "Test Resource",
            "abstract": "A test",
            "type": "vector",
            "format": "vector",
            "spatial_extent": None,
            "created_at": "2024-01-01T00:00:00Z",
            "assets": {},
            "tags": ["boundaries", "water"],
            "license": "CC-BY-4.0",
            "user_properties": {
                "contact_organization": "National Survey",
                "contact_email": "data@survey.gov",
                "topic_category": "planningCadastre",
                "lineage": "Extracted from WFS 2024",
            },
        }
        xml = _resource_to_iso19139(normalized)
        assert "National Survey" in xml
        assert "data@survey.gov" in xml
        assert "planningCadastre" in xml
        assert "boundaries" in xml
        assert "water" in xml
        assert "CC-BY-4.0" in xml
        assert "Extracted from WFS 2024" in xml


class TestXMLEscape:
    """Test suite for XML escaping."""

    def test_escape_ampersand(self):
        """Test escaping ampersand."""
        assert _xml_escape("A & B") == "A &amp; B"

    def test_escape_less_than(self):
        """Test escaping less than."""
        assert _xml_escape("a < b") == "a &lt; b"

    def test_escape_greater_than(self):
        """Test escaping greater than."""
        assert _xml_escape("a > b") == "a &gt; b"

    def test_escape_quotes(self):
        """Test escaping quotes."""
        assert _xml_escape('say "hello"') == "say &quot;hello&quot;"

    def test_escape_empty(self):
        """Test escaping empty string."""
        assert _xml_escape("") == ""
        assert _xml_escape(None) == ""


class TestWebGenerator:
    """Test suite for web UI generation."""

    def test_web_empty_catalog(self, initialized_catalog):
        """Test web generation on empty catalog."""
        result = generate_web_catalog(initialized_catalog, verbose=False)

        assert "index.html" in result

    def test_web_with_resources(self, catalog_with_resource):
        """Test web generation with resources."""
        result = generate_web_catalog(catalog_with_resource, verbose=False)

        assert "index.html" in result

        # Check HTML file exists
        html_path = catalog_with_resource.path / "web" / "index.html"
        assert html_path.exists()

        content = html_path.read_text()
        assert "<!DOCTYPE html>" in content
        assert "Portolan Catalog" in content

    def test_web_contains_resource(self, catalog_with_resource):
        """Test that web UI contains the resource."""
        generate_web_catalog(catalog_with_resource, verbose=False)

        html_path = catalog_with_resource.path / "web" / "index.html"
        content = html_path.read_text()

        assert "Sample Cities" in content
        assert "sample" in content


class TestHTMLEscape:
    """Test suite for HTML escaping."""

    def test_escape_ampersand(self):
        """Test escaping ampersand."""
        assert _html_escape("A & B") == "A &amp; B"

    def test_escape_less_than(self):
        """Test escaping less than."""
        assert _html_escape("<script>") == "&lt;script&gt;"

    def test_escape_quotes(self):
        """Test escaping quotes."""
        assert _html_escape('"test"') == "&quot;test&quot;"


class TestDuckLakeGenerator:
    """Test suite for DuckLake generation."""

    def test_ducklake_no_parquet(self, initialized_catalog):
        """Test DuckLake generation without parquet files."""
        result = generate_ducklake_catalog(initialized_catalog, verbose=False)
        # Should return None when no parquet files
        assert result is None

    def test_ducklake_with_parquet(self, catalog_with_resource):
        """Test DuckLake generation with parquet files."""
        result = generate_ducklake_catalog(catalog_with_resource, verbose=False)

        # DuckLake file should be created
        if result is not None:
            assert result.exists()
            assert result.suffix == ".ducklake"
