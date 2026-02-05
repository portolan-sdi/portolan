# Portolan Test Resources

This document tracks verified external data sources for testing Portolan extractors.

See [Data Format Pipeline](../docs/catalog-data-model.md#data-format-pipeline) for the full architecture.

## Summary

| Extractor | Status | Tool | Metadata Captured |
|-----------|--------|------|-------------------|
| WFS | ✅ Working | ogr2ogr | Basic (service URL, layer) |
| ArcGIS FeatureServer | ✅ Working | gpio | Full (name, description, geometryType, extent, fields) |
| ArcGIS ImageServer | ✅ Working | raquet-io | Full (name, extent, pixelSize, bandCount) |
| STAC | ✅ Working | raquet-io | Full (collection, bbox, properties, assets) |
| PostgreSQL | ⏳ Pending | geopandas | - |
| Local File | ✅ Working | geopandas | Basic |

## Verified Sources

### 1. WFS (Web Feature Service)

| Name | URL | Layer | Description | Status |
|------|-----|-------|-------------|--------|
| `demarcaciones_agua` | `https://wmts.mapama.gob.es/sig/wfs_agua/demarcaciones_et/wfs` | (default) | Spanish Water Demarcations | ✅ Working |

**Test commands:**
```bash
portolan register wfs "https://wmts.mapama.gob.es/sig/wfs_agua/demarcaciones_et/wfs" \
  --name demarcaciones_agua --namespace test \
  --title "Demarcaciones Hidrográficas España"

portolan snapshot demarcaciones_agua --namespace test
portolan materialize demarcaciones_agua --namespace test

# Verify
duckdb -c "SELECT gml_id, nom_demar FROM iceberg_scan('.portolan/data/test/demarcaciones_agua/metadata/v1.metadata.json') LIMIT 5"
```

**Result:** 25 rows, 35.7 MB

**Captured metadata:**
```json
{
  "metadata": {
    "source": {
      "provider": "wfs",
      "ref": {"service_url": "https://...", "layer": null},
      "data": {"service_type": "WFS", "layer": null}
    }
  }
}
```

---

### 2. ArcGIS FeatureServer

| Name | URL | Description | Status |
|------|-----|-------------|--------|
| `wildfire_points` | `https://sampleserver6.arcgisonline.com/arcgis/rest/services/Wildfire/FeatureServer/0` | Wildfire Response Points | ✅ Working |
| `wildfire_lines` | `https://sampleserver6.arcgisonline.com/arcgis/rest/services/Wildfire/FeatureServer/1` | Wildfire Response Lines | ✅ Working |
| `wildfire_polygons` | `https://sampleserver6.arcgisonline.com/arcgis/rest/services/Wildfire/FeatureServer/2` | Wildfire Response Polygons | ✅ Working |

**Test commands:**
```bash
# Points (layer 0)
portolan register arcgis_featureserver \
  "https://sampleserver6.arcgisonline.com/arcgis/rest/services/Wildfire/FeatureServer/0" \
  --name wildfire_points --namespace test --title "Wildfire Response Points"

portolan snapshot wildfire_points --namespace test
portolan materialize wildfire_points --namespace test

# Verify
duckdb -c "SELECT objectid, eventtype FROM iceberg_scan('.portolan/data/test/wildfire_points/metadata/v1.metadata.json') LIMIT 5"
```

**Results:**
- Layer 0 (Points): 21 rows, 9.6 KB
- Layer 1 (Lines): 3 rows, 20.3 KB
- Layer 2 (Polygons): 3 rows, 29.1 KB

**Captured metadata:**
```json
{
  "metadata": {
    "source": {
      "provider": "arcgis",
      "ref": {"service_url": "https://...", "layer_id": 0},
      "data": {
        "name": "Wildfire Response Points",
        "description": "This layer contains...",
        "geometryType": "esriGeometryPoint",
        "extent": {"xmin": ..., "ymin": ..., "xmax": ..., "ymax": ...},
        "fields": [{"name": "objectid", "type": "esriFieldTypeOID", ...}],
        "capabilities": "Query,Extract"
      }
    }
  }
}
```

---

### 3. ArcGIS ImageServer

| Name | URL | Description | Status |
|------|-----|-------------|--------|
| `noaa_satellite_24hr` | `https://satellitemaps.nesdis.noaa.gov/arcgis/rest/services/MERGEDGC_Last_24hr/ImageServer` | NOAA GOES Merged Global Composite (24hr) | ✅ Working |

**Test commands:**
```bash
# Register
portolan register arcgis_imageserver \
  "https://satellitemaps.nesdis.noaa.gov/arcgis/rest/services/MERGEDGC_Last_24hr/ImageServer" \
  --name noaa_satellite_24hr --namespace test \
  --title "NOAA Satellite Merged Global Composite (24hr)"

# Snapshot with bounding box (required for large services)
portolan snapshot noaa_satellite_24hr --namespace test --bbox "-10,35,5,45"

portolan materialize noaa_satellite_24hr --namespace test

# Verify (Raquet format - QUADBIN indexed raster)
duckdb -c "SELECT block, band_1[1:5] FROM iceberg_scan('.portolan/data/test/noaa_satellite_24hr/metadata/v1.metadata.json') LIMIT 5"
```

**Result:** 120 blocks, 4 bands, 7.8M pixels, 1.3 MB (Spain bbox)

**Note:** Large ImageServers require `--bbox` parameter to limit the extraction area.

**Captured metadata:**
```json
{
  "kind": "raster",
  "metadata": {
    "source": {
      "provider": "arcgis_imageserver",
      "ref": {"service_url": "https://..."},
      "data": {
        "name": "MERGEDGC_Last_24hr",
        "description": "Merged GOES East and West...",
        "extent": {"xmin": -180, "ymin": -76.5, "xmax": 180, "ymax": 76.5},
        "pixelSizeX": 0.009,
        "pixelSizeY": 0.009,
        "bandCount": 4
      }
    }
  }
}
```

---

### 4. STAC (SpatioTemporal Asset Catalog)

| Name | URL | Collection | Description | Status |
|------|-----|------------|-------------|--------|
| `copernicus_dem_test` | `https://earth-search.aws.element84.com/v1/collections/cop-dem-glo-30/items/Copernicus_DSM_COG_10_S90_00_W180_00_DEM` | cop-dem-glo-30 | Copernicus DEM GLO-30 tile | ✅ Working |

**Test commands:**
```bash
# Register STAC item
portolan register stac \
  "https://earth-search.aws.element84.com/v1/collections/cop-dem-glo-30/items/Copernicus_DSM_COG_10_S90_00_W180_00_DEM" \
  --name copernicus_dem_test --namespace test \
  --title "Copernicus DEM Test Tile"

portolan snapshot copernicus_dem_test --namespace test
portolan materialize copernicus_dem_test --namespace test

# Verify (Raquet format for raster STAC items)
duckdb -c "SELECT block, band_1[1:5] FROM iceberg_scan('.portolan/data/test/copernicus_dem_test/metadata/v1.metadata.json')"
```

**Result:** 2 blocks (Raquet format), 5.8 KB

**Notes:**
- S3 URLs are automatically converted to HTTPS for public buckets
- Raster assets (GeoTIFF) are converted to Raquet format using raquet-io
- Parquet assets are downloaded directly
- STAC metadata (properties, bbox, collection) is preserved in `metadata.source`
- `kind` is automatically set to "raster" for GeoTIFF assets

**Captured metadata example:**
```json
{
  "kind": "raster",
  "origin": {
    "type": "stac",
    "stac_collection": "cop-dem-glo-30",
    "stac_item_id": "Copernicus_DSM_COG_10_S90_00_W180_00_DEM"
  },
  "metadata": {
    "source": {
      "provider": "stac",
      "data": {
        "collection": "cop-dem-glo-30",
        "bbox": [-180.0, -89.99, -179.0, -88.99],
        "properties": {"platform": "tandem-x", "gsd": 30, ...}
      }
    }
  }
}
```

---

## Catalog Federation

### ArcGIS Server as Catalog Source

ArcGIS FeatureServers can be treated as federated catalog sources, similar to STAC catalogs. This allows automatic discovery and import of all layers from a server.

**Test commands:**
```bash
# 1. Add ArcGIS server as catalog source
portolan catalog add \
  "https://sampleserver6.arcgisonline.com/arcgis/rest/services/Wildfire/FeatureServer" \
  --name wildfire --type arcgis

# 2. Sync to create EXTERNAL resources for all layers
portolan catalog sync wildfire
# Output: Added 3 resources: wildfire_response_points, wildfire_response_lines, wildfire_response_polygons

# 3. List registered catalogs
portolan catalog list
# wildfire (arcgis) - https://sampleserver6.arcgisonline.com/... - last sync: 2025-02-05

# 4. Batch snapshot all resources in federated namespace
portolan snapshot --all --namespace federated_wildfire --verbose
# Output: Batch snapshot complete: 3 succeeded, 0 failed

# 5. Batch materialize all resources
portolan materialize --all --namespace federated_wildfire --verbose
# Output: Batch materialize complete: 3 succeeded, 0 failed

# 6. Verify
duckdb -c "SELECT COUNT(*) FROM iceberg_scan('.portolan/data/federated_wildfire/wildfire_response_points/metadata/v1.metadata.json')"
```

**Result:**
- 3 layers automatically discovered (points, lines, polygons)
- All resources follow the lifecycle: EXTERNAL → CACHED → MATERIALIZED
- Namespace: `federated_wildfire` (auto-generated from source name)

**Created resources:**
| Name | Layer | State | Records |
|------|-------|-------|---------|
| wildfire_response_points | Wildfire Response Points | MATERIALIZED | 22 |
| wildfire_response_lines | Wildfire Response Lines | MATERIALIZED | 3 |
| wildfire_response_polygons | Wildfire Response Polygons | MATERIALIZED | 3 |

**Source tracking in `.portolan/sources.json`:**
```json
{
  "sources": {
    "wildfire": {
      "name": "wildfire",
      "type": "arcgis",
      "url": "https://sampleserver6.arcgisonline.com/arcgis/rest/services/Wildfire/FeatureServer",
      "last_sync": "2025-02-05T15:03:52.123456+00:00",
      "sync_hash": "a1b2c3d4e5f6..."
    }
  }
}
```

---

### 5. PostgreSQL/PostGIS

| Name | Connection | Table | Description | Status |
|------|------------|-------|-------------|--------|
| | | | | ⏳ Pending |

---

### 6. Local Files

| Name | Path | Format | Description | Status |
|------|------|--------|-------------|--------|
| `sample_cities` | `.portolan/sample_cities.parquet` | GeoParquet | Spanish cities test data | ✅ Working |

---

## Requirements

- `ogr2ogr` (GDAL) - for WFS extraction
- `gpio` (geoparquet-io) - for ArcGIS FeatureServer extraction
- `raquet-io` - for ArcGIS ImageServer extraction
- `duckdb` - for querying Iceberg tables

## Batch Operations

Both `snapshot` and `materialize` commands support `--all` flag for batch processing:

```bash
# Snapshot all EXTERNAL resources in a namespace
portolan snapshot --all --namespace <namespace> [--force] [--verbose]

# Materialize all CACHED resources in a namespace
portolan materialize --all --namespace <namespace> [--force] [--verbose]
```

**Behavior:**
- `snapshot --all`: Processes all EXTERNAL resources (or CACHED with `--force`)
- `materialize --all`: Processes all CACHED resources (or MATERIALIZED with `--force`)
- Reports: "Batch <operation> complete: X succeeded, Y failed"

---

## Running Tests

```bash
# Full extractor test suite
uv run pytest tests/test_extractors.py -v

# Manual verification
portolan snapshot <resource> --namespace test --verbose
portolan materialize <resource> --namespace test --verbose

# Batch workflow test
portolan catalog add <url> --name test_catalog --type arcgis
portolan catalog sync test_catalog
portolan snapshot --all --namespace federated_test_catalog
portolan materialize --all --namespace federated_test_catalog
```
