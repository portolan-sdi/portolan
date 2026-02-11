"""
Static Iceberg REST Catalog generation — re-export facade.

This module re-exports all public symbols from the three sub-modules:
- iceberg_metadata: Core Iceberg types, schemas, manifests, parquet utilities
- iceberg_rest_catalog: REST catalog endpoint generation
- sdi_catalog: STAC + ISO 19115 SDI catalog support
"""

# Core Iceberg metadata & types
from iceberg_metadata import (  # noqa: F401
    IcebergTable,
    _arrow_schema_to_iceberg,
    _arrow_to_iceberg_schema,
    _arrow_type_to_iceberg,
    _arrow_type_to_pyiceberg,
    add_iceberg_field_ids,
    create_name_mapping,
    create_table_metadata,
    generate_manifest_files,
    parquet_to_iceberg_table,
)

# REST catalog generation
from iceberg_rest_catalog import (  # noqa: F401
    create_catalog_config,
    create_load_table_response,
    create_namespace_detail,
    create_namespaces_list,
    create_tables_list,
    generate_static_catalog,
)

# SDI catalog (STAC + ISO 19115)
from sdi_catalog import (  # noqa: F401
    create_items_table,
    create_stac_iso_record,
    create_stac_iso_schema,
    detect_parquet_type,
    extract_geoparquet_metadata,
    extract_parquet_metadata,
    extract_raquet_metadata,
    generate_sdi_catalog,
)
