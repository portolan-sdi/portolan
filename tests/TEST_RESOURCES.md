# Portolan Test Resources

Test resources for building a demo catalog. Uses the current CLI: `add`, `load`, `refresh`.

See [Data Format Pipeline](../docs/catalog-data-model.md#data-format-pipeline) for the full architecture.

## Resource Summary

| # | Name | Type | Source | Kind | Size | Status |
|---|------|------|--------|------|------|--------|
| 1 | `demarcaciones_agua` | WFS | Spanish Water Demarcations | vector | 25 rows, 35 MB | Verified |
| 2 | `wildfire_points` | ArcGIS FeatureServer | ESRI Sample Wildfire Points | vector | 21 rows, 10 KB | Verified |
| 3 | `wildfire_lines` | ArcGIS FeatureServer | ESRI Sample Wildfire Lines | vector | 3 rows, 20 KB | Verified |
| 4 | `wildfire_polygons` | ArcGIS FeatureServer | ESRI Sample Wildfire Polygons | vector | 3 rows, 29 KB | Verified |
| 5 | `noaa_satellite_24hr` | ArcGIS ImageServer | NOAA GOES Merged Global Composite | raster | ~120 blocks, 1.3 MB | Verified |
| 6 | `copernicus_dem_test` | STAC | Copernicus DEM GLO-30 tile | raster | 2 blocks, 6 KB | Verified |
| 7 | `sample_cities` | Local file | GeoParquet test cities | vector | 5 rows, 2 KB | Verified |
| 8 | `overture_buildings` | Remote GeoParquet | Overture Maps Buildings (Spain) | vector | ~millions, linked | To test |
| 9 | `autzen_pointcloud` | Local LAZ | PDAL Autzen LiDAR scan | pointcloud | 10.6M points, 56 MB | To test |
| 10 | `autzen_copc` | Remote COPC | PDAL Autzen classified (cloud-native) | pointcloud | ~10M points, linked | To test |
| 11 | `overture_tiles` | PMTiles | Overture Maps Buildings vector tiles | tiles | catalog-only, linked | To test |

## Requirements

- `ogr2ogr` (GDAL) — WFS extraction
- `gpio` (geoparquet-io) — ArcGIS FeatureServer extraction
- `raquet-io` — ArcGIS ImageServer and STAC raster extraction
- `duckdb` — querying Iceberg tables

## Resources

### 1. WFS — Spanish Water Demarcations

```bash
portolan add "https://wmts.mapama.gob.es/sig/wfs_agua/demarcaciones_et/wfs" \
  --type wfs --name demarcaciones_agua --namespace spain \
  --title "Demarcaciones Hidrográficas España" -v
```

- **Result:** 25 rows, 35.7 MB
- **Extractor:** ogr2ogr
- **Source metadata:** service_url, layer

### 2–4. ArcGIS FeatureServer — Wildfire Layers

```bash
# Points (layer 0)
portolan add "https://sampleserver6.arcgisonline.com/arcgis/rest/services/Wildfire/FeatureServer/0" \
  --name wildfire_points --namespace wildfire \
  --title "Wildfire Response Points" -v

# Lines (layer 1)
portolan add "https://sampleserver6.arcgisonline.com/arcgis/rest/services/Wildfire/FeatureServer/1" \
  --name wildfire_lines --namespace wildfire \
  --title "Wildfire Response Lines" -v

# Polygons (layer 2)
portolan add "https://sampleserver6.arcgisonline.com/arcgis/rest/services/Wildfire/FeatureServer/2" \
  --name wildfire_polygons --namespace wildfire \
  --title "Wildfire Response Polygons" -v
```

- **Results:** Points: 21 rows (9.6 KB), Lines: 3 rows (20.3 KB), Polygons: 3 rows (29.1 KB)
- **Extractor:** gpio
- **Source metadata:** name, description, geometryType, extent, fields (full schema)

**Alternative — bulk load all layers at once:**
```bash
portolan load "https://sampleserver6.arcgisonline.com/arcgis/rest/services/Wildfire/FeatureServer" \
  --type arcgis-server --namespace wildfire -v
portolan refresh --all --namespace wildfire -v
```

### 5. ArcGIS ImageServer — NOAA Satellite

```bash
portolan add "https://satellitemaps.nesdis.noaa.gov/arcgis/rest/services/MERGEDGC_Last_24hr/ImageServer" \
  --name noaa_satellite_24hr --namespace satellite \
  --title "NOAA Satellite Merged Global Composite (24hr)" \
  --bbox "-10,35,5,45" -v
```

- **Result:** ~120 blocks, 4 bands, 1.3 MB (Spain bbox)
- **Extractor:** raquet-io (converts to Raquet format)
- **Source metadata:** name, description, extent, pixelSizeX/Y, bandCount
- **Note:** Large ImageServers require `--bbox` to limit extraction area

### 6. STAC — Copernicus DEM

```bash
portolan add "https://earth-search.aws.element84.com/v1/collections/cop-dem-glo-30/items/Copernicus_DSM_COG_10_S90_00_W180_00_DEM" \
  --type stac --name copernicus_dem_test --namespace satellite \
  --title "Copernicus DEM Test Tile" -v
```

- **Result:** 2 blocks (Raquet format), 5.8 KB
- **Extractor:** raquet-io (GeoTIFF → Raquet)
- **Source metadata:** collection, bbox, properties (platform, gsd, datetime)
- **Notes:** S3 URLs auto-converted to HTTPS for public buckets. `kind` auto-set to `raster`.

### 7. Local File — Sample Cities

```bash
# Generate a test GeoParquet first
duckdb -c "INSTALL spatial; LOAD spatial; COPY (
  SELECT name, country, population, ST_Point(longitude, latitude) as geometry
  FROM (VALUES
    ('Paris', 'France', 2161000, 2.3522, 48.8566),
    ('Berlin', 'Germany', 3645000, 13.4050, 52.5200),
    ('Rome', 'Italy', 2873000, 12.4964, 41.9028),
    ('Madrid', 'Spain', 3223000, -3.7038, 40.4168),
    ('London', 'UK', 8982000, -0.1276, 51.5074)
  ) AS t(name, country, population, longitude, latitude)
) TO 'sample_cities.parquet' (FORMAT PARQUET)"

portolan add sample_cities.parquet \
  --name sample_cities --namespace demo \
  --title "European Capital Cities" -v
```

- **Result:** 5 rows, ~2 KB
- **Extractor:** direct file copy + geopandas
- **Source metadata:** basic (file path)

### 8. Remote GeoParquet — Overture Maps Buildings

```bash
# Linked mode (default) — creates Iceberg pointing to remote files, no download
# Using Spain bbox to keep it manageable; glob pattern for multi-file dataset
portolan add "s3://overturemaps-us-west-2/release/2025-11-19.0/theme=buildings/type=building/*" \
  --name overture_buildings --namespace overture \
  --title "Overture Maps Buildings (Spain)" \
  --bbox "-10,35,5,45" -v

# With --cache-data to force local download (slower, for offline use)
portolan add "s3://overturemaps-us-west-2/release/2025-11-19.0/theme=buildings/type=building/*" \
  --name overture_buildings_local --namespace overture \
  --title "Overture Maps Buildings (Spain, local)" \
  --bbox "-10,35,5,45" --cache-data -v
```

- **Source:** [Overture Maps on AWS](https://registry.opendata.aws/overture/)
- **Result:** Millions of buildings (linked Iceberg, no download). State: READY + linked.
- **Action:** `remote` (auto-detected: cloud-native GeoParquet → create remote Iceberg)
- **Tests:** Remote file listing via glob, schema read via range request, multi-file Iceberg
- **Note:** Full dataset is ~230 GB. The bbox filter limits to Spain. Release versions change monthly.

### 9. Local LAZ — PDAL Autzen LiDAR

```bash
# Download test file first
curl -L -o autzen.laz https://github.com/PDAL/data/raw/refs/heads/main/autzen/autzen.laz

portolan add autzen.laz \
  --name autzen_pointcloud --namespace lidar \
  --title "Autzen Hall LiDAR Scan" -v
```

- **Source:** [PDAL test data](https://github.com/PDAL/data/blob/main/autzen/autzen.laz)
- **Result:** 10.6M points, ~56 MB LAZ → Parquet conversion
- **Extractor:** DuckDB PDAL extension (`PDAL_Read` → Parquet)
- **Kind:** auto-detected as pointcloud
- **Requires:** `duckdb` with `pdal` community extension

### 10. Remote COPC — PDAL Autzen Classified (cloud-native)

```bash
# COPC is cloud-optimized, so this creates a linked Iceberg without downloading
portolan add "https://s3.amazonaws.com/hobu-lidar/autzen-classified.copc.laz" \
  --name autzen_copc --namespace lidar \
  --title "Autzen Hall Classified (COPC)" -v
```

- **Source:** [COPC spec site](https://copc.io/)
- **Result:** Linked Iceberg pointing to remote COPC file. State: READY + linked.
- **Action:** `remote` (auto-detected: `.copc.laz` is cloud-native)
- **Tests:** Remote cloud-native point cloud, COPC handling, schema extraction via range request

### 11. PMTiles — Overture Maps Buildings Vector Tiles

```bash
portolan add "https://overturemaps-tiles-us-west-2-beta.s3.amazonaws.com/2025-03-19/buildings.pmtiles" \
  --name overture_tiles --namespace overture \
  --title "Overture Maps Buildings (PMTiles)" -v
```

- **Source:** [Overture Maps PMTiles](https://docs.overturemaps.org/examples/overture-tiles/)
- **Result:** Catalog-only (registered, not queryable). State: REGISTERED.
- **Kind:** `tiles` (auto-detected from `.pmtiles` extension)
- **Action:** `catalog_only` (tiles are discoverable but not queryable — no snapshot/iceberg)
- **Tests:** PMTiles detection, tiles kind, catalog-only routing

## Verification

```bash
# Check status
portolan status -v

# Show metadata (including column schema)
portolan metadata show demarcaciones_agua --namespace spain
portolan metadata show wildfire_points --namespace wildfire

# Query via DuckDB
duckdb -c "SELECT * FROM iceberg_scan('.portolan/data/wildfire/wildfire_points/metadata/v1.metadata.json') LIMIT 5"

# Rebuild all outputs (STAC, ISO, web)
portolan rebuild -v
```

## Bulk Load (Federation)

The `load` command discovers and registers resources from external catalogs:

```bash
# Load all layers from an ArcGIS server
portolan load "https://sampleserver6.arcgisonline.com/arcgis/rest/services/Wildfire/FeatureServer" \
  --type arcgis-server --namespace wildfire -v

# Preview what would be loaded
portolan load "https://sampleserver6.arcgisonline.com/arcgis/rest/services/Wildfire/FeatureServer" \
  --type arcgis-server --dry-run

# Then fetch data for all registered resources
portolan refresh --all --namespace wildfire -v
```
