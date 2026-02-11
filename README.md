# Portolan

**Portolan** is an open, cloud-agnostic framework for building modern spatial data infrastructures. It enables organizations to transform, publish, govern, and observe geospatial data using open standards such as GeoParquet, Raquet, and Apache Iceberg.

[![Tests](https://github.com/portolan-sdi/portolan/actions/workflows/test.yml/badge.svg)](https://github.com/portolan-sdi/portolan/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)

## Why Portolan?

| Benefit | How |
|---------|-----|
| **Scalable** | Built on cloud object storage that scales to petabytes |
| **Open** | 100% open source using open formats (GeoParquet, Raquet, Iceberg) |
| **AI-Ready** | Rich semantics via STAC, ISO 19115, and [Open Semantic Interchange](https://opensemanticinterchange.org/) |
| **Cheap** | Only pay for storage and egress—no servers to run |
| **Sovereign** | Host anywhere (any cloud, on-prem, air-gapped) |
| **Breaks the GIS silo** | Uses general analytics technology (Apache Iceberg), so DuckDB, Snowflake, BigQuery, Databricks, and other non-GIS tools just work |

## Quick Start

```bash
# Install
git clone https://github.com/portolan-sdi/portolan.git
cd portolan
uv sync

# Initialize a catalog
uv run portolan init

# Add a dataset (register + snapshot + Iceberg)
uv run portolan add data.parquet --title "My Dataset"

# Query with DuckDB
duckdb -c "SELECT * FROM iceberg_scan('.portolan/data/default/my_dataset/metadata/v1.metadata.json') LIMIT 10"
```

See [DOCUMENTATION.md](DOCUMENTATION.md) for the full user guide.

## Architecture

```
                                 ┌─────────────────────────────────┐
                                 │         Remote Storage          │
                                 │   (GCS/S3/Azure/Local)          │
                                 │                                 │
                                 │  manifest.json                  │
                                 │  resources/                     │
                                 │  data/                          │
                                 │  v1/ (Iceberg REST catalog)     │
                                 └───────────────┬─────────────────┘
                                                 │
                                                 │ sync/pull
                                                 │
┌────────────────────────────────────────────────┴────────────────────────────────────────────────┐
│                                        Local Catalog (.portolan/)                               │
│                                                                                                 │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐      │
│  │   config.json   │    │   state.json    │    │  connections    │    │    sources      │      │
│  │                 │    │                 │    │    .json        │    │     .json       │      │
│  │ - outputs       │    │ - remote_url    │    │                 │    │                 │      │
│  │   .metadata     │    │ - manifest_hash │    │ DB credentials  │    │ Federated       │      │
│  │   .data         │    └─────────────────┘    └─────────────────┘    │ catalogs        │      │
│  └─────────────────┘                                                  └─────────────────┘      │
│                                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────┐   │
│  │                              resources/{namespace}/{name}.json                          │   │
│  │                                                                                         │   │
│  │   Resource Lifecycle:  REGISTERED ──────────► READY                                     │   │
│  │                        (origin only)          (+snapshot/iceberg, queryable via SQL)     │   │
│  └─────────────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────┐   │
│  │                                    data/                                                │   │
│  │   data/raw/{ns}/{name}/             Snapshot parquet files                              │   │
│  │   data/{ns}/{name}/metadata/        Per-resource Iceberg table metadata                 │   │
│  │   data/_meta/resources/             Iceberg metadata catalog (resources as rows)        │   │
│  └─────────────────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Resource Lifecycle

Resources have two states:

| State | Condition | Description |
|-------|-----------|-------------|
| **REGISTERED** | Has `origin`, no assets | Discoverable pointer to data |
| **READY** | Has `assets.iceberg` or `assets.snapshot` | SQL-queryable via Iceberg |

Data location is orthogonal: **local** (data in catalog) or **linked** (Iceberg points to remote data).

### Output System

Outputs are split into two categories configured in `.portolan/config.json`:

```json
{
  "outputs": {
    "metadata": { "stac": true, "iso19139": false, "web": true, "iceberg": true },
    "data": { "iceberg": true, "ducklake": false }
  }
}
```

**Metadata outputs** — discovery catalogs of ALL resources (including registered-only):
- **STAC** — SpatioTemporal Asset Catalog
- **ISO 19139** — XML metadata
- **Web** — static HTML catalog browser
- **Iceberg metadata catalog** — all resources as rows in a single Iceberg table

**Data outputs** — queryable tables for READY resources with Parquet data:
- **Iceberg** — per-resource data tables + static REST catalog
- **DuckLake** — DuckDB catalog

### Supported Origin Types

| Type | Description | Extractor |
|------|-------------|-----------|
| `file` | Local file (Parquet, GeoJSON, Shapefile, etc.) | geopandas |
| `wfs` | OGC Web Feature Service | ogr2ogr |
| `arcgis_featureserver` | ArcGIS FeatureServer | gpio (geoparquet-io) |
| `arcgis_imageserver` | ArcGIS ImageServer (raster) | gpio |
| `stac` | STAC Item | httpx download |
| `postgres` | PostgreSQL/PostGIS table | geopandas + psycopg2 |
| `oracle` | Oracle Spatial table | geopandas + cx_Oracle |
| `pointcloud` | Point cloud (LAZ, LAS, COPC, E57) | DuckDB PDAL extension |
| `tiles` | PMTiles / MBTiles | tilequet-io |

### Resource Kinds

| Kind | Snapshot Format | Description |
|------|----------------|-------------|
| `vector` | GeoParquet | Vector features (points, lines, polygons) |
| `raster` | Raquet | Raster imagery and grids |
| `table` | GeoParquet | Non-spatial tabular data |
| `collection` | — | Container for multiple resources |
| `pointcloud` | Parquet | 3D point clouds (via PDAL) |
| `tiles` | Tilequet | Map tiles (PMTiles/MBTiles) |

## Project Structure

```
portolan/
├── portolan.py              # Main CLI (Click-based): add, load, refresh, sync, etc.
├── portolan_resource.py     # Resource model and lifecycle states
├── extractors.py            # Data extraction dispatch (file, WFS, ArcGIS, DB, etc.)
├── output_generators.py     # Output generation (STAC, ISO, web, Iceberg metadata/data)
├── schemas.py               # JSON Schema validation
├── catalog_state.py         # Remote storage (obstore) and sync state management
├── catalog_sources.py       # Federated catalog source tracking
├── sync_controller.py       # Sync control plane (retry, history, health)
├── namespace_utils.py       # Namespace hierarchy utilities
├── iceberg_catalog.py       # Iceberg catalog generation (re-export facade)
├── iceberg_metadata.py      # Iceberg core types + schemas
├── iceberg_rest_catalog.py  # Iceberg REST catalog endpoints
├── sdi_catalog.py           # STAC + ISO 19115 metadata generation
└── tests/                   # Test suite (288 tests)
    ├── conftest.py
    ├── test_cli.py
    ├── test_resource.py
    ├── test_schemas.py
    ├── test_output_generators.py
    ├── test_catalog_state.py
    ├── test_catalog_sources.py
    ├── test_namespace_utils.py
    └── test_sync_controller.py
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `portolan init [path]` | Initialize a new catalog |
| `portolan add <source>` | Add a single resource (smart defaults) |
| `portolan load <catalog-url>` | Bulk load from a STAC or ArcGIS catalog |
| `portolan refresh [name]` | Re-fetch resources from their origins |
| `portolan rebuild` | Rebuild all output formats from scratch |
| `portolan dataset add <file>` | Add dataset with STAC-style metadata |
| `portolan metadata show <name>` | Show resource metadata |
| `portolan metadata set <name> <key> <value>` | Set metadata on a resource |
| `portolan sync` | Push local changes to remote storage |
| `portolan pull` | Pull remote changes to local |
| `portolan clone <url>` | Clone a remote catalog |
| `portolan status` | Show catalog status |
| `portolan validate` | Validate all resources and config |
| `portolan connection add` | Manage database connections |

## Development

### Prerequisites

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- GDAL (for WFS extraction via ogr2ogr)
- Optional: `gpio` CLI from [geoparquet-io](https://github.com/geoparquet/geoparquet-io) for ArcGIS extraction

### Setup

```bash
git clone https://github.com/portolan-sdi/portolan.git
cd portolan
uv sync
```

### Running Tests

```bash
uv run pytest           # Run all tests
uv run pytest -v        # Verbose output
uv run pytest tests/test_schemas.py -v  # Specific file
```

### Adding New Extractors

1. Add the type to `ORIGIN_SCHEMA` in `schemas.py`
2. Add the type to `EXTRACTORS` set in `extractors.py`
3. Add extraction logic in `run_extractor()` in `extractors.py`
4. Add tests

### Key Design Decisions

1. **Local-first**: All operations work locally first, then sync to remote
2. **Git-like workflow**: `sync` and `pull` with manifest-based change tracking
3. **Schema validation**: JSON Schema validation on all data models
4. **Two lifecycle states**: REGISTERED (discoverable) and READY (queryable)
5. **Layered metadata**: User overrides > source metadata > derived metadata
6. **Static catalog**: Generates static Iceberg REST catalog (no server needed)
7. **Outputs split**: Metadata outputs (discovery) vs data outputs (queryable tables)

## Remote Storage

Portolan uses [obstore](https://github.com/developmentseed/obstore) for remote storage:

| Backend | URL Scheme |
|---------|-----------|
| AWS S3 | `s3://bucket/path` |
| Google Cloud Storage | `gs://bucket/path` |
| Azure Blob Storage | `az://container/path` |
| S3-compatible (R2, MinIO, OVH, Wasabi) | `s3://bucket/path` + `endpoint_url` option |
| Local filesystem | `file:///local/path` |

## Dependencies

Core:
- `click` — CLI framework
- `pyarrow` — Parquet I/O and Arrow tables
- `geopandas` — Geospatial data manipulation
- `jsonschema` — Schema validation
- `httpx` — HTTP client
- `obstore` — Cloud object storage (S3, GCS, Azure)

Optional:
- `psycopg2-binary` — PostgreSQL support
- `cx_Oracle` — Oracle support

## Related Projects

- [GeoParquet](https://geoparquet.org/) — Cloud-native vector format
- [Raquet](https://github.com/geoparquet/raquet) — Cloud-native raster format
- [Apache Iceberg](https://iceberg.apache.org/) — Table format for analytics
- [STAC](https://stacspec.org/) — SpatioTemporal Asset Catalog
- [DuckDB](https://duckdb.org/) — Analytical database with Iceberg support

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes with tests
4. Run the test suite (`uv run pytest`)
5. Submit a pull request

## License

Apache 2.0 — See [LICENSE](LICENSE) for details.

## Links

- [Documentation](DOCUMENTATION.md)
- [Data Model](docs/catalog-data-model.md)
- [GitHub Issues](https://github.com/portolan-sdi/portolan/issues)
