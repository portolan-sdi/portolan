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
