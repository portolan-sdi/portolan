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

# Add a dataset (register + snapshot)
uv run portolan add data.parquet --public --title "My Dataset"

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
│  │ - remotes       │    │ - manifest_hash │    │ DB credentials  │    │ Federated       │      │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘    │ catalogs        │      │
│                                                                        └─────────────────┘      │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────┐   │
│  │                              resources/{namespace}/{name}.json                          │   │
│  │                                                                                         │   │
│  │   Resource Lifecycle:  REGISTERED ──────────► READY                                     │   │
│  │                        (origin only)          (+iceberg, queryable via SQL)              │   │
│  └─────────────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────┐   │
│  │                                    data/                                                │   │
│  │   data/raw/{ns}/{name}/        Snapshot parquet files                                   │   │
│  │   data/{ns}/{name}/metadata/   Iceberg table metadata                                   │   │
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

## Project Structure

```
portolan/
├── portolan.py            # Main CLI (Click-based): add, load, refresh, sync, etc.
├── portolan_resource.py   # Resource model and lifecycle states
├── extractors.py          # Data extraction dispatch (file, WFS, ArcGIS, DB, etc.)
├── catalog_state.py       # Sync state management
├── iceberg_catalog.py     # Iceberg catalog generation (facade)
├── iceberg_metadata.py    # Iceberg core types + schemas
├── iceberg_rest_catalog.py # Iceberg REST catalog endpoints
├── sdi_catalog.py         # STAC + ISO metadata generation
├── schemas.py             # JSON Schema validation
├── output_generators.py   # STAC/ISO output generation
├── web/                   # Browser-based catalog viewer
│   └── index.html
├── docs/                  # Additional documentation
│   ├── catalog-data-model.md
│   └── demo-catalog.md
└── tests/                 # Test suite
    ├── test_cli.py
    ├── test_resource.py
    ├── test_schemas.py
    └── test_catalog_sources.py
```

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
# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run specific test file
uv run pytest tests/test_resource.py -v

# Run with coverage
uv run pytest --cov=. --cov-report=html
```

### Code Quality

```bash
# Format code
uv run ruff format .

# Lint
uv run ruff check .

# Type checking (optional)
uv run mypy portolan.py resource.py
```

### Adding New Extractors

To add a new origin type:

1. Add the type to `ORIGIN_SCHEMA` in `schemas.py`
2. Add the type to `EXTRACTORS` set in `extractors.py`
3. Add extraction logic in `run_extractor()` in `extractors.py`
4. Add tests in `tests/test_cli.py`

Example extraction branch in `extractors.py`:

```python
elif resource.origin.type == "my_new_type":
    # Your extraction logic here
    # Output should be a GeoParquet file at output_path
    pass
```

### Key Design Decisions

1. **Local-first**: All operations work locally first, then sync to remote
2. **Git-like workflow**: `sync` and `pull` with manifest-based change tracking
3. **Schema validation**: JSON Schema validation on all data models
4. **Lifecycle states**: Explicit state machine (EXTERNAL → CACHED → MATERIALIZED)
5. **Layered metadata**: User overrides > source metadata > derived metadata
6. **Static catalog**: Generates static Iceberg REST catalog (no server needed)

## Dependencies

Core dependencies:
- `click` - CLI framework
- `pyarrow` - Parquet I/O and Arrow tables
- `geopandas` - Geospatial data manipulation
- `jsonschema` - Schema validation
- `httpx` - HTTP client for STAC/API calls

Optional dependencies:
- `psycopg2-binary` - PostgreSQL support
- `cx_Oracle` - Oracle support

## Related Projects

- [GeoParquet](https://geoparquet.org/) - Cloud-native vector format
- [Raquet](https://github.com/geoparquet/raquet) - Cloud-native raster format
- [Apache Iceberg](https://iceberg.apache.org/) - Table format for analytics
- [STAC](https://stacspec.org/) - SpatioTemporal Asset Catalog
- [DuckDB](https://duckdb.org/) - Analytical database with Iceberg support

## Known Limitations

### Iceberg metadata and data must be co-located for BigQuery

BigQuery requires that Iceberg metadata files (metadata JSON, manifest-list, manifest Avro) and the underlying Parquet data files reside in the same GCS bucket. You cannot have metadata on GCS pointing to data on S3. This means `materialize --remote` with cross-cloud data (e.g., S3 Parquet + GCS metadata) will create a valid Iceberg table that DuckDB can query but BigQuery cannot.

Workarounds:
- Mirror the data files to the same GCS bucket as the metadata
- Use BigQuery Omni to run queries in the same cloud region as the data
- Use DuckDB or other engines that support cross-location Iceberg tables

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes with tests
4. Run the test suite (`uv run pytest`)
5. Submit a pull request

For major changes, please open an issue first to discuss the approach.

## License

Apache 2.0 - See [LICENSE](LICENSE) for details.

## Links

- [Documentation](DOCUMENTATION.md)
- [Data Model](docs/catalog-data-model.md)
- [Demo Catalog](docs/demo-catalog.md)
- [GitHub Issues](https://github.com/portolan-sdi/portolan/issues)
