"""
Pytest configuration and shared fixtures for Portolan tests.
"""

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

# Test data directory
TEST_DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture
def test_data_dir():
    """Return the path to the test data directory."""
    TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
    return TEST_DATA_DIR


@pytest.fixture
def temp_catalog_dir():
    """Create a temporary directory for a test catalog."""
    temp_dir = tempfile.mkdtemp(prefix="portolan_test_")
    yield Path(temp_dir)
    # Cleanup after test
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def sample_geoparquet(temp_catalog_dir):
    """Create a sample GeoParquet file for testing."""
    import duckdb

    parquet_path = temp_catalog_dir / "sample.parquet"

    conn = duckdb.connect()
    conn.execute("INSTALL spatial; LOAD spatial")
    conn.execute(f"""
        COPY (
            SELECT
                name,
                country,
                population,
                ST_Point(longitude, latitude) as geometry
            FROM (VALUES
                ('Paris', 'France', 2161000, 2.3522, 48.8566),
                ('Berlin', 'Germany', 3645000, 13.4050, 52.5200),
                ('Rome', 'Italy', 2873000, 12.4964, 41.9028)
            ) AS t(name, country, population, longitude, latitude)
        ) TO '{parquet_path}' (FORMAT PARQUET)
    """)
    conn.close()

    return parquet_path


@pytest.fixture
def initialized_catalog(temp_catalog_dir):
    """Create an initialized Portolan catalog for testing."""
    from catalog_state import LocalState
    from portolan import CatalogConfig

    catalog_path = temp_catalog_dir / ".portolan"
    catalog = CatalogConfig(path=catalog_path)
    catalog.path.mkdir(parents=True, exist_ok=True)
    catalog.data_dir.mkdir(exist_ok=True)
    catalog.metadata_dir.mkdir(exist_ok=True)

    # Create resources directory
    resources_dir = catalog.path / "resources"
    resources_dir.mkdir(exist_ok=True)

    # Initialize state
    state = LocalState(remote_url=None)
    state.save(catalog.path / "state.json")

    catalog.save()

    return catalog


@pytest.fixture
def catalog_with_resource(initialized_catalog, sample_geoparquet):
    """Create a catalog with a sample resource."""
    import shutil
    from datetime import datetime, timezone

    catalog = initialized_catalog

    # Create namespace directory
    namespace = "test"
    resources_dir = catalog.path / "resources" / namespace
    resources_dir.mkdir(parents=True, exist_ok=True)

    # Copy parquet to data directory
    data_dir = catalog.data_dir / namespace / "sample"
    data_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(sample_geoparquet, data_dir / "sample.parquet")

    # Create resource JSON
    resource = {
        "name": "sample",
        "type": "managed",
        "format": "geoparquet",
        "title": "Sample Cities",
        "abstract": "A sample dataset of European cities",
        "origin": "portolan",
        "spatial_extent": {
            "west": 2.3522,
            "south": 41.9028,
            "east": 13.4050,
            "north": 52.5200,
        },
        "crs": "EPSG:4326",
        "assets": {
            "data": {
                "href": f"data/{namespace}/sample/sample.parquet",
                "type": "application/vnd.apache.parquet",
                "title": "GeoParquet file",
            }
        },
        "properties": {"row_count": 3},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    resource_path = resources_dir / "sample.json"
    with open(resource_path, "w") as f:
        json.dump(resource, f, indent=2)

    return catalog


# Helper functions


def get_catalog_resource_count(catalog_path: Path) -> int:
    """Count resources in a catalog."""
    resources_dir = catalog_path / "resources"
    if not resources_dir.exists():
        return 0
    count = 0
    for ns_dir in resources_dir.iterdir():
        if ns_dir.is_dir():
            count += len(list(ns_dir.glob("*.json")))
    return count


def get_catalog_namespaces(catalog_path: Path) -> list[str]:
    """Get list of namespaces in a catalog."""
    resources_dir = catalog_path / "resources"
    if not resources_dir.exists():
        return []
    return [d.name for d in resources_dir.iterdir() if d.is_dir()]
