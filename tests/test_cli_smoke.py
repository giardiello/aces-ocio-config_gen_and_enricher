"""Smoke tests: each CLI subcommand --help exits 0.

Note: Tests that delegate to upgrade/map/validate-amf/enrich/lut-build/lut-verify/repo
import the underlying scripts, which require PyOpenColorIO. Run with pytest -v;
if PyOpenColorIO is not installed, test_cli_help and test_subcommand_help_split
still run (split uses the CLI's own parser for --help).
"""
import subprocess
import sys
from pathlib import Path

# Repo root
ROOT = Path(__file__).resolve().parent.parent


def _run_cli(subcommand_argv):
    cmd = [sys.executable, "-m", "ocio_aces_tools"] + subcommand_argv
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def test_cli_help():
    code, out, err = _run_cli(["--help"])
    assert code == 0, f"cli --help failed: {err}"
    assert "upgrade" in out and "map" in out and "validate-amf" in out


def test_subcommand_help_upgrade():
    code, out, err = _run_cli(["upgrade", "--help"])
    assert code == 0, f"upgrade --help failed: {err}"


def test_subcommand_help_map():
    code, out, err = _run_cli(["map", "--help"])
    assert code == 0, f"map --help failed: {err}"


def test_subcommand_help_validate_amf():
    code, out, err = _run_cli(["validate-amf", "--help"])
    assert code == 0, f"validate-amf --help failed: {err}"


def test_subcommand_help_split():
    code, out, err = _run_cli(["split", "--help"])
    assert code == 0, f"split --help failed: {err}"


def test_subcommand_help_enrich():
    code, out, err = _run_cli(["enrich", "--help"])
    assert code == 0, f"enrich --help failed: {err}"


def test_subcommand_help_lut_build():
    code, out, err = _run_cli(["lut-build", "--help"])
    assert code == 0, f"lut-build --help failed: {err}"


def test_subcommand_help_lut_verify():
    code, out, err = _run_cli(["lut-verify", "--help"])
    assert code == 0, f"lut-verify --help failed: {err}"


def test_subcommand_help_repo_extract():
    code, out, err = _run_cli(["repo", "extract", "--help"])
    assert code == 0, f"repo extract --help failed: {err}"


def test_subcommand_help_repo_compare():
    code, out, err = _run_cli(["repo", "compare", "--help"])
    assert code == 0, f"repo compare --help failed: {err}"
