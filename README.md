# Portolan

The goal of Portolan is to enable organizations to easily share open data in an low-cost, accessible, soveriegn, reliable and user-friendly manner. We are focused on enabling governments, but any organization that wants to share data with the world (or even internally) will benefit from the tools and standards Portolan provides. The effort is run as a collaborative open source project - not controlled by any organization and with open decision-making from the start.

The core of Portolan is the [cloud native geospatial](https://cloudnativegeo.org) formats, can be hosted on any cloud (or any server that supports range requests). The formats scale incredibly well, and are cheaper than almost any option, as the only costs are for storage and 'egress'. A small government with mostly vector data will pay just a few dollars a month, and even a full set of imagery and point clouds will likely be less than $50 a month. Organizations like [Source Cooperative](https://source.coop) currently provide free hosting for open data, and Portolan runs easily on those.

Portolan brings together a number of open source projects to make it easier to get data into those formats, and to make the data that is in those formats more friendly and accessible to all. A Portolan node is a set of open geospatial data that as interactive as any geospatial 'portal', but is faster, more reliable, more scalable and much cheaper to run. Our goal is to enable thousands of Portolan nodes, and make geospatial information truly accessible. Leveraging standard, accessible formats also enables AI to much more easily take advantage of the information, so Portolan nodes become part of the broader data infrastructure with ease.

## Getting Started

### Prerequisites

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Installation

```bash
# Clone the repository
git clone https://github.com/portolan-sdi/portolan.git
cd portolan

# Install dependencies
uv sync

# Verify installation
uv run portolan --help
```

### Quick Start

Portolan uses a **local-first workflow**: work with data locally, then sync to remote storage.

1. **Initialize a catalog** in your project directory:

```bash
uv run portolan init
```

This creates a `.portolan` directory with your local catalog.

2. **Add a dataset** to the local catalog:

```bash
# Add a public dataset
uv run portolan dataset add mydata.parquet --public --title "My Dataset"

# Add a private dataset
uv run portolan dataset add mydata.parquet --tenant acme --collection imagery
```

3. **Configure a remote** storage backend (optional):

```bash
# AWS S3
uv run portolan remote add origin s3://my-bucket/portolan

# Google Cloud Storage
uv run portolan remote add origin gs://my-bucket/portolan

# MinIO or S3-compatible
uv run portolan remote add origin s3://warehouse --endpoint http://localhost:9000

# Local filesystem
uv run portolan remote add origin file:///var/data/portolan
```

4. **Sync to remote** when ready:

```bash
uv run portolan sync
```

5. **Browse locally** with the web UI:

```bash
uv run portolan web serve
# Open http://localhost:8080 in your browser
```

## Architecture

Portolan creates a **static Iceberg REST catalog** that can be hosted on any cloud storage. This enables:

- **Zero-server architecture**: No backend servers needed, just static files
- **Local-first workflow**: Work locally, sync to remote when ready
- **Pluggable storage**: AWS S3, Google Cloud Storage, Azure Blob, or local filesystem
- **Standard formats**: Uses [GeoParquet](https://geoparquet.org/) for vectors and [Raquet](https://github.com/geoparquet/raquet) for rasters
- **Iceberg metadata**: Full compatibility with Iceberg-aware tools like DuckDB, Spark, and Trino
- **STAC + ISO 19115**: Metadata tables include both STAC and ISO 19115 fields for SDI compliance

### Supported Storage Backends

Portolan uses [obstore](https://github.com/developmentseed/obstore) for storage abstraction:

| Backend | URL Format | Example |
|---------|------------|---------|
| AWS S3 | `s3://bucket/path` | `s3://my-data/portolan` |
| Google Cloud | `gs://bucket/path` | `gs://my-bucket/portolan` |
| Azure Blob | `az://container/path` | `az://mycontainer/portolan` |
| Local filesystem | `file:///path` | `file:///var/data/portolan` |
| S3-compatible | `s3://bucket` + `--endpoint` | MinIO, DigitalOcean Spaces, etc. |

### Storage Layout

```
bucket/
  manifest.json           # Catalog index for web UI
  index.html              # Web UI (optional)
  public/                 # Publicly accessible datasets
    {collection}/
      data/
        {collection}/
          items/          # STAC+ISO metadata table
          {dataset}/      # Individual dataset files
  private/                # Access-controlled datasets
    {tenant}/
      {collection}/
        ...
```

### Components

| File | Description |
|------|-------------|
| `portolan.py` | CLI tool for managing datasets, users, and access |
| `iceberg_catalog.py` | Core library for generating Iceberg/STAC/ISO catalogs |
| `esri2iceberg.py` | Converter for ArcGIS FeatureServer/ImageServer services |
| `web/index.html` | Browser-based catalog viewer with DuckDB WASM |

## CLI Reference

### Initialize & Status

```bash
# Initialize a new catalog
portolan init [path] [options]
  --remote, -r   Remote storage URL (e.g., s3://bucket/path)
  --name, -n     Name for the remote (default: origin)

# Show catalog status
portolan status
```

### Dataset Management

```bash
# Add a dataset
portolan dataset add <file> [options]
  --id           Dataset ID (default: filename)
  --title        Dataset title
  --description  Dataset description
  --collection   Collection name (default: datasets)
  --tenant       Tenant for private datasets (default: default)
  --public       Make dataset publicly accessible
  --topic        ISO topic category
  --license      License (default: CC-BY-4.0)
  --verbose      Show detailed output

# List datasets
portolan dataset list [--verbose]

# Remove a dataset
portolan dataset remove <visibility/collection/dataset> [--force]
```

### Remote Storage

```bash
# Add a remote
portolan remote add <name> <url> [options]
  --access-key   AWS access key (or set AWS_ACCESS_KEY_ID)
  --secret-key   AWS secret key (or set AWS_SECRET_ACCESS_KEY)
  --endpoint     Custom endpoint URL (for MinIO, etc.)
  --region       AWS region (default: us-east-1)
  --anonymous    Use anonymous access
  --default      Set as default remote

# List remotes
portolan remote list

# Remove a remote
portolan remote remove <name>

# Set default remote
portolan remote set-default <name>
```

### Sync

```bash
# Sync to remote storage
portolan sync [options]
  --remote, -r   Remote name (default: uses default remote)
  --verbose, -v  Show detailed output
  --dry-run      Preview sync without uploading
```

### Web UI

```bash
# Serve locally for development
portolan web serve [--port 8080] [--host 127.0.0.1]

# Deploy web UI to remote storage
portolan web deploy [--remote <name>]
```

## Web UI

The web UI (`web/index.html`) provides a browser-based interface for exploring Portolan catalogs:

- **Dataset browsing**: View all public datasets with metadata
- **Authentication**: Sign in with S3 credentials to access private datasets
- **Map preview**: Interactive maps for GeoParquet (vector) and Raquet (raster) data
- **Query examples**: Copy-paste DuckDB queries for each dataset

The UI uses DuckDB WASM to query parquet files directly from storage, requiring no backend server.

## Converting ArcGIS Services

Use `esri2iceberg.py` to convert ArcGIS REST services to Portolan format:

```bash
# Convert all FeatureServers and ImageServers
python esri2iceberg.py https://services.arcgis.com/.../rest/services \
  --bucket my-bucket \
  --s3-endpoint storage.googleapis.com

# Skip raster conversion
python esri2iceberg.py <url> --bucket my-bucket --skip-rasters

# Specify raster resolution
python esri2iceberg.py <url> --bucket my-bucket --raster-resolution 12
```

## Querying with DuckDB

Portolan catalogs work seamlessly with DuckDB:

```sql
-- Load the Iceberg extension
LOAD iceberg;

-- Attach a Portolan catalog
ATTACH 'warehouse' AS catalog (
    TYPE iceberg,
    ENDPOINT 'http://localhost:9000/warehouse',
    AUTHORIZATION_TYPE 'none'
);

-- List all tables
SHOW ALL TABLES;

-- Query a dataset
SELECT * FROM catalog.default.my_dataset LIMIT 10;

-- Query the STAC+ISO metadata table
SELECT id, title, bbox_west, bbox_south, bbox_east, bbox_north
FROM catalog.datasets.items;
```

## License

This project is open source. See the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please open an issue or pull request on GitHub.
