import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


class TestExtendCLI:
    def test_list_families(self):
        result = subprocess.run(
            [sys.executable, "-m", "ocio_aces_tools", "extend", "--list-families"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_missing_input(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ocio_aces_tools",
                "extend",
                "-i",
                "nonexistent.ocio",
                "--families",
                "arri",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
