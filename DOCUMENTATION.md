# Portolan User Documentation

This guide covers everything you need to know to use Portolan for managing your geospatial data infrastructure.

## Table of Contents

1. [Installation](#installation)
2. [Getting Started](#getting-started)
3. [Core Concepts](#core-concepts)
4. [Workflow Guide](#workflow-guide)
5. [CLI Reference](#cli-reference)
6. [Working with Data Sources](#working-with-data-sources)
7. [Querying Data](#querying-data)
8. [Remote Storage](#remote-storage)
9. [Automation & Orchestration](#automation--orchestration)
10. [Troubleshooting](#troubleshooting)

---

## Installation

### Prerequisites

- Python 3.10 or later
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- Optional: GDAL (for WFS extraction)
- Optional: [geoparquet-io](https://github.com/geoparquet/geoparquet-io) (for ArcGIS extraction)
- Optional: DuckDB PDAL extension (for point cloud LAZ/LAS extraction)

### Install from Source

```bash
# Clone the repository
git clone https://github.com/portolan-sdi/portolan.git
cd portolan

# Install dependencies with uv (recommended)
uv sync

# Verify installation
uv run portolan --help
```

### Install with pip

```bash
pip install portolan
```

---

## Getting Started

### Initialize a Catalog

Create a new Portolan catalog in your project directory:

```bash
portolan init
```

This creates a `.portolan` directory with the catalog structure:

```
.portolan/
├── config.json       # Catalog configuration
├── state.json        # Sync state
├── resources/        # Resource definitions
│   └── default/      # Default namespace
├── data/             # Data files (snapshots, Iceberg metadata)
└── v1/               # Iceberg REST catalog structure
```

### Add Your First Dataset

The quickest way to add data is the `add` command, which registers and snapshots in one step:

```bash
# Add a local file
portolan add mydata.parquet --title "My Dataset"

# Add to the public namespace
portolan add countries.geojson --public --title "Country Boundaries"
```

### Check Status

```bash
portolan status
```

### Query with DuckDB

Once snapshotted, your data is queryable as an Iceberg table:

```bash
duckdb -c "
LOAD iceberg;
SELECT * FROM iceberg_scan('.portolan/data/default/mydata/metadata/v1.metadata.json') LIMIT 10;
"
```

---

## Core Concepts

### Resource Lifecycle

Every resource in Portolan has a lifecycle state:

```
REGISTERED ──────► READY
     │                │
     ▼                ▼
Pointer to      Iceberg table
data source     (queryable via SQL)
```

| State | What it means | How to get there |
|-------|---------------|------------------|
| **REGISTERED** | Discoverable pointer to data, not SQL-queryable | `portolan add --catalog-only` |
| **READY** | Has Iceberg table, queryable via DuckDB/BigQuery/etc. | `portolan add` (default) |

Data location is orthogonal to state:
- **local** — data downloaded and stored in the catalog
- **linked** — Iceberg points to remote data (no local copy)

### Namespaces

Resources are organized into namespaces:

```
.portolan/resources/
├── default/          # Default namespace
│   └── cities.json
├── public/           # Public datasets
│   └── countries.json
└── imagery/          # Custom namespace
    └── sentinel.json
```

Use `--namespace` (or `-ns`) to specify a namespace:

```bash
portolan add /path/to/data.parquet --namespace imagery --name satellite
```

### Metadata Layers

Portolan uses layered metadata with clear precedence:

1. **User metadata** (highest priority) - Explicitly set by you
2. **Source metadata** - Fetched from the origin (STAC, ArcGIS, etc.)
3. **Derived metadata** - Computed from the data (row count, bbox, schema hash)

```json
{
  "metadata": {
    "user": {
      "title": "My Custom Title",
      "description": "My description"
    },
    "source": {
      "provider": "stac",
      "data": {"title": "Original Title"}
    },
    "derived": {
      "row_count": 1500,
      "bbox": [-10, 35, 5, 45],
      "schema_hash": "abc123"
    }
  }
}
```

---

## Workflow Guide

### Workflow 1: Add Local Files

For local files you want to manage in your catalog:

```bash
# Add a local file (auto-detects type, downloads + creates Iceberg)
portolan add data.parquet --title "My Data"

# Add a GeoJSON file (auto-converts to GeoParquet)
portolan add boundaries.geojson --public --name boundaries
```

### Workflow 2: Add Remote Cloud-Native Data

For remote Parquet/COPC files already in cloud storage:

```bash
# Remote Parquet — creates Iceberg without downloading
portolan add s3://bucket/data.parquet --name remote_data

# Force local download for SLA/offline access
portolan add s3://bucket/data.parquet --name local_copy --cache-data
```

### Workflow 3: Connect to External Services

For remote data sources like WFS, ArcGIS, or databases:

```bash
# ArcGIS FeatureServer (auto-detected from URL)
portolan add https://services.arcgis.com/.../FeatureServer/0 \
  --name boundaries --title "Administrative Boundaries"

# WFS layer
portolan add https://example.com/wfs --type wfs --layer boundaries --name boundaries
```

### Workflow 4: Database Extraction

For PostgreSQL or Oracle databases:

```bash
# First, store your connection securely
portolan connection add mydb "postgresql://user:pass@host:5432/dbname"

# Add the table (extracts to GeoParquet + creates Iceberg)
portolan add "public.buildings" --type postgres --connection-ref mydb --name buildings
```

### Workflow 5: Discover from Catalogs

Discover and register resources from STAC or ArcGIS catalogs:

```bash
# Load from a STAC catalog
portolan load https://earth-search.aws.element84.com/v1 \
  --max-items 50 --collections sentinel-2-l2a

# Load from an ArcGIS server
portolan load https://services.arcgis.com/.../rest/services
```

### Workflow 6: Re-fetch Data

Re-fetch data from the original source. Portolan tracks a source fingerprint and skips unchanged sources automatically:

```bash
# Refresh a single resource (skips if source unchanged)
portolan refresh cities

# Force refresh even if source hasn't changed
portolan refresh cities --force

# Refresh all resources in a namespace
portolan refresh --all --namespace imagery
```

**Change detection by source type:**

| Source type | Detection method | Behavior |
|---|---|---|
| Local file | mtime + file size | Skips if unchanged |
| Remote Parquet (s3://, gs://) | file size + ETag/Last-Modified | Skips if unchanged |
| WFS, ArcGIS, Database | No cheap detection available | Always re-extracts |

Use `--force` to bypass change detection and always re-extract.

### Workflow 7: Sync to Remote

Push your local catalog to cloud storage:

```bash
# Configure remote
# (edit .portolan/state.json to set remote_url)

# Sync local → remote
portolan sync

# Pull remote → local
portolan pull
```

**Important:** `refresh` and `sync` are different operations:

| Command | Direction | What it does |
|---|---|---|
| `portolan refresh` | External origins → local catalog | Re-fetches data from original sources (WFS, ArcGIS, databases, files) |
| `portolan sync` | Local catalog → remote storage | Pushes catalog and data to cloud storage (GCS/S3/Azure) |

A typical update cycle: `portolan refresh --all` then `portolan sync`.

---

## CLI Reference

### Initialization

```bash
portolan init [PATH] [--remote URL]
```

Initialize a new catalog. PATH defaults to current directory.

### Add Resource

```bash
portolan add <SOURCE> [OPTIONS]
```

Add a resource to the catalog. Smart defaults based on source type — does the right thing automatically.

**Options:**
- `--type` - Source type (auto-detected if omitted)
- `--name, -n` - Resource name (default: derived from source)
- `--namespace, -ns` - Namespace (default: "default")
- `--layer, -l` - Layer name for multi-layer sources or database tables
- `--connection-ref` - Connection reference for database sources
- `--title` - Human-readable title
- `--description` - Description
- `--public` - Use "public" namespace
- `--catalog-only` - Just register for discovery, no processing
- `--cache-data` - Force local download for remote cloud-native formats (SLA/offline)
- `--bbox` - Bounding box filter: xmin,ymin,xmax,ymax (WGS84)

**Smart defaults by source type:**

| Source | Default action |
|--------|---------------|
| Local Parquet/GeoParquet | Copy + Iceberg |
| Local Shapefile/GeoJSON | Convert to GeoParquet + Iceberg |
| Remote Parquet (s3://, gs://) | Remote Iceberg (no download) |
| Remote COPC | Remote Iceberg (no download) |
| ArcGIS FeatureServer | Download + GeoParquet + Iceberg |
| WFS endpoint | Download + GeoParquet + Iceberg |
| Database table | Extract + Iceberg |
| Local LAZ/LAS | Convert to Parquet + Iceberg |
| Unknown format | Register for discovery only |

**Examples:**

```bash
# Local file
portolan add cities.parquet --name cities --public

# Remote cloud-native (no download)
portolan add s3://bucket/data.parquet --name overture

# ArcGIS FeatureServer
portolan add https://services.arcgis.com/.../FeatureServer/0 --name parcels

# PostgreSQL table
portolan add "public.buildings" --type postgres --connection-ref mydb --name buildings

# Point cloud
portolan add scan.laz --type pointcloud --name lidar

# Discovery-only (no processing)
portolan add some.pmtiles --catalog-only --name tiles
```

### Refresh Resource

```bash
portolan refresh [NAME] [OPTIONS]
```

Re-fetch data from the original source, detect schema drift, and re-create Iceberg metadata.

Portolan stores a source fingerprint when data is first added. On refresh, it compares the current source against the stored fingerprint and skips re-extraction if unchanged. Use `--force` to bypass this check.

**Options:**
- `--namespace, -ns` - Namespace (default: "default")
- `--all` - Refresh all resources in namespace
- `--force` - Force refresh even if source hasn't changed
- `--bbox` - Bounding box filter
- `--verbose, -v` - Verbose output

**Change Detection:**

For local files, Portolan checks the modification time and file size. For remote files, it checks file size and ETag/Last-Modified headers. API sources (WFS, ArcGIS, databases) don't support cheap change detection and are always re-extracted.

**Schema Drift Detection:**

If the schema changes between refreshes, you'll see a warning and the change is tracked in the resource metadata (`metadata.derived.previous_schema_hash`).

### Load from Catalog

```bash
portolan load <URL> [OPTIONS]
```

Discover and register resources from an external catalog or service.

**Options:**
- `--type` - Catalog type: `stac`, `arcgis-server` (auto-detected if omitted)
- `--namespace, -ns` - Namespace (default: derived from catalog type)
- `--max-items` - Maximum items to load (default: 100, 0 = all)
- `--collections, -c` - Filter to specific collections (STAC only, repeatable)
- `--dry-run` - Preview what would be added
- `--verbose, -v` - Verbose output

**Examples:**

```bash
# STAC catalog
portolan load https://earth-search.aws.element84.com/v1 --max-items 50

# ArcGIS server
portolan load https://services.arcgis.com/.../rest/services

# Preview
portolan load https://example.com/stac --dry-run
```

### Connection Management

```bash
# Add a database connection
portolan connection add <NAME> <CONNECTION_STRING> [OPTIONS]

# List connections
portolan connection list [--verbose]

# Remove a connection
portolan connection remove <NAME> [--force]
```

**Options for add:**
- `--geometry-column, -g` - Geometry column name (default: "geom")

**Examples:**

```bash
# PostgreSQL
portolan connection add mydb "postgresql://user:pass@localhost:5432/gisdb"

# Oracle
portolan connection add oracledb "oracle://user:pass@host:1521/service" -g GEOMETRY

# List with details
portolan connection list -v
```

### Dataset Management

```bash
# List all resources
portolan dataset list [--namespace NS] [--verbose] [--json]

# Remove a resource
portolan dataset remove <NAMESPACE/NAME> [--force]
```

### Sync & Status

```bash
# Show catalog status
portolan status [--verbose]

# Sync to remote
portolan sync [--dry-run] [--force-with-lease] [--verbose]

# Pull from remote
portolan pull [--force] [--verbose]

# Clone a remote catalog
portolan clone <URL> [PATH] [--verbose]
```

### Validation

```bash
# Validate entire catalog
portolan validate [--verbose]

# Validate specific resource
portolan validate default/cities

# Validate only resources
portolan validate --resources-only
```

### Rebuild

```bash
portolan rebuild [OPTIONS]
```

Rebuild catalog and all enabled outputs.

**Options:**
- `--base-url` - Base URL for hosted catalog
- `--outputs-only` - Only rebuild STAC/ISO outputs
- `--verbose, -v` - Verbose output

---

## Working with Data Sources

### Local Files

Supported formats: GeoParquet, Parquet, GeoJSON, Shapefile, GeoPackage, and anything geopandas can read.

```bash
portolan add /path/to/data.geojson --name mydata  # Converts to GeoParquet + Iceberg
```

### WFS (Web Feature Service)

Requires GDAL/ogr2ogr to be installed.

```bash
portolan add "https://example.com/wfs" --type wfs --layer "myLayer" --name boundaries
```

### ArcGIS FeatureServer

Requires [geoparquet-io](https://github.com/geoparquet/geoparquet-io) CLI (`gpio`).

```bash
portolan add "https://services.arcgis.com/.../FeatureServer/0" --name parcels
```

### ArcGIS ImageServer (Raster)

```bash
portolan add "https://services.arcgis.com/.../ImageServer" --name elevation
# Creates Raquet format + Iceberg
```

### STAC Items

```bash
portolan add "https://earth-search.aws.element84.com/v1/..." --type stac --name sentinel_scene
```

### PostgreSQL/PostGIS

```bash
# Store connection
portolan connection add gisdb "postgresql://user:pass@localhost:5432/gis"

# Add table
portolan add "public.buildings" --type postgres --connection-ref gisdb --name buildings
```

### Oracle Spatial

```bash
# Store connection
portolan connection add oradb "oracle://user:pass@host:1521/service" --geometry-column SHAPE

# Add table
portolan add "ADMIN.PARCELS" --type oracle --connection-ref oradb --name parcels
```

### Point Cloud / LiDAR (LAZ, LAS)

Requires the DuckDB PDAL extension, which reads 119+ point cloud formats via [PDAL](https://pdal.io/).

```bash
# Install the extension (one-time)
duckdb -c "INSTALL pdal FROM community;"

# Add a LAZ/LAS file (converts to Parquet + Iceberg in one step)
portolan add /path/to/scan.laz --type pointcloud --name autzen_lidar \
  --namespace lidar --title "Autzen Stadium LiDAR"
```

The point cloud is stored as a flat Parquet table with columns like X, Y, Z, Intensity, Classification, ReturnNumber, Red, Green, Blue, etc. All standard numeric types — queryable in DuckDB, BigQuery, Snowflake, and any Iceberg-compatible engine.

```sql
-- Query point cloud via Iceberg
LOAD iceberg;
SELECT count(*) as points, min(Z) as min_elevation, max(Z) as max_elevation
FROM iceberg_scan('.portolan/data/lidar/autzen_lidar/metadata/v1.metadata.json');

-- Filter by classification (2 = ground, 6 = building)
SELECT X, Y, Z FROM iceberg_scan('...')
WHERE Classification = 6;
```

Supported input formats include LAS, LAZ, COPC, E57, PLY, PCD, and any format supported by PDAL. Remote files (S3, HTTP) are also supported.

---

## Loading from External Catalogs

Portolan can discover and register resources from external STAC catalogs and ArcGIS servers.

### STAC Catalogs

```bash
# Discover items from a STAC catalog
portolan load https://earth-search.aws.element84.com/v1

# Filter to specific collections
portolan load https://earth-search.aws.element84.com/v1 \
  -c sentinel-2-l2a --max-items 50

# Preview what would be loaded
portolan load https://example.com/stac --dry-run
```

### ArcGIS Servers

```bash
# Discover all FeatureServers and ImageServers
portolan load https://services.arcgis.com/.../rest/services

# Preview first
portolan load https://services.arcgis.com/.../rest/services --dry-run
```

Resources loaded from catalogs start in **REGISTERED** state (discoverable but not SQL-queryable). Use `portolan refresh <name>` to download and process individual resources.

---

## Querying Data

### DuckDB with Iceberg

```sql
LOAD iceberg;

-- Direct scan
SELECT * FROM iceberg_scan(
  '.portolan/data/default/cities/metadata/v1.metadata.json'
) LIMIT 10;

-- Attach as catalog (if using REST catalog endpoint)
ATTACH '' AS catalog (
    TYPE iceberg,
    ENDPOINT 'https://storage.googleapis.com/my-bucket/portolan',
    AUTHORIZATION_TYPE 'none'
);

SELECT * FROM catalog.portolan.cities LIMIT 10;
```

### DuckDB with Spatial

```sql
LOAD spatial;

-- Spatial queries on GeoParquet
SELECT name, population
FROM read_parquet('.portolan/data/raw/default/cities/cities.parquet')
WHERE ST_Within(
  geometry,
  ST_GeomFromText('POLYGON((-4 39, -3 39, -3 41, -4 41, -4 39))')
);
```

### BigQuery

```sql
-- Create external table pointing to Iceberg metadata
-- bq mk --table --external_table_definition=ICEBERG=gs://bucket/portolan/data/cities/metadata/v1.metadata.json project.dataset.cities

SELECT * FROM `project.dataset.cities` LIMIT 10;
```

---

## Remote Storage

### Supported Backends

| Backend | URL Format | Example |
|---------|------------|---------|
| AWS S3 | `s3://bucket/path` | `s3://my-data/portolan` |
| Google Cloud | `gs://bucket/path` | `gs://my-bucket/portolan` |
| Azure Blob | `az://container/path` | `az://mycontainer/portolan` |
| Local filesystem | `file:///path` | `file:///var/data/portolan` |

### Configure Remote

Edit `.portolan/state.json`:

```json
{
  "remote_url": "gs://my-bucket/portolan",
  "base_manifest_hash": null
}
```

### Sync Workflow

```bash
# Check status
portolan status

# Sync local changes to remote
portolan sync

# Preview what would be synced
portolan sync --dry-run

# Pull changes from remote
portolan pull

# Force pull (discards local changes)
portolan pull --force
```

### Clone Existing Catalog

```bash
portolan clone gs://public-catalog/portolan ./local-copy
```

---

## Automation & Orchestration

Portolan is designed as a CLI-first tool, making it easy to automate with external schedulers. Rather than building an internal scheduling engine, Portolan provides the building blocks for external orchestration.

### Understanding refresh vs sync

These are the two key operations for keeping data current:

```
External origins          Local catalog          Remote storage
(WFS, ArcGIS, DB)        (.portolan/)           (GCS/S3/Azure)
       │                       │                       │
       │   portolan refresh    │    portolan sync      │
       │ ────────────────────► │ ────────────────────► │
       │   (re-fetch data)     │   (push catalog)      │
       │                       │                       │
       │                       │    portolan pull       │
       │                       │ ◄──────────────────── │
       │                       │   (pull catalog)      │
```

- **`refresh`** pulls fresh data FROM external origins INTO your local catalog
- **`sync`** pushes your local catalog TO remote storage for sharing/querying
- **`pull`** pulls a shared catalog FROM remote storage to your local machine

### Automated update pipeline

The typical automation pattern is:

```bash
#!/bin/bash
# update-catalog.sh — run on a schedule

# 1. Re-fetch all data from origins (skips unchanged sources)
portolan refresh --all

# 2. Push updated catalog to remote storage
portolan sync

# 3. (Optional) Check sync health
portolan control health
```

### External orchestration examples

**Cron (simplest):**

```cron
# Refresh and sync every 6 hours
0 */6 * * * cd /path/to/project && portolan refresh --all && portolan sync
```

**GitHub Actions:**

```yaml
name: Update Catalog
on:
  schedule:
    - cron: '0 */6 * * *'  # Every 6 hours
  workflow_dispatch:         # Manual trigger

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync
      - run: uv run portolan refresh --all
      - run: uv run portolan sync
```

**Google Cloud Functions / AWS Lambda:**

```python
def update_catalog(event, context):
    """Cloud function triggered on a schedule."""
    import subprocess
    subprocess.run(["portolan", "refresh", "--all"], check=True)
    subprocess.run(["portolan", "sync"], check=True)
```

### Control plane

Portolan includes a lightweight control plane that logs every sync operation to a local DuckDB database (`.portolan/control.duckdb`). This provides:

- **Event history** — every refresh, sync, and pull is logged with timestamps and outcomes
- **Retry with backoff** — failed operations are retried automatically (configurable)
- **Health monitoring** — check success/failure rates over time

```bash
# View sync history
portolan control history

# Check health summary (last 24 hours)
portolan control health

# View history for a specific operation type
portolan control history --type snapshot
```

### Configuring retry policy

Add a `sync_policy` section to `.portolan/config.json`:

```json
{
  "sync_policy": {
    "max_retries": 3,
    "retry_backoff": "exponential",
    "retry_delay_seconds": 2.0,
    "timeout_seconds": 300,
    "on_failure": "log"
  }
}
```

| Setting | Options | Default |
|---|---|---|
| `max_retries` | 0-10 | 3 |
| `retry_backoff` | `exponential`, `linear`, `fixed` | `exponential` |
| `retry_delay_seconds` | seconds | 2.0 |
| `on_failure` | `log`, `webhook` | `log` |
| `webhook_url` | URL (when `on_failure: webhook`) | — |

---

## Troubleshooting

### "Resource validation failed"

Check the resource JSON against the schema:

```bash
portolan validate default/myresource
```

Common issues:
- `name` must be lowercase with underscores only
- `kind` must be one of: `vector`, `raster`, `table`, `collection`
- `origin.type` must be a valid type

### "Schema drift detected"

The source data schema changed. Options:

1. Accept the new schema:
   ```bash
   portolan refresh mydata --force
   ```

2. Investigate the change by comparing the schema hashes in the resource JSON.

### "Connection not found"

Add the connection first:

```bash
portolan connection add mydb "postgresql://..."
```

### "gpio command not found"

Install geoparquet-io:

```bash
pip install geoparquet-io
```

### "ogr2ogr not found"

Install GDAL:

```bash
# macOS
brew install gdal

# Ubuntu
apt install gdal-bin

# Windows
# Download from https://gdal.org/download.html
```

### Sync fails with "Remote has changes you don't have"

Your local catalog is behind the remote:

```bash
# Get remote changes first
portolan pull

# Then sync your changes
portolan sync
```

Or force push (careful - may overwrite remote changes):

```bash
portolan sync --force-with-lease
```

---

## Best Practices

### Organizing Resources

- Use meaningful namespaces (`imagery`, `boundaries`, `analytics`)
- Use descriptive names (`spanish_cities` not `data1`)
- Add titles and descriptions for discoverability

### Metadata

- Set user metadata for important datasets
- Use tags for categorization
- Include license and attribution

### Sync Workflow

- Commit changes to git before syncing
- Use `--dry-run` to preview sync operations
- Pull before pushing if collaborating

### Performance

- For large datasets, use partitioned Parquet files
- Materialize datasets you query frequently
- Use `--force` sparingly (re-downloads/re-processes data)

---

## Getting Help

- **GitHub Issues**: [portolan-sdi/portolan/issues](https://github.com/portolan-sdi/portolan/issues)
- **Documentation**: This file and `docs/` directory
- **CLI Help**: `portolan --help` or `portolan <command> --help`
