# Portolan Demo Catalog

This document showcases a Portolan catalog with different resource types, demonstrating how to discover and query geospatial data using SQL.

## Resource Types

Portolan supports three types of resources:

| Type | Description | Storage |
|------|-------------|---------|
| `managed` | Data stored in your warehouse with full control | Your GCS/S3 bucket |
| `external` | References to remote data sources | Third-party URLs |
| `external_cached` | External data with local cache for reliability | Source + local copy |

## Supported Formats

| Format | Type | Description |
|--------|------|-------------|
| **GeoParquet** | Vector | Cloud-native vector data, queryable with DuckDB Spatial |
| **Raquet** | Raster | Cloud-native raster tiles, queryable with DuckDB Raquet |
| **COG** | Raster | Cloud Optimized GeoTIFF |
| **PMTiles** | Vector Tiles | Single-file vector tile archives |
| **Zarr** | N-dimensional | Chunked, cloud-optimized arrays (climate data, etc.) |

## Demo Catalog Contents

```
┌────────────────────────┬─────────────────┬────────────┬──────────────────────────────────────────┐
│ name                   │ type            │ format     │ description                              │
├────────────────────────┼─────────────────┼────────────┼──────────────────────────────────────────┤
│ spanish_cities         │ managed         │ geoparquet │ Major cities in Spain (our data)         │
│ naturalearth_countries │ external_cached │ geoparquet │ Country boundaries (cached locally)      │
│ overture_buildings     │ external        │ geoparquet │ Overture Maps building footprints        │
│ modis_lst_spain        │ external        │ raquet     │ MODIS Land Surface Temperature           │
│ copernicus_dem         │ external        │ cog        │ Copernicus DEM 30m elevation             │
│ protomaps_basemap      │ external        │ pmtiles    │ OpenStreetMap vector tiles               │
│ era5_temperature       │ external        │ zarr       │ ERA5 climate reanalysis                  │
└────────────────────────┴─────────────────┴────────────┴──────────────────────────────────────────┘
```

## Connecting to the Catalog

### DuckDB - REST Catalog (recommended)

```sql
INSTALL iceberg;
INSTALL httpfs;
LOAD iceberg;
LOAD httpfs;

-- Attach the catalog
ATTACH '' AS catalog (
    TYPE iceberg,
    ENDPOINT 'https://storage.googleapis.com/portolan-demo-catalog',
    AUTHORIZATION_TYPE 'none'
);

-- List all resources
SELECT * FROM catalog.portolan.resources;
```

### DuckDB - Direct Iceberg Scan

```sql
SELECT * FROM iceberg_scan(
    'https://storage.googleapis.com/portolan-demo-catalog/data/resources/metadata/v1.metadata.json'
);
```

### BigQuery - BigLake Iceberg

```sql
-- Create external table (run once)
-- bq mk --table --external_table_definition=ICEBERG=gs://portolan-demo-catalog/data/resources/metadata/v1.metadata.json dataset.resources

SELECT * FROM `project.dataset.resources`;
```

---

## SQL Examples: Data Discovery

### Find all GeoParquet datasets

```sql
SELECT name, title, abstract
FROM catalog.portolan.resources
WHERE format = 'geoparquet';
```

```
┌────────────────────────┬───────────────────────────┬─────────────────────────────────────────────┐
│ name                   │ title                     │ abstract                                    │
├────────────────────────┼───────────────────────────┼─────────────────────────────────────────────┤
│ spanish_cities         │ Major Spanish Cities      │ Population and location of major cities...  │
│ overture_buildings     │ Overture Maps Buildings   │ Building footprints from Overture Maps...   │
│ naturalearth_countries │ Natural Earth Countries   │ Country boundaries from Natural Earth...    │
└────────────────────────┴───────────────────────────┴─────────────────────────────────────────────┘
```

### Find datasets covering a specific area (Spain)

```sql
SELECT name, format, title
FROM catalog.portolan.resources
WHERE bbox_west <= 0
  AND bbox_east >= -4
  AND bbox_south <= 40
  AND bbox_north >= 40;
```

### Find raster datasets

```sql
SELECT name, format, title,
       json_extract_string(assets, '$.data.href') as url
FROM catalog.portolan.resources
WHERE format IN ('cog', 'raquet', 'zarr');
```

### Search by keyword in title or abstract

```sql
SELECT name, format, title
FROM catalog.portolan.resources
WHERE LOWER(title) LIKE '%temperature%'
   OR LOWER(abstract) LIKE '%temperature%';
```

### List managed vs external data

```sql
SELECT type, COUNT(*) as count,
       STRING_AGG(name, ', ') as datasets
FROM catalog.portolan.resources
GROUP BY type;
```

---

## SQL Examples: Querying GeoParquet with DuckDB Spatial

DuckDB's spatial extension allows direct querying of GeoParquet files with full geometry support.

### Setup

```sql
INSTALL spatial;
LOAD spatial;
```

### Query Overture Buildings in a bounding box

```sql
-- Find buildings in central Madrid
SELECT id, names, height, ST_Area(geometry) as area_m2
FROM read_parquet('s3://overturemaps-us-west-2/release/2024-11-13.0/theme=buildings/type=building/*')
WHERE bbox.xmin >= -3.71 AND bbox.xmax <= -3.68
  AND bbox.ymin >= 40.41 AND bbox.ymax <= 40.43
LIMIT 100;
```

### Spatial join: Cities within country boundaries

```sql
-- Using the catalog to find the data URLs first
WITH cities AS (
    SELECT * FROM read_parquet(
        'gs://portolan-demo-catalog/data/demo/spanish_cities/spanish_cities.parquet'
    )
),
countries AS (
    SELECT * FROM read_parquet(
        'gs://portolan-demo-catalog/cache/naturalearth_countries.parquet'
    )
)
SELECT
    c.name as city,
    c.population,
    co.NAME as country
FROM cities c
JOIN countries co ON ST_Within(c.geometry, co.geometry);
```

### Calculate distances between cities

```sql
SELECT
    a.name as from_city,
    b.name as to_city,
    ROUND(ST_Distance_Spheroid(a.geometry, b.geometry) / 1000, 1) as distance_km
FROM read_parquet('gs://portolan-demo-catalog/data/demo/spanish_cities/spanish_cities.parquet') a
CROSS JOIN read_parquet('gs://portolan-demo-catalog/data/demo/spanish_cities/spanish_cities.parquet') b
WHERE a.name < b.name
ORDER BY distance_km;
```

### Aggregate statistics by region

```sql
-- Total population within a polygon
SELECT SUM(population) as total_pop
FROM read_parquet('gs://portolan-demo-catalog/data/demo/spanish_cities/spanish_cities.parquet')
WHERE ST_Within(
    geometry,
    ST_GeomFromText('POLYGON((-4 39, -3 39, -3 41, -4 41, -4 39))')
);
```

---

## SQL Examples: Querying Raquet (Cloud-Native Raster)

Raquet enables SQL queries on raster data using the DuckDB Raquet extension.

### Setup

```sql
LOAD raquet;
```

### Explore the dataset structure

```sql
-- Get metadata about the raster
SELECT metadata
FROM read_raquet_metadata('https://storage.googleapis.com/raquet_demo_data/modis_lst_spain_v2.parquet');

-- Count tiles and resolution
SELECT
    COUNT(*) as total_tiles,
    COUNT(DISTINCT quadbin_resolution(block)) as resolutions
FROM read_raquet('https://storage.googleapis.com/raquet_demo_data/modis_lst_spain_v2.parquet');
```

### Get temperature at a specific location (Madrid)

```sql
-- Extract Land Surface Temperature at Madrid city center
SELECT
    ST_RasterValue(
        block,
        band_1,
        -3.7038,  -- longitude
        40.4168,  -- latitude
        'float32',
        256,
        'gzip'
    ) * 0.02 - 273.15 as temperature_celsius  -- MODIS scale factor + Kelvin to Celsius
FROM read_raquet('https://storage.googleapis.com/raquet_demo_data/modis_lst_spain_v2.parquet')
WHERE block = quadbin_from_lonlat(-3.7038, 40.4168, 13);
```

### Calculate statistics for a region

```sql
-- Get LST statistics for all tiles covering Spain
SELECT
    block,
    (quadbin_to_bbox(block)).* as bbox,
    (ST_RasterSummaryStats(band_1, 'float32', 256, 256, 'gzip')).*
FROM read_raquet('https://storage.googleapis.com/raquet_demo_data/modis_lst_spain_v2.parquet')
LIMIT 10;
```

### Find hottest and coldest tiles

```sql
SELECT
    block,
    (quadbin_to_lonlat(block)).* as center,
    (ST_RasterSummaryStats(band_1, 'float32', 256, 256, 'gzip')).max * 0.02 - 273.15 as max_temp_c
FROM read_raquet('https://storage.googleapis.com/raquet_demo_data/modis_lst_spain_v2.parquet')
ORDER BY max_temp_c DESC
LIMIT 5;
```

### Point-raster join: Temperature at each city

```sql
-- Get temperature for each Spanish city from the catalog
WITH cities AS (
    SELECT name, population, ST_X(geometry) as lon, ST_Y(geometry) as lat
    FROM read_parquet('gs://portolan-demo-catalog/data/demo/spanish_cities/spanish_cities.parquet')
)
SELECT
    c.name,
    c.population,
    ST_RasterValue(
        r.block, r.band_1,
        c.lon, c.lat,
        'float32', 256, 'gzip'
    ) * 0.02 - 273.15 as temperature_celsius
FROM cities c
JOIN read_raquet('https://storage.googleapis.com/raquet_demo_data/modis_lst_spain_v2.parquet') r
ON r.block = quadbin_from_lonlat(c.lon, c.lat, 13);
```

### Spatial filtering with bounding box

```sql
-- Get tiles intersecting Andalusia region
SELECT block, (quadbin_to_bbox(block)).*
FROM read_raquet('https://storage.googleapis.com/raquet_demo_data/modis_lst_spain_v2.parquet')
WHERE quadbin_intersects_bbox(block, -7.5, 36.0, -1.5, 38.5)  -- Andalusia bbox
LIMIT 10;
```

---

## The Power of Unified Discovery

The key value of Portolan is **unified discovery** - one SQL query finds data across:
- Different formats (GeoParquet, Raquet, COG, PMTiles, Zarr)
- Different storage locations (your warehouse, public clouds, partner data)
- Different providers (Overture, Microsoft, Google, your organization)

```sql
-- One query to find all datasets about Spain
SELECT
    name,
    type,
    format,
    title,
    json_extract_string(assets, '$.data.href') as access_url
FROM catalog.portolan.resources
WHERE (bbox_west <= 4.5 AND bbox_east >= -9.5
       AND bbox_south <= 44 AND bbox_north >= 35.5)
   OR LOWER(title) LIKE '%spain%'
ORDER BY format;
```

Then, depending on the format, use the appropriate DuckDB extension to query the actual data:
- **GeoParquet**: `read_parquet()` with Spatial extension
- **Raquet**: `read_raquet()` with Raquet extension
- **COG/Zarr**: Use STAC URLs with appropriate libraries

This is the essence of a modern **Spatial Data Infrastructure (SDI)** - discover once, query with the best tool for each format.

---

## Complete Workflow: Discover → Query Raquet

This example shows the full power of the catalog: discover a dataset through SQL, then query it directly.

```sql
INSTALL iceberg; INSTALL httpfs;
LOAD iceberg; LOAD httpfs;
LOAD raquet;  -- For raster queries

-- 1. Attach the catalog
ATTACH '' AS catalog (
    TYPE iceberg,
    ENDPOINT 'https://storage.googleapis.com/portolan-demo-catalog',
    AUTHORIZATION_TYPE 'none'
);

-- 2. Find the Raquet dataset and get its URL
WITH raquet_dataset AS (
    SELECT
        name,
        title,
        json_extract_string(assets, '$.data.href') as data_url
    FROM catalog.portolan.resources
    WHERE format = 'raquet'
    LIMIT 1
)
SELECT * FROM raquet_dataset;

-- Result:
-- ┌─────────────────┬────────────────────────────────────────┬─────────────────────────────────────────────────────────────┐
-- │ name            │ title                                  │ data_url                                                    │
-- ├─────────────────┼────────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
-- │ modis_lst_spain │ MODIS Land Surface Temperature - Spain │ https://storage.googleapis.com/raquet_demo_data/modis_lst.. │
-- └─────────────────┴────────────────────────────────────────┴─────────────────────────────────────────────────────────────┘

-- 3. Get temperature at Madrid using the discovered URL
WITH raquet_url AS (
    SELECT json_extract_string(assets, '$.data.href') as url
    FROM catalog.portolan.resources
    WHERE format = 'raquet' LIMIT 1
),
madrid AS (SELECT -3.7038 as lon, 40.4168 as lat)
SELECT
    'Madrid' as city,
    ST_RasterValue(
        r.block, r.band_1,
        madrid.lon, madrid.lat,
        'float32', 256, 'gzip'
    ) * 0.02 - 273.15 as temperature_celsius
FROM read_raquet((SELECT url FROM raquet_url)) r, madrid
WHERE r.block = quadbin_from_lonlat(madrid.lon, madrid.lat, 13);
```

### Or use the Direct Table (no URL lookup needed!)

Since Raquet files are registered as direct Iceberg tables, you can also query directly:

```sql
-- Direct access without URL lookup
SELECT
    block,
    (quadbin_to_lonlat(block)).* as center,
    (ST_RasterSummaryStats(band_1, 'float32', 256, 256, 'gzip')).mean as mean_temp_raw
FROM catalog.portolan.modis_lst_spain
LIMIT 5;
```

This is the hybrid approach: use `catalog.portolan.resources` for **discovery** across all formats, then use direct tables like `catalog.portolan.modis_lst_spain` for **querying** Parquet-based data.
