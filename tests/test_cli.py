"""
Tests for Portolan CLI commands.
"""

import json
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from portolan import cli


class TestInitCommand:
    """Test suite for init command."""

    def test_init_creates_catalog(self, temp_catalog_dir):
        """Test that init creates a .portolan directory."""
        runner = CliRunner()
        result = runner.invoke(cli, ["init", str(temp_catalog_dir)])

        assert result.exit_code == 0
        assert "Initialized Portolan catalog" in result.output
        assert (temp_catalog_dir / ".portolan").exists()
        assert (temp_catalog_dir / ".portolan" / "config.json").exists()
        assert (temp_catalog_dir / ".portolan" / "state.json").exists()

    def test_init_with_remote(self, temp_catalog_dir):
        """Test init with remote URL."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["init", str(temp_catalog_dir), "--remote", "gs://test-bucket/catalog"],
        )

        assert result.exit_code == 0
        assert "Remote: gs://test-bucket/catalog" in result.output

        # Check state.json has remote
        state_file = temp_catalog_dir / ".portolan" / "state.json"
        with open(state_file) as f:
            state = json.load(f)
        assert state["remote_url"] == "gs://test-bucket/catalog"

    def test_init_fails_if_exists(self, temp_catalog_dir):
        """Test that init fails if catalog already exists."""
        runner = CliRunner()

        # First init
        runner.invoke(cli, ["init", str(temp_catalog_dir)])

        # Second init should fail
        result = runner.invoke(cli, ["init", str(temp_catalog_dir)])
        assert "already exists" in result.output


class TestStatusCommand:
    """Test suite for status command."""

    def test_status_no_catalog(self, temp_catalog_dir):
        """Test status when no catalog exists."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=temp_catalog_dir):
            result = runner.invoke(cli, ["status"])
            assert "No Portolan catalog found" in result.output

    def test_status_with_catalog(self, initialized_catalog):
        """Test status with an initialized catalog."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(cli, ["status"])
            assert result.exit_code == 0
            assert "Portolan Catalog Status" in result.output
            assert "Resources:" in result.output

    def test_status_shows_resources(self, catalog_with_resource):
        """Test that status shows resource count."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=catalog_with_resource.path.parent):
            result = runner.invoke(cli, ["status"])
            assert result.exit_code == 0
            assert "Resources: 1" in result.output


class TestDatasetCommands:
    """Test suite for dataset commands."""

    def test_dataset_add(self, initialized_catalog, sample_geoparquet):
        """Test adding a dataset."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(
                cli,
                [
                    "dataset",
                    "add",
                    str(sample_geoparquet),
                    "--public",
                    "--title",
                    "Test Dataset",
                ],
            )

            assert result.exit_code == 0
            assert "Resource added successfully" in result.output

    def test_dataset_list_empty(self, initialized_catalog):
        """Test listing datasets when empty."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(cli, ["dataset", "list"])
            assert result.exit_code == 0


class TestSyncCommand:
    """Test suite for sync command."""

    def test_sync_no_remote(self, initialized_catalog):
        """Test sync fails without remote."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(cli, ["sync"])
            assert result.exit_code != 0
            assert "No remote configured" in result.output

    def test_sync_dry_run(self, catalog_with_resource):
        """Test sync dry run."""
        # Set up a remote URL in state
        state_file = catalog_with_resource.path / "state.json"
        with open(state_file, "w") as f:
            json.dump({"remote_url": "file:///tmp/test-remote", "base_manifest_hash": None}, f)

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=catalog_with_resource.path.parent):
            result = runner.invoke(cli, ["sync", "--dry-run"])
            assert "Dry run" in result.output or "added" in result.output


class TestRebuildCommand:
    """Test suite for rebuild command."""

    def test_rebuild_empty_catalog(self, initialized_catalog):
        """Test rebuild on empty catalog."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(cli, ["rebuild"])
            assert result.exit_code == 0

    def test_rebuild_with_resource(self, catalog_with_resource):
        """Test rebuild with a resource."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=catalog_with_resource.path.parent):
            result = runner.invoke(cli, ["rebuild", "-v"])
            assert result.exit_code == 0


class TestAddCommand:
    """Test suite for the add command."""

    def test_add_full_lifecycle(self, initialized_catalog, sample_geoparquet):
        """Test add runs full lifecycle (download + Iceberg)."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(
                cli,
                [
                    "add",
                    str(sample_geoparquet),
                    "--name",
                    "full_test",
                    "--title",
                    "Full Test",
                ],
            )

            assert result.exit_code == 0, result.output
            assert "Resource added successfully" in result.output

            # Check resource has Iceberg metadata
            resource_path = initialized_catalog.path / "resources" / "default" / "full_test.json"
            with open(resource_path) as f:
                data = json.load(f)

            assert "iceberg" in data["assets"]
            assert data["metadata"]["user"]["title"] == "Full Test"

    def test_add_public(self, initialized_catalog, sample_geoparquet):
        """Test add with --public flag."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(
                cli,
                ["add", str(sample_geoparquet), "--name", "public_test", "--public"],
            )

            assert result.exit_code == 0

            # Check resource is in public namespace
            resource_path = initialized_catalog.path / "resources" / "public" / "public_test.json"
            assert resource_path.exists()

    def test_add_catalog_only(self, initialized_catalog, sample_geoparquet):
        """Test add with --catalog-only flag registers without processing."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(
                cli,
                [
                    "add",
                    str(sample_geoparquet),
                    "--name",
                    "catalog_only_test",
                    "--catalog-only",
                ],
            )

            assert result.exit_code == 0
            assert "registered for discovery" in result.output

            # Check resource exists but has no Iceberg
            resource_path = initialized_catalog.path / "resources" / "default" / "catalog_only_test.json"
            with open(resource_path) as f:
                data = json.load(f)

            assert "iceberg" not in data.get("assets", {})
            assert "snapshot" not in data.get("assets", {})

    def test_add_with_namespace(self, initialized_catalog, sample_geoparquet):
        """Test add with custom namespace."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(
                cli,
                [
                    "add",
                    str(sample_geoparquet),
                    "--name",
                    "ns_test",
                    "--namespace",
                    "custom",
                ],
            )

            assert result.exit_code == 0
            resource_path = initialized_catalog.path / "resources" / "custom" / "ns_test.json"
            assert resource_path.exists()

    def test_add_with_title_description(self, initialized_catalog, sample_geoparquet):
        """Test add with title and description."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(
                cli,
                [
                    "add",
                    str(sample_geoparquet),
                    "--name",
                    "titled",
                    "--title",
                    "My Title",
                    "--description",
                    "My Description",
                ],
            )

            assert result.exit_code == 0

            resource_path = initialized_catalog.path / "resources" / "default" / "titled.json"
            with open(resource_path) as f:
                data = json.load(f)
            assert data["metadata"]["user"]["title"] == "My Title"
            assert data["metadata"]["user"]["description"] == "My Description"

    def test_add_creates_iceberg(self, initialized_catalog, sample_geoparquet):
        """Test that add auto-creates Iceberg metadata for parquet files."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(
                cli,
                ["add", str(sample_geoparquet), "--name", "iceberg_test"],
            )

            assert result.exit_code == 0

            # Check Iceberg metadata was created
            metadata_path = initialized_catalog.path / "data" / "default" / "iceberg_test" / "metadata" / "v1.metadata.json"
            assert metadata_path.exists()


class TestRefreshCommand:
    """Test suite for refresh command."""

    def test_refresh_not_found(self, initialized_catalog):
        """Test refresh of non-existent resource."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(cli, ["refresh", "nonexistent"])
            assert result.exit_code != 0
            assert "Resource not found" in result.output


class TestSchemaDrift:
    """Test suite for schema drift detection."""

    def test_schema_drift_on_refresh(self, initialized_catalog, temp_catalog_dir):
        """Refresh with changed source schema should detect drift."""
        import duckdb

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            # Create first parquet file
            parquet_v1 = temp_catalog_dir / "data_v1.parquet"
            conn = duckdb.connect()
            conn.execute("INSTALL spatial; LOAD spatial")
            conn.execute(f"""
                COPY (
                    SELECT 'Paris' as name, 1000 as population,
                    ST_Point(2.35, 48.85) as geometry
                ) TO '{parquet_v1}' (FORMAT PARQUET)
            """)
            conn.close()

            # Add resource
            result = runner.invoke(
                cli,
                ["add", str(parquet_v1), "--name", "drift_test"],
            )
            assert result.exit_code == 0

            # Verify schema_hash was stored
            resource_path = initialized_catalog.path / "resources" / "default" / "drift_test.json"
            with open(resource_path) as f:
                resource_data = json.load(f)
            assert resource_data["metadata"]["derived"]["schema_hash"] is not None
            original_hash = resource_data["metadata"]["derived"]["schema_hash"]

            # Create second parquet with different schema (extra column)
            parquet_v2 = temp_catalog_dir / "data_v2.parquet"
            conn = duckdb.connect()
            conn.execute("INSTALL spatial; LOAD spatial")
            conn.execute(f"""
                COPY (
                    SELECT 'Paris' as name, 1000 as population,
                    'France' as country,
                    ST_Point(2.35, 48.85) as geometry
                ) TO '{parquet_v2}' (FORMAT PARQUET)
            """)
            conn.close()

            # Update the resource origin to point to v2
            resource_data["origin"]["url"] = str(parquet_v2)
            with open(resource_path, "w") as f:
                json.dump(resource_data, f, indent=2)

            # Refresh should detect drift
            result = runner.invoke(cli, ["refresh", "drift_test", "--force"])
            assert result.exit_code == 0
            assert "Schema drift detected" in result.output

            # Verify schema hash changed
            with open(resource_path) as f:
                resource_data = json.load(f)
            new_hash = resource_data["metadata"]["derived"]["schema_hash"]
            assert new_hash != original_hash
            assert resource_data["metadata"]["derived"]["previous_schema_hash"] == original_hash

    def test_no_drift_same_schema(self, initialized_catalog, sample_geoparquet):
        """Re-add with same schema should not report drift."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            # Add resource
            runner.invoke(
                cli,
                ["add", str(sample_geoparquet), "--name", "no_drift"],
            )

            # Refresh with --force (same file, same schema)
            result = runner.invoke(cli, ["refresh", "no_drift", "--force"])
            assert result.exit_code == 0
            assert "Schema drift" not in result.output


class TestChangeDetection:
    """Test suite for refresh change detection."""

    def test_refresh_skips_unchanged_file(self, initialized_catalog, sample_geoparquet):
        """Refresh should skip re-extraction when source file hasn't changed."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            # Add resource (stores source fingerprint)
            result = runner.invoke(
                cli,
                ["add", str(sample_geoparquet), "--name", "skip_test"],
            )
            assert result.exit_code == 0

            # Verify fingerprint was stored
            resource_path = initialized_catalog.path / "resources" / "default" / "skip_test.json"
            with open(resource_path) as f:
                resource_data = json.load(f)
            assert resource_data["assets"]["snapshot"].get("source_fingerprint") is not None

            # Refresh without --force — should skip since file hasn't changed
            result = runner.invoke(cli, ["refresh", "skip_test"])
            assert result.exit_code == 0
            assert "source unchanged, skipping" in result.output

    def test_refresh_force_overrides_skip(self, initialized_catalog, sample_geoparquet):
        """--force should refresh even when source is unchanged."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(
                cli,
                ["add", str(sample_geoparquet), "--name", "force_test"],
            )
            assert result.exit_code == 0

            # Refresh with --force — should NOT skip
            result = runner.invoke(cli, ["refresh", "force_test", "--force"])
            assert result.exit_code == 0
            assert "source unchanged" not in result.output
            assert "Refreshed force_test" in result.output


class TestTilesKind:
    """Test suite for tiles kind (PMTiles)."""

    def test_remote_pmtiles_detected_as_catalog_only(self, initialized_catalog):
        """Remote PMTiles URL should be detected as tiles kind and catalog-only."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(
                cli,
                ["add", "https://example.com/buildings.pmtiles",
                 "--name", "test_tiles", "--namespace", "demo", "-v"],
            )
            assert result.exit_code == 0
            assert "tiles" in result.output.lower()

            # Check resource was created with kind=tiles
            resource_path = initialized_catalog.path / "resources" / "demo" / "test_tiles.json"
            with open(resource_path) as f:
                data = json.load(f)
            assert data["kind"] == "tiles"
            assert data["origin"]["type"] == "tiles"
            # Remote tiles should be registered (catalog-only, no snapshot/iceberg)
            assert "snapshot" not in data.get("assets", {}) or data["assets"].get("snapshot") is None

    def test_pointcloud_kind_schema_valid(self):
        """Pointcloud and tiles are valid kinds in schema."""
        from schemas import validate_resource

        for kind in ("pointcloud", "tiles"):
            data = {"name": "test", "kind": kind}
            errors = validate_resource(data)
            assert errors == [], f"kind='{kind}' should be valid"


class TestTiles3dKind:
    """Test suite for 3D Tiles kind."""

    def test_tiles3d_explicit_type(self, initialized_catalog):
        """--type tiles3d should register as tiles kind with tiles3d origin."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(
                cli,
                ["add", "https://example.com/buildings/tileset.json",
                 "--type", "tiles3d",
                 "--name", "test_3dtiles", "--namespace", "demo",
                 "--catalog-only", "-v"],
            )
            assert result.exit_code == 0

            resource_path = initialized_catalog.path / "resources" / "demo" / "test_3dtiles.json"
            with open(resource_path) as f:
                data = json.load(f)
            assert data["kind"] == "tiles"
            assert data["origin"]["type"] == "tiles3d"

    def test_tiles3d_schema_valid(self):
        """tiles3d should be a valid origin type in schema."""
        from schemas import validate_resource

        data = {
            "name": "test",
            "kind": "tiles",
            "origin": {"type": "tiles3d", "url": "https://example.com/tileset.json"},
        }
        errors = validate_resource(data)
        assert errors == [], f"tiles3d origin type should be valid: {errors}"


class TestMetadataCommands:
    """Test suite for metadata commands."""

    def test_metadata_show(self, initialized_catalog, sample_geoparquet):
        """Test metadata show displays user metadata."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            runner.invoke(cli, ["add", str(sample_geoparquet), "--name", "meta_test", "--title", "Test Cities"])
            result = runner.invoke(cli, ["metadata", "show", "meta_test"])
            assert result.exit_code == 0
            assert "Test Cities" in result.output
            assert "User metadata:" in result.output

    def test_metadata_show_json(self, initialized_catalog, sample_geoparquet):
        """Test metadata show --json outputs valid JSON."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            runner.invoke(cli, ["add", str(sample_geoparquet), "--name", "json_test", "--title", "JSON Test"])
            result = runner.invoke(cli, ["metadata", "show", "json_test", "--json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "user" in data
            assert data["user"]["title"] == "JSON Test"

    def test_metadata_set_well_known(self, initialized_catalog, sample_geoparquet):
        """Setting a well-known field goes to typed field."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            runner.invoke(cli, ["add", str(sample_geoparquet), "--name", "wk_test"])
            result = runner.invoke(cli, ["metadata", "set", "wk_test", "license", "CC-BY-4.0"])
            assert result.exit_code == 0

            resource_path = initialized_catalog.path / "resources" / "default" / "wk_test.json"
            with open(resource_path) as f:
                data = json.load(f)
            assert data["metadata"]["user"]["license"] == "CC-BY-4.0"

    def test_metadata_set_custom_property(self, initialized_catalog, sample_geoparquet):
        """Setting a non-well-known field goes to properties."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            runner.invoke(cli, ["add", str(sample_geoparquet), "--name", "prop_test"])
            result = runner.invoke(cli, ["metadata", "set", "prop_test", "contact_email", "test@example.com"])
            assert result.exit_code == 0

            resource_path = initialized_catalog.path / "resources" / "default" / "prop_test.json"
            with open(resource_path) as f:
                data = json.load(f)
            assert data["metadata"]["user"]["properties"]["contact_email"] == "test@example.com"

    def test_metadata_set_json_bulk(self, initialized_catalog, sample_geoparquet):
        """Bulk set via JSON."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            runner.invoke(cli, ["add", str(sample_geoparquet), "--name", "bulk_test"])
            result = runner.invoke(cli, [
                "metadata", "set", "bulk_test",
                "--json", '{"license": "MIT", "contact_email": "bulk@example.com", "topic_category": "boundaries"}',
            ])
            assert result.exit_code == 0
            assert "Updated 3 field(s)" in result.output

            resource_path = initialized_catalog.path / "resources" / "default" / "bulk_test.json"
            with open(resource_path) as f:
                data = json.load(f)
            assert data["metadata"]["user"]["license"] == "MIT"
            assert data["metadata"]["user"]["properties"]["contact_email"] == "bulk@example.com"
            assert data["metadata"]["user"]["properties"]["topic_category"] == "boundaries"

    def test_metadata_unset(self, initialized_catalog, sample_geoparquet):
        """Unset removes a property."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            runner.invoke(cli, ["add", str(sample_geoparquet), "--name", "unset_test"])
            runner.invoke(cli, ["metadata", "set", "unset_test", "contact_email", "test@example.com"])
            result = runner.invoke(cli, ["metadata", "unset", "unset_test", "contact_email"])
            assert result.exit_code == 0
            assert "Removed" in result.output

    def test_metadata_set_nonexistent_resource(self, initialized_catalog):
        """Set on nonexistent resource fails."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(cli, ["metadata", "set", "nonexistent", "key", "value"])
            assert result.exit_code != 0
            assert "not found" in result.output.lower()


class TestParseRemoteUrl:
    """Test suite for _parse_remote_url helper."""

    def test_s3_url(self):
        """Test parsing s3:// URLs."""
        from portolan import _parse_remote_url

        scheme, path = _parse_remote_url("s3://my-bucket/data/file.parquet")
        assert scheme == "s3"
        assert path == "my-bucket/data/file.parquet"

    def test_gs_url(self):
        """Test parsing gs:// URLs."""
        from portolan import _parse_remote_url

        scheme, path = _parse_remote_url("gs://my-bucket/data/file.parquet")
        assert scheme == "gs"
        assert path == "my-bucket/data/file.parquet"

    def test_s3_https_url(self):
        """Test parsing S3 public HTTPS URLs."""
        from portolan import _parse_remote_url

        scheme, path = _parse_remote_url(
            "https://my-bucket.s3.us-west-2.amazonaws.com/data/file.parquet"
        )
        assert scheme == "s3"
        assert path == "my-bucket/data/file.parquet"

    def test_gcs_https_url(self):
        """Test parsing GCS public HTTPS URLs."""
        from portolan import _parse_remote_url

        scheme, path = _parse_remote_url(
            "https://storage.googleapis.com/my-bucket/data/file.parquet"
        )
        assert scheme == "gs"
        assert path == "my-bucket/data/file.parquet"

    def test_generic_https_url(self):
        """Test parsing generic HTTPS URLs."""
        from portolan import _parse_remote_url

        scheme, path = _parse_remote_url("https://example.com/data/file.parquet")
        assert scheme == "https"
        assert path == "https://example.com/data/file.parquet"

    def test_az_url(self):
        """Test parsing az:// URLs."""
        from portolan import _parse_remote_url

        scheme, path = _parse_remote_url("az://mycontainer/data/file.parquet")
        assert scheme == "az"
        assert path == "mycontainer/data/file.parquet"

    def test_local_file(self):
        """Test parsing local file paths."""
        from portolan import _parse_remote_url

        scheme, path = _parse_remote_url("/path/to/file.parquet")
        assert scheme == "file"
        assert path == "/path/to/file.parquet"


class TestTableNameValidation:
    """Test suite for SQL injection prevention."""

    def test_valid_simple_name(self):
        """Test valid simple table name."""
        from extractors import _validate_table_name

        assert _validate_table_name("cities") == "cities"

    def test_valid_schema_qualified(self):
        """Test valid schema-qualified table name."""
        from extractors import _validate_table_name

        assert _validate_table_name("public.buildings") == "public.buildings"

    def test_valid_underscore(self):
        """Test valid name with underscores."""
        from extractors import _validate_table_name

        assert _validate_table_name("my_table_2024") == "my_table_2024"

    def test_rejects_sql_injection(self):
        """Test that SQL injection attempts are rejected."""
        from extractors import _validate_table_name

        with pytest.raises(click.ClickException):
            _validate_table_name("'; DROP TABLE users; --")

    def test_rejects_semicolon(self):
        """Test that semicolons are rejected."""
        from extractors import _validate_table_name

        with pytest.raises(click.ClickException):
            _validate_table_name("table; DELETE FROM x")

    def test_rejects_spaces(self):
        """Test that spaces are rejected."""
        from extractors import _validate_table_name

        with pytest.raises(click.ClickException):
            _validate_table_name("table name")

    def test_rejects_starting_number(self):
        """Test that names starting with numbers are rejected."""
        from extractors import _validate_table_name

        with pytest.raises(click.ClickException):
            _validate_table_name("123table")


class TestExtractorDispatch:
    """Test suite for extractor dispatch."""

    def test_unsupported_type_raises(self):
        """Test that unsupported origin type raises error."""
        from extractors import run_extractor
        from portolan_resource import Origin, Resource

        resource = Resource(
            name="test",
            kind="vector",
            origin=Origin(type="unsupported", url="http://example.com"),
        )
        with pytest.raises(click.ClickException, match="Unsupported origin type"):
            run_extractor(resource, Path("/tmp/out.parquet"), catalog_path=Path("/tmp"))

    def test_file_extractor(self, initialized_catalog, sample_geoparquet):
        """Test file extractor via dispatch."""
        from extractors import run_extractor
        from portolan_resource import Origin, Resource

        resource = Resource(
            name="test_dispatch",
            kind="vector",
            origin=Origin(type="file", url=str(sample_geoparquet)),
        )

        output_path = initialized_catalog.path / "data" / "test_output.parquet"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        run_extractor(resource, output_path, catalog_path=initialized_catalog.path)
        assert output_path.exists()
        assert output_path.stat().st_size > 0


class TestLoadCommand:
    """Test suite for load command."""

    def test_load_arcgis_dry_run(self, initialized_catalog, monkeypatch):
        """Dry run prints discovered services without saving."""
        fake_fs = [
            {
                "name": "Buildings",
                "url": "https://example.com/arcgis/rest/services/Buildings/FeatureServer",
                "layers": [
                    {"id": 0, "name": "Footprints", "geometryType": "esriGeometryPolygon"},
                    {"id": 1, "name": "Points", "geometryType": "esriGeometryPoint"},
                ],
            }
        ]
        fake_is = [
            {
                "name": "Elevation",
                "url": "https://example.com/arcgis/rest/services/Elevation/ImageServer",
                "pixel_type": "U8",
                "band_count": 3,
                "extent": {},
            }
        ]

        monkeypatch.setattr(
            "portolan.discover_arcgis_services",
            lambda url, verbose=False: (fake_fs, fake_is),
        )

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(
                cli,
                [
                    "load",
                    "https://example.com/arcgis/rest/services",
                    "--dry-run",
                ],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            assert "Dry run" in result.output
            assert "buildings_footprints" in result.output
            assert "buildings_points" in result.output
            assert "elevation" in result.output

    def test_load_arcgis_saves_resources(self, initialized_catalog, monkeypatch):
        """Load saves resource JSON files to catalog."""
        fake_fs = [
            {
                "name": "Rivers",
                "url": "https://example.com/arcgis/rest/services/Rivers/FeatureServer",
                "layers": [
                    {"id": 0, "name": "Main", "geometryType": "esriGeometryPolyline"},
                ],
            }
        ]
        fake_is = []

        monkeypatch.setattr(
            "portolan.discover_arcgis_services",
            lambda url, verbose=False: (fake_fs, fake_is),
        )

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(
                cli,
                [
                    "load",
                    "https://example.com/arcgis/rest/services",
                    "--namespace", "test_arcgis",
                ],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            assert "Loaded 1 resources" in result.output

        # Check resource file was created in new Resource format
        resource_file = initialized_catalog.path / "resources" / "test_arcgis" / "rivers.json"
        assert resource_file.exists()

        resource = json.loads(resource_file.read_text())
        assert resource["name"] == "rivers"
        assert resource["kind"] == "vector"
        assert resource["origin"]["type"] == "arcgis_featureserver"
        assert "FeatureServer/0" in resource["origin"]["url"]

    def test_load_bad_arcgis_url(self, initialized_catalog):
        """Non-ArcGIS URL is rejected."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(
                cli,
                ["load", "https://example.com/not-arcgis", "--type", "arcgis-server"],
                catch_exceptions=False,
            )
            assert result.exit_code != 0
            assert "REST services endpoint" in result.output


class TestDottedNamespaces:
    """Tests for hierarchical dotted namespace support."""

    def test_add_with_dotted_namespace(self, initialized_catalog, sample_geoparquet):
        """Add a resource using a dotted namespace."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(
                cli,
                [
                    "add",
                    str(sample_geoparquet),
                    "--name", "fires",
                    "--namespace", "europe.spain",
                ],
                catch_exceptions=False,
            )
            assert result.exit_code == 0

        resource_file = initialized_catalog.path / "resources" / "europe.spain" / "fires.json"
        assert resource_file.exists()

        resource = json.loads(resource_file.read_text())
        assert resource["name"] == "fires"

    def test_invalid_namespace_rejected(self, initialized_catalog, sample_geoparquet):
        """Invalid namespaces are rejected with a clear error."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(
                cli,
                [
                    "add",
                    str(sample_geoparquet),
                    "--name", "test",
                    "--namespace", "Europe.Spain",
                ],
            )
            assert result.exit_code != 0
            assert "Invalid namespace" in result.output

    def test_dataset_list_tree_display(self, initialized_catalog, sample_geoparquet):
        """dataset list renders dotted namespaces as a tree."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            # Add resources in dotted namespaces
            runner.invoke(
                cli,
                ["add", str(sample_geoparquet), "--name", "fires",
                 "--namespace", "europe.spain", "--catalog-only"],
                catch_exceptions=False,
            )
            runner.invoke(
                cli,
                ["add", str(sample_geoparquet), "--name", "cities",
                 "--namespace", "europe.france", "--catalog-only"],
                catch_exceptions=False,
            )

            result = runner.invoke(
                cli,
                ["dataset", "list"],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            assert "europe/" in result.output
            assert "spain/" in result.output
            assert "france/" in result.output
            assert "fires" in result.output
            assert "cities" in result.output

    def test_namespace_underscore_allowed(self, initialized_catalog, sample_geoparquet):
        """Underscores are valid in namespace segments."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(
                cli,
                [
                    "add",
                    str(sample_geoparquet),
                    "--name", "test",
                    "--namespace", "my_server.data_folder",
                    "--catalog-only",
                ],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
