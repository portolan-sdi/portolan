# Portolan: Geospatial Data Infrastructure for the Modern Stack

A presentation on architecture, design decisions, and implementation.

---

## The Problem

### Traditional SDI Pain Points

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Current Reality                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
│   │ Shapefile│  │ GeoJSON  │  │ PostGIS  │  │  ArcGIS  │  │ WFS/WMS  │ │
│   └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘ │
│        │             │             │             │             │        │
│        └─────────────┴──────┬──────┴─────────────┴─────────────┘        │
│                             ▼                                           │
│                    ┌────────────────┐                                   │
│                    │ Different APIs │                                   │
│                    │ for each source│                                   │
│                    └────────┬───────┘                                   │
│                             │                                           │
│        ┌────────────────────┼────────────────────┐                      │
│        ▼                    ▼                    ▼                      │
│  ┌───────────┐      ┌───────────────┐    ┌─────────────┐               │
│  │ No unified│      │    Format     │    │     No      │               │
│  │   query   │      │  conversions  │    │ versioning  │               │
│  └───────────┘      └───────────────┘    └─────────────┘               │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**Pain Points:**
- Fragmented data sources with incompatible APIs
- No standard way to discover and query geospatial metadata
- Format proliferation (Shapefile, GeoJSON, GeoPackage, etc.)
- Difficult for AI/LLMs to understand and query
- No cloud-native workflow

---

## The Solution: Portolan

### Core Value Proposition

```
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│       WFS       │  │     ArcGIS      │  │      STAC       │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              ▼
         ┌────────────────────────────────────────────┐
         │              PORTOLAN CATALOG              │
         │                                            │
         │  ┌──────────────┐  ┌───────────────────┐  │
         │  │  GeoParquet  │  │  Iceberg Tables   │  │
         │  └──────────────┘  └───────────────────┘  │
         │                                            │
         │  ┌──────────────────────────────────────┐ │
         │  │         Cloud Storage (S3/GCS)       │ │
         │  └──────────────────────────────────────┘ │
         └────────────────────┬───────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│    SQL Query    │  │    STAC API     │  │   ISO 19139     │
│ DuckDB/Snowflake│  │                 │  │    OGC API      │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

**Portolan provides:**
1. **Unified ingestion** from any geospatial source
2. **Cloud-native formats** (GeoParquet, COG, Iceberg)
3. **SQL-queryable metadata** via Iceberg tables
4. **Multi-standard outputs** (STAC, ISO 19139, OGC)
5. **AI-ready** with Open Semantic Interchange (OSI)

---

## Architecture Overview

### Local-First Design

```
┌──────────────────────────────────────────────────────────────────────┐
│                        LOCAL (.portolan/)                            │
│                                                                      │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────┐  │
│   │ config.json │  │ resources/  │  │    data/    │  │ state.json│  │
│   └─────────────┘  └─────────────┘  └─────────────┘  └───────────┘  │
│                                                                      │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               │ portolan sync
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        REMOTE (GCS/S3)                               │
│                                                                      │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌───────────┐  │
│   │   Iceberg   │  │ Data Files  │  │    STAC     │  │ ISO 19139 │  │
│   │   Catalog   │  │  (Parquet)  │  │   Catalog   │  │    XML    │  │
│   └─────────────┘  └─────────────┘  └─────────────┘  └───────────┘  │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

**Design Decision:** Local-first workflow allows offline work, version control of metadata, and batch operations before syncing to cloud storage.

---

## Resource Lifecycle

### Type-Aware Behavior

The lifecycle is **type-aware** - vectors and rasters take different paths:

```
  VECTOR (GeoParquet):
  ┌─────────────┐    snapshot     ┌──────────────────────────────────┐
  │  EXTERNAL   │ ──────────────▶ │  MATERIALIZED                    │
  │  (reference)│    (cheap)      │  GeoParquet + Iceberg metadata   │
  └─────────────┘                 │  (auto-registered, no rewrite!)  │
       register                   └──────────────────────────────────┘

  RASTER (COG/Zarr → Raquet):
  ┌─────────────┐    snapshot     ┌─────────────┐  materialize  ┌──────────────┐
  │  EXTERNAL   │ ──────────────▶ │   CACHED    │ ────────────▶ │ MATERIALIZED │
  │  (reference)│    (download)   │  COG / Zarr │  (expensive)  │ Raquet +     │
  └─────────────┘                 └─────────────┘               │ Iceberg meta │
       register                                                 └──────────────┘
```

| Kind | snapshot | materialize |
|------|----------|-------------|
| **Vector** | Download + auto-create Iceberg metadata (free!) | No-op (already done) |
| **Raster** | Download to COG/Zarr (cache only) | Convert to Raquet + Iceberg (expensive) |

**Key insight:** For vectors, Iceberg registration is free thanks to "lightweight Iceberg"
(name-mapping property). So snapshot does it automatically. For rasters, format conversion
is expensive, so it remains an explicit step.

---

## Data Format Pipeline

### Format Transformation Strategy

```
  ORIGIN (Various)              CACHE (Cloud-Native)         MATERIALIZED (Iceberg)
┌─────────────────────┐       ┌─────────────────────┐       ┌─────────────────────┐
│                     │       │                     │       │                     │
│  Shapefile          │       │                     │       │  GeoParquet         │
│  GeoJSON            │ ────▶ │  GeoParquet         │ ────▶ │  + Iceberg metadata │
│  WFS                │       │                     │       │                     │
│  ArcGIS FeatureServer       │                     │       │                     │
│                     │       │                     │       │                     │
├─────────────────────┤       ├─────────────────────┤       ├─────────────────────┤
│                     │       │                     │       │                     │
│  GeoTIFF            │       │  COG                │       │  Raquet             │
│  ArcGIS ImageServer │ ────▶ │  or                 │ ────▶ │  (QUADBIN indexed)  │
│  STAC raster assets │       │  Zarr               │       │                     │
│                     │       │                     │       │                     │
├─────────────────────┤       ├─────────────────────┤       ├─────────────────────┤
│                     │       │                     │       │                     │
│  LAS / LAZ          │ ────▶ │  COPC               │ ────▶ │  Pointquet          │
│  E57                │       │                     │       │                     │
│                     │       │                     │       │                     │
├─────────────────────┤       ├─────────────────────┤       ├─────────────────────┤
│                     │       │                     │       │                     │
│  MBTiles            │ ────▶ │  Tilesets           │ ────▶ │  Tilequet           │
│  PMTiles            │       │                     │       │                     │
│                     │       │                     │       │                     │
└─────────────────────┘       └─────────────────────┘       └─────────────────────┘
```

### Format Summary

| Kind | snapshot produces | materialize produces | Steps |
|------|-------------------|----------------------|-------|
| **Vector** | GeoParquet + Iceberg metadata | (already done) | 1 step |
| **Raster** | COG or Zarr (cache only) | Raquet (QUADBIN) + Iceberg | 2 steps |
| **Point Cloud** | COPC | Pointquet + Iceberg | 2 steps |
| **Tileset** | Tilesets | Tilequet + Iceberg | 2 steps |

**Key Insight:** Vector data gets Iceberg "for free" (lightweight Iceberg = no data rewrite). Raster/point cloud/tileset formats require expensive conversion, so materialization is explicit.

---

## Extractors

### Supported Sources

```
┌─────────────────────────────────────────────────────────────────────┐
│                         VECTOR SOURCES                              │
│                                                                     │
│  ┌─────────┐    ┌─────────────────┐    ┌─────────┐    ┌─────────┐ │
│  │   WFS   │    │ArcGIS           │    │ PostGIS │    │  Local  │ │
│  │         │    │FeatureServer    │    │         │    │  Files  │ │
│  └────┬────┘    └────────┬────────┘    └────┬────┘    └────┬────┘ │
│       │                  │                  │              │       │
│       │ ogr2ogr          │ gpio             │ geopandas    │ geopandas
│       │                  │                  │              │       │
│       └──────────────────┴────────┬─────────┴──────────────┘       │
│                                   ▼                                 │
│                           ┌─────────────┐                          │
│                           │ GeoParquet  │                          │
│                           └─────────────┘                          │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                         RASTER SOURCES                              │
│                                                                     │
│  ┌─────────────────┐    ┌─────────────┐    ┌─────────────────────┐ │
│  │ArcGIS           │    │   STAC      │    │     GeoTIFF         │ │
│  │ ImageServer     │    │   Assets    │    │                     │ │
│  └────────┬────────┘    └──────┬──────┘    └──────────┬──────────┘ │
│           │                    │                      │            │
│           │ raquet-io          │ download             │ raquet-io  │
│           │                    │ + raquet-io          │            │
│           └────────────────────┴───────────┬──────────┘            │
│                                            ▼                        │
│                                    ┌─────────────┐                 │
│                                    │ COG/Raquet  │                 │
│                                    └─────────────┘                 │
└─────────────────────────────────────────────────────────────────────┘
```

### Extractor Summary

| Source | Tool | Output | Metadata Captured |
|--------|------|--------|-------------------|
| WFS | `ogr2ogr` | GeoParquet | Service URL, layer |
| ArcGIS FeatureServer | `gpio` | GeoParquet | Name, fields, extent, geometry type |
| ArcGIS ImageServer | `raquet-io` | Raquet | Name, extent, pixel size, bands |
| STAC | `httpx` + `raquet-io` | GeoParquet/Raquet | Collection, bbox, properties, assets |
| PostGIS | `geopandas` | GeoParquet | Table, connection ref |
| Local File | `geopandas` | GeoParquet | Path, format |

---

## Catalog Federation

### Multi-Catalog Aggregation

```
┌──────────────────────────────────────────────────────────────────────┐
│                       UPSTREAM CATALOGS                              │
│                                                                      │
│   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐ │
│   │  STAC Catalog   │  │  ArcGIS Server  │  │  Another Portolan   │ │
│   │  (earth-search) │  │  (Wildfire FS)  │  │    Catalog          │ │
│   └────────┬────────┘  └────────┬────────┘  └──────────┬──────────┘ │
│            │                    │                      │            │
└────────────┼────────────────────┼──────────────────────┼────────────┘
             │                    │                      │
             │     portolan catalog sync                 │
             │                    │                      │
             ▼                    ▼                      ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       PORTOLAN CATALOG                               │
│                                                                      │
│   ┌────────────────────────────────────────────────────────────┐    │
│   │              CatalogSource Registry                        │    │
│   │              (.portolan/sources.json)                      │    │
│   └────────────────────────────────────────────────────────────┘    │
│                                                                      │
│   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐ │
│   │federated_        │  │federated_        │  │federated_        │ │
│   │  earth_search/   │  │  wildfire/       │  │  partner/        │ │
│   │                  │  │                  │  │                  │ │
│   │ ○ sentinel_2     │  │ ○ response_pts   │  │ ○ buildings      │ │
│   │ ○ landsat_8      │  │ ○ response_lines │  │ ○ roads          │ │
│   │ ○ dem            │  │ ○ response_polys │  │ ○ parcels        │ │
│   └──────────────────┘  └──────────────────┘  └──────────────────┘ │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### Federation Workflow

```bash
# 1. Register upstream catalog
portolan catalog add https://server/FeatureServer --name wildfire --type arcgis

# 2. Sync to discover resources
portolan catalog sync wildfire
# → Creates EXTERNAL resources in federated_wildfire/

# 3. Batch snapshot all discovered resources
portolan snapshot --all --namespace federated_wildfire

# 4. Batch materialize to Iceberg
portolan materialize --all --namespace federated_wildfire
```

**Design Decision:** Treat ArcGIS servers like STAC catalogs - both are "catalog sources" that can be synced to discover multiple resources.

---

## Output Generation

### Multi-Standard Compatibility

```
                    ┌─────────────────────────┐
                    │     Resource JSON       │
                    │   (Source of Truth)     │
                    └────────────┬────────────┘
                                 │
         ┌───────────┬───────────┼───────────┬───────────┐
         │           │           │           │           │
         ▼           ▼           ▼           ▼           ▼
    ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
    │ Iceberg │ │  STAC   │ │ISO 19139│ │DuckLake │ │  Web    │
    │Metadata │ │  Item   │ │   XML   │ │   SQL   │ │  JSON   │
    └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘
         │           │           │           │           │
         ▼           ▼           ▼           ▼           ▼
    ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
    │ DuckDB  │ │  STAC   │ │ INSPIRE │ │Embedded │ │ Browser │
    │Snowflake│ │ Clients │ │GeoNetwork│ │Analytics│ │   UI    │
    │  Spark  │ │         │ │         │ │         │ │         │
    └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘
```

### Output Formats

| Output | Format | Use Case |
|--------|--------|----------|
| **Iceberg** | JSON + Avro manifests | Query engines (DuckDB, Snowflake, Spark) |
| **STAC** | JSON | Cloud-native geospatial discovery |
| **ISO 19139** | XML | Government SDI, INSPIRE compliance |
| **DuckLake** | SQL | Embedded analytics |
| **Web** | JSON | Browser-based catalog UI |

**Design Decision:** Generate all outputs from a single resource definition. The resource JSON is the canonical source; outputs are derived views.

---

## Iceberg Integration

### Why Iceberg?

```
┌─────────────────────────────────────────────────────────────────────┐
│                      WITHOUT ICEBERG                                │
│                                                                     │
│       ┌─────────────────┐                                          │
│       │  Parquet File   │                                          │
│       └────────┬────────┘                                          │
│                │                                                    │
│                ├──────────────▶  DuckDB ✓                          │
│                │                                                    │
│                ├──────────────▶  Snowflake ?  (needs setup)        │
│                │                                                    │
│                └──────────────▶  Spark ?  (needs config)           │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                       WITH ICEBERG                                  │
│                                                                     │
│       ┌─────────────────┐                                          │
│       │  Parquet File   │                                          │
│       └────────┬────────┘                                          │
│                │                                                    │
│                ▼                                                    │
│       ┌─────────────────┐                                          │
│       │ Iceberg Metadata│                                          │
│       └────────┬────────┘                                          │
│                │                                                    │
│                ├──────────────▶  DuckDB ✓                          │
│                │                                                    │
│                ├──────────────▶  Snowflake ✓                       │
│                │                                                    │
│                ├──────────────▶  Spark ✓                           │
│                │                                                    │
│                ├──────────────▶  BigQuery ✓                        │
│                │                                                    │
│                └──────────────▶  Trino ✓                           │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Iceberg Metadata Structure

```
data/{namespace}/{resource}/
│
├── {resource}.parquet              ◀── Original data (unchanged!)
│
└── metadata/
    ├── v1.metadata.json            ◀── Table metadata + name-mapping
    ├── snap-1-manifest-list.avro   ◀── Snapshot manifest list
    └── snap-1-manifest.avro        ◀── Data file manifest
```

**Lightweight Iceberg:** We use `schema.name-mapping.default` property to enable column matching by name. This means:
- Original Parquet files are **never rewritten**
- No field IDs needed in Parquet metadata
- Same query compatibility with DuckDB, Spark, Trino, etc.

**Key Benefit:** Same GeoParquet file becomes queryable by ANY Iceberg-compatible engine without data modification.

---

## Metadata Model

### Three-Layer Metadata

```
┌─────────────────────────────────────────────────────────────────────┐
│                         RESOURCE METADATA                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │                      USER METADATA                            │ │
│  │                    (Manual input)                             │ │
│  │                                                               │ │
│  │   title          description          tags          license   │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │                     SOURCE METADATA                           │ │
│  │                  (Extracted from origin)                      │ │
│  │                                                               │ │
│  │   provider       fetched_at       original_fields    extent   │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │                    DERIVED METADATA                           │ │
│  │                   (Computed from data)                        │ │
│  │                                                               │ │
│  │   row_count      schema_hash      file_size_bytes       bbox  │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

| Layer | Source | When Updated |
|-------|--------|--------------|
| **User** | Manual input | On register/edit |
| **Source** | Extracted from origin | On snapshot |
| **Derived** | Computed from data | On snapshot |

---

## CLI Design

### Command Structure

```
portolan
│
├── init                         # Create catalog
├── status                       # Show catalog state
├── validate                     # Validate all resources
├── sync                         # Push to remote storage
│
├── register <type> <url>        # Register EXTERNAL resource
├── snapshot <name>              # Create CACHED snapshot
│   └── --all --namespace <ns>   # Batch all in namespace
├── materialize <name>           # Create MATERIALIZED Iceberg table
│   ├── --remote                 # Iceberg from remote data (no download)
│   └── --all --namespace <ns>   # Batch all in namespace
├── add <file>                   # Convenience: register + snapshot + materialize
│
└── catalog
    ├── add <url>                # Register upstream catalog
    ├── list                     # List registered catalogs
    ├── sync [name]              # Sync from upstream
    └── remove <name>            # Unregister catalog
```

### Example Workflow

```bash
# Vector resource (snapshot = done, Iceberg auto-created)
portolan register arcgis_featureserver "https://server/0" --name buildings
portolan snapshot buildings
# → Already materialized! Query with DuckDB immediately.

# Raster resource (needs explicit materialize for format conversion)
portolan register arcgis_imageserver "https://server/ImageServer" --name dem
portolan snapshot dem          # Downloads COG (cache only)
portolan materialize dem       # Converts to Raquet + Iceberg (expensive)

# Federated catalog
portolan catalog add "https://server/FeatureServer" --name city --type arcgis
portolan catalog sync city
portolan snapshot --all --namespace federated_city
# → Vector resources are already queryable via Iceberg!
```

```bash
# Remote GeoParquet (no download at all!)
portolan register file "s3://overturemaps-us-west-2/release/.../places.parquet" --name places
portolan materialize places --remote
# → Reads only Parquet schema (range request), creates Iceberg metadata
# → 965 MB file stays on S3, queryable via Iceberg!
```

**Design Decision:** Type-aware lifecycle - vectors get Iceberg for free (lightweight registration), rasters require explicit materialization (expensive format conversion). Remote GeoParquet files can be registered as Iceberg without any download.

---

## Key Design Decisions

### 1. Local-First Architecture

```
┌────────────────────┐     ┌────────────────────┐
│   Local Work       │     │   Remote Storage   │
│                    │     │                    │
│  ○ Edit offline    │────▶│  ○ Source of truth │
│  ○ Version control │sync │  ○ Shared access   │
│  ○ Batch changes   │     │  ○ Multi-output    │
└────────────────────┘     └────────────────────┘
```

**Rationale:** Offline capability, version control friendly, batch operations before sync, no cloud lock-in.

### 2. Type-Aware Lifecycle

```
VECTOR:  EXTERNAL ──snapshot──▶ MATERIALIZED  (1 step, Iceberg is free)
RASTER:  EXTERNAL ──snapshot──▶ CACHED ──materialize──▶ MATERIALIZED  (2 steps)
```

**Rationale:** Lightweight Iceberg (name-mapping) makes vector registration free - no reason to have a separate step. Raster format conversion remains expensive, so it stays explicit.

### 3. Format Standardization

```
Any Format ──▶ Cloud-Native ──▶ Iceberg-Ready
                (GeoParquet)     (+ metadata)
                (COG/Zarr)       (Raquet)
                (COPC)           (Pointquet)
```

**Rationale:** Industry standards with broad tool support, efficient cloud storage, progressive enhancement.

### 4. Multi-Output Generation

```
              ┌─────────────┐
              │  Resource   │
              │    JSON     │
              └──────┬──────┘
                     │
    ┌────────┬───────┼───────┬────────┐
    ▼        ▼       ▼       ▼        ▼
 Iceberg   STAC   ISO19139  Web   DuckLake
```

**Rationale:** Single source of truth, compliance with multiple standards, no metadata duplication.

### 5. Catalog Federation

```
Upstream A ─┐
            │
Upstream B ─┼──▶ Portolan ──▶ Unified Query
            │     Catalog
Upstream C ─┘
```

**Rationale:** Aggregate from multiple sources, maintain local control, selective caching.

---

## Technology Stack

```
┌─────────────────────────────────────────────────────────────────────┐
│                              CORE                                   │
│                                                                     │
│     Python 3.11+      Click CLI       PyArrow       GeoPandas      │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                           EXTRACTION                                │
│                                                                     │
│     GDAL/ogr2ogr        gpio CLI       raquet-io        httpx      │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                            STORAGE                                  │
│                                                                     │
│       Parquet           Iceberg          GCS/S3         Local      │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                             QUERY                                   │
│                                                                     │
│       DuckDB          Snowflake          Spark         BigQuery    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Dependencies

| Tool | Purpose |
|------|---------|
| `click` | CLI framework |
| `pyarrow` | Parquet/Arrow operations |
| `geopandas` | Vector data handling |
| `httpx` | HTTP client |
| `jsonschema` | Validation |
| `ogr2ogr` | WFS extraction |
| `gpio` | ArcGIS FeatureServer extraction |
| `raquet-io` | Raster to Raquet conversion |

---

## Future Roadmap

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│  Phase 1 (Complete)     Phase 2 (Current)    Phase 3 (Next)        │
│  ─────────────────      ────────────────     ──────────────        │
│                                                                     │
│  ✓ Extractors           ✓ Federation         ○ Schema Drift        │
│    - WFS                  - Catalog sources    - Change detection  │
│    - ArcGIS FS            - Batch operations   - Version tracking  │
│    - ArcGIS IS                                                     │
│    - STAC                                                          │
│    - Local files                                                   │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Phase 4 (Future)                                                  │
│  ────────────────                                                  │
│                                                                     │
│  ○ Real-time Sync       ○ Time Travel        ○ Access Control      │
│    - Webhooks             - Historical         - Fine-grained      │
│    - Scheduled refresh    - snapshots          - permissions       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Summary

### What Portolan Provides

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│   1. Unified ingestion     from heterogeneous geospatial sources   │
│                                                                     │
│   2. Cloud-native formats  for efficient storage and query         │
│                                                                     │
│   3. Multi-standard outputs for interoperability                   │
│                                                                     │
│   4. SQL-queryable catalogs via Iceberg                            │
│                                                                     │
│   5. Federated discovery   across multiple upstream catalogs       │
│                                                                     │
│   6. AI-ready metadata     with semantic descriptions              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### The Vision

```
        Any geospatial data source
                    │
                    ▼
             ┌─────────────┐
             │  Portolan   │
             └──────┬──────┘
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
   SQL Query    STAC/ISO    AI Agents
   (any engine)  Discovery   Understand
```

---

## Resources

- **Documentation:** `docs/catalog-data-model.md`
- **Test Resources:** `tests/TEST_RESOURCES.md`
- **CLI Help:** `portolan --help`
