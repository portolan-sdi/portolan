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


class TestRegisterCommand:
    """Test suite for register command."""

    def test_register_file(self, initialized_catalog, sample_geoparquet):
        """Test registering a local file."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(
                cli,
                [
                    "register",
                    "file",
                    str(sample_geoparquet),
                    "--name",
                    "test_file",
                ],
            )

            assert result.exit_code == 0
            assert "Registered file resource" in result.output
            assert "State: EXTERNAL" in result.output

            # Check resource file was created
            resource_path = initialized_catalog.path / "resources" / "default" / "test_file.json"
            assert resource_path.exists()

    def test_register_with_namespace(self, initialized_catalog, sample_geoparquet):
        """Test registering with custom namespace."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(
                cli,
                [
                    "register",
                    "file",
                    str(sample_geoparquet),
                    "--name",
                    "test_ns",
                    "--namespace",
                    "custom",
                ],
            )

            assert result.exit_code == 0
            resource_path = initialized_catalog.path / "resources" / "custom" / "test_ns.json"
            assert resource_path.exists()

    def test_register_with_title(self, initialized_catalog, sample_geoparquet):
        """Test registering with title and description."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(
                cli,
                [
                    "register",
                    "file",
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

            # Check metadata
            import json
            resource_path = initialized_catalog.path / "resources" / "default" / "titled.json"
            with open(resource_path) as f:
                data = json.load(f)
            assert data["metadata"]["user"]["title"] == "My Title"
            assert data["metadata"]["user"]["description"] == "My Description"


class TestSnapshotCommand:
    """Test suite for snapshot command."""

    def test_snapshot_file(self, initialized_catalog, sample_geoparquet):
        """Test snapshotting a registered vector file auto-creates Iceberg metadata."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            # First register
            runner.invoke(
                cli,
                ["register", "file", str(sample_geoparquet), "--name", "snap_test"],
            )

            # Then snapshot
            result = runner.invoke(cli, ["snapshot", "snap_test"])

            assert result.exit_code == 0
            assert "Snapshot created" in result.output
            # Vector resources should be auto-materialized
            assert "State: MATERIALIZED" in result.output
            assert "Iceberg: auto-registered" in result.output

            # Check snapshot file was created
            snapshot_path = initialized_catalog.path / "data" / "raw" / "default" / "snap_test" / "snap_test.parquet"
            assert snapshot_path.exists()

            # Check Iceberg metadata was auto-created
            metadata_path = initialized_catalog.path / "data" / "default" / "snap_test" / "metadata" / "v1.metadata.json"
            assert metadata_path.exists()

    def test_snapshot_not_found(self, initialized_catalog):
        """Test snapshot of non-existent resource."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(cli, ["snapshot", "nonexistent"])

            assert result.exit_code != 0
            assert "Resource not found" in result.output


class TestMaterializeCommand:
    """Test suite for materialize command."""

    def test_materialize_vector_already_done(self, initialized_catalog, sample_geoparquet):
        """Test materializing a vector resource that was auto-materialized by snapshot."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            # Register and snapshot (auto-materializes for vectors)
            runner.invoke(
                cli,
                ["register", "file", str(sample_geoparquet), "--name", "mat_test"],
            )
            runner.invoke(cli, ["snapshot", "mat_test"])

            # Materialize should recognize it's already done
            result = runner.invoke(cli, ["materialize", "mat_test"])

            assert result.exit_code == 0
            assert "already has Iceberg metadata" in result.output

            # Iceberg metadata should exist (from snapshot)
            metadata_path = initialized_catalog.path / "data" / "default" / "mat_test" / "metadata" / "v1.metadata.json"
            assert metadata_path.exists()

    def test_materialize_force_vector(self, initialized_catalog, sample_geoparquet):
        """Test force re-materializing a vector resource."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            # Register and snapshot (auto-materializes for vectors)
            runner.invoke(
                cli,
                ["register", "file", str(sample_geoparquet), "--name", "force_mat"],
            )
            runner.invoke(cli, ["snapshot", "force_mat"])

            # Force materialize should regenerate
            result = runner.invoke(cli, ["materialize", "force_mat", "--force"])

            assert result.exit_code == 0
            assert "Materialized" in result.output

    def test_materialize_not_cached(self, initialized_catalog, sample_geoparquet):
        """Test materializing without snapshotting first."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            # Register but don't snapshot
            runner.invoke(
                cli,
                ["register", "file", str(sample_geoparquet), "--name", "not_cached"],
            )

            result = runner.invoke(cli, ["materialize", "not_cached"])

            assert result.exit_code != 0
            assert "must be cached first" in result.output


class TestAddCommand:
    """Test suite for add convenience command."""

    def test_add_full_lifecycle(self, initialized_catalog, sample_geoparquet):
        """Test add runs full lifecycle (register + snapshot + materialize)."""
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

            assert result.exit_code == 0
            assert "Resource added successfully" in result.output

            # Check resource is materialized
            import json
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


class TestSchemaDrift:
    """Test suite for schema drift detection."""

    def test_snapshot_force_detects_and_accepts_drift(self, initialized_catalog, temp_catalog_dir):
        """Snapshot --force with changed schema should detect drift and accept it."""
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

            # Register and snapshot
            result = runner.invoke(
                cli,
                ["register", "file", str(parquet_v1), "--name", "drift_test"],
            )
            assert result.exit_code == 0

            result = runner.invoke(cli, ["snapshot", "drift_test"])
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

            # Re-snapshot with --force should detect drift and accept it
            result = runner.invoke(cli, ["snapshot", "drift_test", "--force"])
            assert result.exit_code == 0
            assert "Schema drift detected" in result.output
            assert "Schema change accepted" in result.output

            # Verify schema hash changed
            with open(resource_path) as f:
                resource_data = json.load(f)
            new_hash = resource_data["metadata"]["derived"]["schema_hash"]
            assert new_hash != original_hash

            # Verify previous_schema_hash was tracked
            assert resource_data["metadata"]["derived"]["previous_schema_hash"] == original_hash

    def test_no_drift_same_schema(self, initialized_catalog, sample_geoparquet):
        """Re-snapshot with same schema should not report drift."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            # Register and snapshot
            runner.invoke(
                cli,
                ["register", "file", str(sample_geoparquet), "--name", "no_drift"],
            )
            runner.invoke(cli, ["snapshot", "no_drift"])

            # Re-snapshot with --force (same file, same schema)
            result = runner.invoke(cli, ["snapshot", "no_drift", "--force"])
            assert result.exit_code == 0
            assert "Schema drift" not in result.output


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


class TestImportArcgisServer:
    """Test suite for import arcgis-server command."""

    def test_help_shows(self):
        """Command shows up in help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["import", "arcgis-server", "--help"])
        assert result.exit_code == 0
        assert "arcgis-server" in result.output.lower() or "ArcGIS" in result.output

    def test_bad_url_rejected(self, initialized_catalog):
        """Non-ArcGIS URL is rejected."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(
                cli,
                ["import", "arcgis-server", "https://example.com/not-arcgis"],
                catch_exceptions=False,
            )
            assert result.exit_code != 0
            assert "REST services endpoint" in result.output

    def test_dry_run_with_mocked_discovery(self, initialized_catalog, monkeypatch):
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
                    "import", "arcgis-server",
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
            assert "1 FeatureServer" in result.output
            assert "1 ImageServer" in result.output

    def test_import_saves_resources(self, initialized_catalog, monkeypatch):
        """Import saves resource JSON files to catalog."""
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
                    "import", "arcgis-server",
                    "https://example.com/arcgis/rest/services",
                    "--namespace", "test_arcgis",
                ],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            assert "Imported 1 resources" in result.output

        # Check resource file was created
        resource_file = initialized_catalog.path / "resources" / "test_arcgis" / "rivers.json"
        assert resource_file.exists()

        resource = json.loads(resource_file.read_text())
        assert resource["name"] == "rivers"
        assert resource["kind"] == "vector"
        assert resource["origin"]["type"] == "arcgis_featureserver"
        assert "FeatureServer/0" in resource["origin"]["url"]

    def test_skip_rasters(self, initialized_catalog, monkeypatch):
        """--skip-rasters filters out ImageServers."""
        fake_fs = [
            {
                "name": "Data",
                "url": "https://example.com/rest/services/Data/FeatureServer",
                "layers": [{"id": 0, "name": "Layer", "geometryType": "esriGeometryPoint"}],
            }
        ]
        fake_is = [
            {
                "name": "Raster",
                "url": "https://example.com/rest/services/Raster/ImageServer",
                "pixel_type": "U8",
                "band_count": 1,
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
                    "import", "arcgis-server",
                    "https://example.com/rest/services",
                    "--skip-rasters",
                    "--dry-run",
                ],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            assert "0 ImageServer" in result.output
            assert "raster" not in result.output.lower().split("dry run")[1]


class TestDottedNamespaces:
    """Tests for hierarchical dotted namespace support."""

    def test_register_with_dotted_namespace(self, initialized_catalog, sample_geoparquet):
        """Register a resource using a dotted namespace."""
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=initialized_catalog.path.parent):
            result = runner.invoke(
                cli,
                [
                    "register", "file",
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
                    "register", "file",
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
            # Register resources in dotted namespaces
            runner.invoke(
                cli,
                ["register", "file", str(sample_geoparquet), "--name", "fires",
                 "--namespace", "europe.spain"],
                catch_exceptions=False,
            )
            runner.invoke(
                cli,
                ["register", "file", str(sample_geoparquet), "--name", "cities",
                 "--namespace", "europe.france"],
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
                    "register", "file",
                    str(sample_geoparquet),
                    "--name", "test",
                    "--namespace", "my_server.data_folder",
                ],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
