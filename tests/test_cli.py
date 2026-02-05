"""
Tests for Portolan CLI commands.
"""

import json

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
            assert "Dataset added successfully" in result.output

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
