#!/usr/bin/env python3
"""Legacy entry: python extend_ocio_config.py -> same as python -m ocio_aces_tools extend"""
if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.argv = ["ocio_aces_tool", "extend"] + sys.argv[1:]
    from ocio_aces_tools.cli import main

    sys.exit(main())
