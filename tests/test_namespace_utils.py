"""Tests for namespace_utils module."""

import pytest

from namespace_utils import (
    arcgis_folder_to_namespace,
    build_namespace_tree,
    namespace_depth,
    namespace_parts,
    namespace_to_iceberg,
    validate_namespace,
)


class TestValidateNamespace:
    """Tests for validate_namespace()."""

    def test_valid_simple(self):
        assert validate_namespace("default") is None

    def test_valid_with_digits(self):
        assert validate_namespace("europe2") is None

    def test_valid_with_underscores(self):
        assert validate_namespace("test_arcgis") is None

    def test_valid_dotted(self):
        assert validate_namespace("europe.spain.madrid") is None

    def test_valid_dotted_with_digits(self):
        assert validate_namespace("region1.area2") is None

    def test_valid_dotted_with_underscores(self):
        assert validate_namespace("my_server.folder_a") is None

    def test_empty(self):
        assert validate_namespace("") is not None

    def test_leading_dot(self):
        error = validate_namespace(".europe")
        assert error is not None
        assert "start or end" in error

    def test_trailing_dot(self):
        error = validate_namespace("europe.")
        assert error is not None
        assert "start or end" in error

    def test_consecutive_dots(self):
        error = validate_namespace("europe..spain")
        assert error is not None
        assert "consecutive" in error

    def test_uppercase(self):
        error = validate_namespace("Europe")
        assert error is not None
        assert "lowercase" in error.lower()

    def test_special_chars(self):
        error = validate_namespace("europe-spain")
        assert error is not None

    def test_segment_starts_with_digit(self):
        error = validate_namespace("europe.1spain")
        assert error is not None
        assert "start with a letter" in error

    def test_spaces(self):
        error = validate_namespace("europe spain")
        assert error is not None


class TestNamespaceToIceberg:
    """Tests for namespace_to_iceberg()."""

    def test_simple_passthrough(self):
        assert namespace_to_iceberg("default") == "default"

    def test_dotted_to_underscored(self):
        assert namespace_to_iceberg("europe.spain.madrid") == "europe_spain_madrid"

    def test_single_dot(self):
        assert namespace_to_iceberg("a.b") == "a_b"

    def test_with_underscores(self):
        assert namespace_to_iceberg("my_ns.sub_ns") == "my_ns_sub_ns"


class TestNamespaceParts:
    """Tests for namespace_parts()."""

    def test_simple(self):
        assert namespace_parts("default") == ["default"]

    def test_dotted(self):
        assert namespace_parts("europe.spain.madrid") == ["europe", "spain", "madrid"]

    def test_two_parts(self):
        assert namespace_parts("a.b") == ["a", "b"]


class TestNamespaceDepth:
    """Tests for namespace_depth()."""

    def test_depth_one(self):
        assert namespace_depth("default") == 1

    def test_depth_two(self):
        assert namespace_depth("europe.spain") == 2

    def test_depth_three(self):
        assert namespace_depth("europe.spain.madrid") == 3


class TestBuildNamespaceTree:
    """Tests for build_namespace_tree()."""

    def test_single_flat(self):
        tree = build_namespace_tree(["default"])
        assert tree == {"default": {}}

    def test_multiple_flat(self):
        tree = build_namespace_tree(["default", "public"])
        assert tree == {"default": {}, "public": {}}

    def test_nested(self):
        tree = build_namespace_tree(["europe.spain.madrid", "europe.france", "default"])
        assert tree == {
            "default": {},
            "europe": {
                "france": {},
                "spain": {
                    "madrid": {},
                },
            },
        }

    def test_shared_prefix(self):
        tree = build_namespace_tree(["a.b.c", "a.b.d", "a.e"])
        assert tree == {
            "a": {
                "b": {
                    "c": {},
                    "d": {},
                },
                "e": {},
            },
        }

    def test_empty(self):
        tree = build_namespace_tree([])
        assert tree == {}


class TestArcgisFolderToNamespace:
    """Tests for arcgis_folder_to_namespace()."""

    def test_no_folder(self):
        assert arcgis_folder_to_namespace("arcgis", "") == "arcgis"

    def test_single_folder(self):
        assert arcgis_folder_to_namespace("arcgis", "Environment") == "arcgis.environment"

    def test_nested_folder(self):
        assert arcgis_folder_to_namespace("arcgis", "Environment/Water") == "arcgis.environment.water"

    def test_folder_with_spaces(self):
        result = arcgis_folder_to_namespace("myserver", "Folder 1/Sub Folder")
        assert result == "myserver.folder1.subfolder"

    def test_folder_starting_with_digit(self):
        result = arcgis_folder_to_namespace("arcgis", "1Data")
        assert result == "arcgis.f1data"

    def test_folder_with_trailing_slash(self):
        result = arcgis_folder_to_namespace("arcgis", "Environment/")
        assert result == "arcgis.environment"
