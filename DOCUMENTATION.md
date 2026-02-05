# Portolan User Documentation

This guide covers everything you need to know to use Portolan for managing your geospatial data infrastructure.

## Table of Contents

1. [Installation](#installation)
2. [Getting Started](#getting-started)
3. [Core Concepts](#core-concepts)
4. [Workflow Guide](#workflow-guide)
5. [CLI Reference](#cli-reference)
6. [Working with Data Sources](#working-with-data-sources)
7. [Catalog Federation](#catalog-federation)
8. [Querying Data](#querying-data)
9. [Remote Storage](#remote-storage)
10. [Troubleshooting](#troubleshooting)

---

## Installation

### Prerequisites

- Python 3.10 or later
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- Optional: GDAL (for WFS extraction)
- Optional: [geoparquet-io](https://github.com/geoparquet/geoparquet-io) (for ArcGIS extraction)

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

The quickest way to add data is the `add` command, which registers, snapshots, and materializes in one step:

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

Once materialized, your data is queryable as an Iceberg table:

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
EXTERNAL ──────► CACHED ──────► MATERIALIZED
   │                │                │
   │                │                │
   ▼                ▼                ▼
Pointer to      Downloaded       Iceberg table
remote data     as GeoParquet    with metadata
```

| State | What it means | How to get there |
|-------|---------------|------------------|
| **EXTERNAL** | Only a pointer to the data source | `portolan register` |
| **CACHED** | Data downloaded to local GeoParquet | `portolan snapshot` |
| **MATERIALIZED** | Iceberg table wrapping the snapshot | `portolan materialize` |

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
portolan register file /path/to/data.parquet --namespace imagery --name satellite
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
# Quick add (register + snapshot + materialize)
portolan add data.parquet --title "My Data"

# Or step by step:
portolan register file /path/to/data.parquet --name mydata
portolan snapshot mydata
portolan materialize mydata
```

### Workflow 2: Connect to External Services

For remote data sources like WFS, ArcGIS, or databases:

```bash
# Register an ArcGIS FeatureServer
portolan register arcgis_featureserver https://services.arcgis.com/.../0 \
  --name boundaries \
  --title "Administrative Boundaries"

# Download as GeoParquet
portolan snapshot boundaries

# Make it queryable via Iceberg
portolan materialize boundaries
```

### Workflow 3: Database Extraction

For PostgreSQL or Oracle databases:

```bash
# First, store your connection securely
portolan connection add mydb "postgresql://user:pass@host:5432/dbname"

# Register the table
portolan register postgres "public.buildings" \
  --connection-ref mydb \
  --name buildings

# Extract and materialize
portolan snapshot buildings
portolan materialize buildings
```

### Workflow 4: STAC Import

Import from a STAC catalog:

```bash
# Import up to 50 items from a STAC catalog
portolan import stac https://earth-search.aws.element84.com/v1 \
  --max-items 50 \
  --collections sentinel-2-l2a
```

### Workflow 5: Sync to Remote

Push your local catalog to cloud storage:

```bash
# Configure remote
# (edit .portolan/state.json to set remote_url)

# Sync
portolan sync

# Pull changes from remote
portolan pull
```

---

## CLI Reference

### Initialization

```bash
portolan init [PATH] [--remote URL]
```

Initialize a new catalog. PATH defaults to current directory.

### Resource Registration

```bash
portolan register <TYPE> <URL> [OPTIONS]
```

Register an external resource (creates EXTERNAL state).

**Types:** `file`, `wfs`, `arcgis_featureserver`, `arcgis_imageserver`, `stac`, `postgres`, `oracle`

**Options:**
- `--name, -n` - Resource name (default: derived from URL)
- `--namespace, -ns` - Namespace (default: "default")
- `--layer, -l` - Layer name for multi-layer sources
- `--connection-ref` - Connection reference for databases
- `--title` - Human-readable title
- `--description` - Description

**Examples:**

```bash
# Local file
portolan register file /data/cities.parquet --name cities

# ArcGIS FeatureServer
portolan register arcgis_featureserver https://services.arcgis.com/.../0 --name parcels

# PostgreSQL table
portolan register postgres "public.buildings" --connection-ref mydb --name buildings

# WFS layer
portolan register wfs https://example.com/wfs --layer boundaries --name boundaries
```

### Snapshot

```bash
portolan snapshot <NAME> [OPTIONS]
```

Download/extract data to local GeoParquet (EXTERNAL → CACHED).

**Options:**
- `--namespace, -ns` - Namespace (default: "default")
- `--force, -f` - Re-snapshot even if already cached
- `--verbose, -v` - Verbose output

**Schema Drift Detection:**

If the schema changes between snapshots, you'll see a warning:

```
⚠️  Schema drift detected for cities
  Previous schema hash: abc123
  New schema hash:      def456

Use --force to accept the new schema.
```

### Materialize

```bash
portolan materialize <NAME> [OPTIONS]
```

Create Iceberg table from snapshot (CACHED → MATERIALIZED).

**Options:**
- `--namespace, -ns` - Namespace (default: "default")
- `--force, -f` - Re-materialize even if already done
- `--verbose, -v` - Verbose output

### Add (Convenience)

```bash
portolan add <FILE> [OPTIONS]
```

Register + snapshot + materialize in one command.

**Options:**
- `--name, -n` - Resource name
- `--namespace, -ns` - Namespace
- `--public` - Use "public" namespace
- `--title` - Title
- `--description` - Description

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

### Catalog Federation

```bash
# Register an upstream catalog
portolan catalog add <URL> [OPTIONS]

# List registered catalogs
portolan catalog list [--verbose]

# Sync from upstream
portolan catalog sync [NAME] [OPTIONS]

# Remove a catalog
portolan catalog remove <NAME> [--force]
```

**Options for add:**
- `--name, -n` - Catalog name
- `--type` - Catalog type (`stac`, `arcgis`, `wfs`, `portolan`)
- `--collections, -c` - Filter to specific collections (repeatable)

**Options for sync:**
- `--max-items` - Maximum items to sync (default: 100)
- `--dry-run` - Preview changes without saving

**Examples:**

```bash
# Add a STAC catalog
portolan catalog add https://earth-search.aws.element84.com/v1 --name earth-search

# Filter to specific collections
portolan catalog add https://example.com/stac -c sentinel-2-l2a -c landsat-8

# Sync
portolan catalog sync earth-search --max-items 50

# Preview what would be synced
portolan catalog sync --dry-run
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

### Import

```bash
portolan import stac <URL> [OPTIONS]
```

Import items from a STAC catalog.

**Options:**
- `--namespace, -n` - Namespace for imported items (default: "stac")
- `--max-items` - Maximum items to import (default: 100, 0 = all)
- `--collections, -c` - Filter to specific collections (repeatable)
- `--dry-run` - Preview without saving
- `--verbose, -v` - Verbose output

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
portolan register file /path/to/data.geojson --name mydata
portolan snapshot mydata  # Converts to GeoParquet
```

### WFS (Web Feature Service)

Requires GDAL/ogr2ogr to be installed.

```bash
portolan register wfs "https://example.com/wfs" \
  --layer "myLayer" \
  --name boundaries

portolan snapshot boundaries
```

### ArcGIS FeatureServer

Requires [geoparquet-io](https://github.com/geoparquet/geoparquet-io) CLI (`gpio`).

```bash
portolan register arcgis_featureserver \
  "https://services.arcgis.com/xxx/ArcGIS/rest/services/MyService/FeatureServer/0" \
  --name parcels

portolan snapshot parcels
```

### ArcGIS ImageServer (Raster)

```bash
portolan register arcgis_imageserver \
  "https://services.arcgis.com/xxx/ArcGIS/rest/services/Elevation/ImageServer" \
  --name elevation

portolan snapshot elevation  # Creates Raquet format
```

### STAC Items

```bash
portolan register stac \
  "https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a/items/S2A_..." \
  --name sentinel_scene

portolan snapshot sentinel_scene  # Downloads primary asset
```

### PostgreSQL/PostGIS

```bash
# Store connection
portolan connection add gisdb "postgresql://user:pass@localhost:5432/gis"

# Register table
portolan register postgres "public.buildings" \
  --connection-ref gisdb \
  --name buildings

portolan snapshot buildings
```

### Oracle Spatial

```bash
# Store connection
portolan connection add oradb "oracle://user:pass@host:1521/service" \
  --geometry-column SHAPE

# Register table
portolan register oracle "ADMIN.PARCELS" \
  --connection-ref oradb \
  --name parcels

portolan snapshot parcels
```

---

## Catalog Federation

Portolan can track and sync with upstream catalogs like STAC, keeping your local catalog up to date.

### Register Upstream Catalogs

```bash
# STAC catalog
portolan catalog add https://earth-search.aws.element84.com/v1 \
  --name earth-search

# With collection filter
portolan catalog add https://planetarycomputer.microsoft.com/api/stac/v1 \
  --name planetary-computer \
  --collections sentinel-2-l2a landsat-c2-l2
```

### Sync Updates

```bash
# Sync all catalogs
portolan catalog sync

# Sync specific catalog
portolan catalog sync earth-search

# Preview changes
portolan catalog sync --dry-run

# Limit items
portolan catalog sync earth-search --max-items 50
```

### How Sync Works

1. Fetches current state from upstream catalog
2. Computes hash of items to detect changes
3. Compares with last sync hash
4. For new/changed items:
   - Creates resource entry with upstream reference
   - Preserves source metadata
5. Updates sync state with new hash

Synced resources have an `upstream` field tracking their origin:

```json
{
  "upstream": {
    "catalog": "earth-search",
    "type": "stac",
    "id": "S2A_..."
  }
}
```

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
   portolan snapshot mydata --force
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
