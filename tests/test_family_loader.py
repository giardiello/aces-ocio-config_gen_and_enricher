import pytest
from pathlib import Path
import tempfile
import os

from ocio_vendor_extensions.family_loader import FamilyManifest, load_manifest, load_family, discover_families


class TestFamilyManifest:
    def test_valid_manifest(self, tmp_path):
        yaml_content = """
schema_version: 1
family: testfamily
description: "Test family"
depends_on: []
display_mappings:
  "Test : sRGB View":
    - "sRGB - Display"
intermediates:
  - "Test : Intermediate"
"""
        p = tmp_path / "family.yaml"
        p.write_text(yaml_content)
        m = load_manifest(p)
        assert m.family == "testfamily"
        assert m.depends_on == []
        assert "Test : sRGB View" in m.display_mappings
        assert m.intermediates == ["Test : Intermediate"]

    def test_missing_family_field(self, tmp_path):
        from pydantic import ValidationError
        p = tmp_path / "family.yaml"
        p.write_text("schema_version: 1\ndescription: no family\n")
        with pytest.raises(ValidationError):
            load_manifest(p)

    def test_invalid_yaml(self, tmp_path):
        p = tmp_path / "family.yaml"
        p.write_text("{{invalid yaml")
        with pytest.raises(RuntimeError):
            load_manifest(p)

    def test_extra_keys_ignored(self, tmp_path):
        yaml_content = """
schema_version: 1
family: testfamily
future_field: something
display_mappings: {}
intermediates: []
"""
        p = tmp_path / "family.yaml"
        p.write_text(yaml_content)
        m = load_manifest(p)
        assert m.family == "testfamily"


class TestDiscoverFamilies:
    def test_discover_finds_families(self, tmp_path):
        fam_dir = tmp_path / "families" / "myfam"
        fam_dir.mkdir(parents=True)
        (fam_dir / "family.yaml").write_text(
            "schema_version: 1\nfamily: myfam\ndisplay_mappings: {}\nintermediates: []\n"
        )
        result = discover_families(tmp_path / "families")
        assert "myfam" in result

    def test_discover_skips_dirs_without_yaml(self, tmp_path):
        fam_dir = tmp_path / "families" / "noyaml"
        fam_dir.mkdir(parents=True)
        result = discover_families(tmp_path / "families")
        assert "noyaml" not in result
