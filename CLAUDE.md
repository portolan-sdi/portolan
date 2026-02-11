# CLAUDE.md

## Project Overview

Portolan is a CLI tool (pre-release) for building spatial data infrastructures using open formats. It converts geospatial data into GeoParquet/Raquet/Parquet, wraps it in Apache Iceberg, and generates discovery catalogs (STAC, ISO 19139, web).

## Running

```bash
uv sync                    # Install dependencies
uv run portolan <command>  # Run CLI
.venv/bin/pytest tests/    # Run tests (300 tests, ~3s)
```

## Architecture

**Single-package Python project** — all modules at root level, no `src/` layout.

### Key Modules

| Module | Role |
|--------|------|
| `portolan.py` | CLI entry point (Click). All commands. `CatalogConfig`, `OutputsConfig` dataclasses. |
| `portolan_resource.py` | Resource model dataclasses (`Resource`, `Origin`, `Assets`, `SnapshotAsset`, `IcebergAsset`, `DerivedMetadata`, `UserMetadata`). State machine: `origin` only = registered, `assets.iceberg` or `assets.snapshot` = ready. |
| `extractors.py` | Data extraction dispatch. `run_extractor()` routes by `resource.origin.type`. `EXTRACTORS` set lists types with extractors. |
| `output_generators.py` | All output generation. `_normalize_resource()` converts Resource dicts to flat format for generators. Split into metadata outputs (STAC, ISO, web, Iceberg metadata catalog) and data outputs (Iceberg data tables, DuckLake). |
| `schemas.py` | JSON Schema definitions and validators. `RESOURCE_SCHEMA`, `CONFIG_SCHEMA`, `STATE_SCHEMA`. `additionalProperties: false` everywhere — update schema when adding fields. |
| `catalog_state.py` | `ObstoreRemoteStore` wraps obstore for S3/GCS/Azure/S3-compatible. `LocalState` for sync tracking. `scan_catalog_outputs()` discovers all output files for sync. |
| `iceberg_metadata.py` | Core Iceberg types (`IcebergTable`), schema conversion, manifest generation. |
| `iceberg_rest_catalog.py` | Static Iceberg REST catalog endpoint generation. |
| `iceberg_catalog.py` | Re-export facade for the three iceberg modules. |
| `sdi_catalog.py` | STAC + ISO 19115 record generation from Parquet metadata. |

### Config Structure

`.portolan/config.json`:
```json
{
  "outputs": {
    "metadata": { "stac": false, "iso19139": false, "web": false, "iceberg": true },
    "data": { "iceberg": true, "ducklake": false }
  }
}
```

Each output value is `true`/`false` or `{"enabled": true, ...}` for format-specific config.

### Resource Lifecycle

Two states: **REGISTERED** (origin only, discoverable) and **READY** (has snapshot/iceberg, queryable).

Three commands move resources through states:
- `add` — register + extract + create Iceberg (smart defaults based on origin type)
- `load` — bulk import from external catalogs (STAC, ArcGIS)
- `refresh` — re-fetch from origin with change detection

### Output System

- **Metadata outputs**: Discovery catalogs of ALL resources. `regenerate_metadata_outputs()` / `update_metadata_outputs()`.
- **Data outputs**: Queryable tables for READY resources. `regenerate_data_outputs()` / `update_data_outputs()`.
- `rebuild` command delegates to `regenerate_all_outputs()`. `--base-url` rewrites Iceberg metadata URLs for remote deployment.
- `add`/`refresh` gate Iceberg data creation on `catalog.outputs.is_enabled("data", "iceberg")`.

### Remote Deployment

- `rebuild --base-url <URL>` rewrites all Iceberg metadata (locations, manifests, data file paths) to use the public URL.
- `sync` uploads both resources (manifest-tracked with conflict detection) AND all output files (data/, v1/, stac/, iso19139/, web/).
- Output files are full-overwrite (derived artifacts, no diff tracking needed).
- `scan_catalog_outputs()` in `catalog_state.py` discovers uploadable files, excludes config/state/resources dir, maps v1/ `__list__`/`__detail__` suffixes.
- `_EXCLUDED_DATA_SUBDIRS = {"raw"}` skips local extract cache from upload.

### Key Helpers in portolan.py

- `_register_resource()` — create Resource + save JSON
- `_extract_to_parquet()` — download + convert via extractors
- `_create_iceberg_metadata()` — create per-resource Iceberg table
- `_create_remote_iceberg()` — Iceberg pointing to remote Parquet (no download)
- `_detect_default_action()` — smart defaults: remote Parquet → remote Iceberg; known formats → download+Iceberg; unknown → catalog-only

## Conventions

- **Tests**: Use `runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent)` because `get_catalog()` searches from CWD.
- **Schema updates**: When adding fields to resource model dataclasses, also update the schema in `schemas.py` (additionalProperties: false will reject unknown fields).
- **Namespaces**: Dot-separated hierarchy (`europe.spain`). Stored as flat directory names. Converted to underscores for Iceberg (`europe_spain`).
- **Parquet formats**: vector→GeoParquet, raster→Raquet, tiles→Tilequet, pointcloud→Parquet. All go through Iceberg.
- **No backwards compatibility**: Pre-release, no migration code. Change formats directly.
- **obstore v0.8.2**: `result.bytes().to_bytes()` for Python bytes, `FileNotFoundError` for missing keys, `obs.list()` returns nested lists.
