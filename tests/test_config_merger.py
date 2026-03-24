import pytest
from pathlib import Path
import PyOpenColorIO as OCIO

from ocio_vendor_extensions.config_merger import (
    merge_colorspaces,
    copy_luts,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestMergeColorspaces:
    def test_adds_new_colorspace(self):
        base = OCIO.Config.CreateFromFile(str(FIXTURES / "base_config.ocio"))
        snippet = OCIO.Config.CreateFromFile(
            str(FIXTURES / "snippet_family" / "colorspaces.ocio")
        )
        allowed = {"TestFam : sRGB View"}
        added = merge_colorspaces(base, snippet, allowed)
        assert "TestFam : sRGB View" in added
        assert base.getColorSpace("TestFam : sRGB View") is not None

    def test_skips_existing_colorspace(self):
        base = OCIO.Config.CreateFromFile(str(FIXTURES / "base_config.ocio"))
        snippet = OCIO.Config.CreateFromFile(
            str(FIXTURES / "snippet_family" / "colorspaces.ocio")
        )
        allowed = {"ACES2065-1"}
        added = merge_colorspaces(base, snippet, allowed)
        assert "ACES2065-1" not in added

    def test_ignores_unlisted_colorspace(self):
        base = OCIO.Config.CreateFromFile(str(FIXTURES / "base_config.ocio"))
        snippet = OCIO.Config.CreateFromFile(
            str(FIXTURES / "snippet_family" / "colorspaces.ocio")
        )
        allowed = set()
        added = merge_colorspaces(base, snippet, allowed)
        assert len(added) == 0


class TestCopyLuts:
    def test_copies_files(self, tmp_path):
        src_dir = tmp_path / "src_luts"
        src_dir.mkdir()
        (src_dir / "test.cube").write_text("LUT data")
        dst_dir = tmp_path / "dst_luts"
        dst_dir.mkdir()
        copied = copy_luts(["test.cube"], src_dir, dst_dir)
        assert (dst_dir / "test.cube").exists()
        assert len(copied) == 1

    def test_skips_existing(self, tmp_path):
        src_dir = tmp_path / "src_luts"
        src_dir.mkdir()
        (src_dir / "test.cube").write_text("LUT data")
        dst_dir = tmp_path / "dst_luts"
        dst_dir.mkdir()
        (dst_dir / "test.cube").write_text("existing")
        copied = copy_luts(["test.cube"], src_dir, dst_dir)
        assert len(copied) == 0
        assert (dst_dir / "test.cube").read_text() == "existing"
