#!/usr/bin/env python3
"""Reformat CLF (Common LUT Format) XML files with proper indentation.

Usage:
    python scripts/format_clf.py file.clf [file2.clf ...]
    python scripts/format_clf.py --dir ocio_vendor_extensions/families/
"""
import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ET.register_namespace("", "urn:AMPAS:CLF:v3.0")
ET.register_namespace("", "urn:AMPAS:CLF:v2.0")


def _detect_clf_namespace(path: Path) -> str | None:
    """Return the CLF default namespace URI if present in the raw XML, else None."""
    with open(path, "r", encoding="utf-8") as f:
        head = f.read(2048)
    m = re.search(r'xmlns="(urn:AMPAS:CLF:v[^"]+)"', head)
    return m.group(1) if m else None


def format_clf(path: Path) -> bool:
    """Reformat a single CLF file in-place. Returns True on success."""
    try:
        ns_uri = _detect_clf_namespace(path)

        tree = ET.parse(path)
        ET.indent(tree, space="    ")
        tree.write(path, xml_declaration=True, encoding="UTF-8")

        text = path.read_text(encoding="utf-8")
        needs_write = False

        if "ns0:" in text:
            text = text.replace("ns0:", "")
            text = re.sub(r'\s+xmlns:ns0="[^"]*"', "", text)
            needs_write = True

        if ns_uri and f'xmlns="{ns_uri}"' not in text:
            text = text.replace("<ProcessList", f'<ProcessList xmlns="{ns_uri}"', 1)
            needs_write = True

        if needs_write:
            path.write_text(text, encoding="utf-8")

        return True
    except ET.ParseError as e:
        print(f"  ERROR parsing {path}: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Reformat CLF XML files with proper indentation")
    parser.add_argument("files", nargs="*", type=Path, help="CLF files to format")
    parser.add_argument("--dir", type=Path, help="Recursively format all .clf files under this directory")
    args = parser.parse_args()

    targets: list[Path] = []
    if args.dir:
        targets.extend(sorted(args.dir.rglob("*.clf")))
    targets.extend(args.files)

    if not targets:
        parser.print_help()
        return 1

    ok = 0
    fail = 0
    for p in targets:
        if format_clf(p):
            ok += 1
        else:
            fail += 1

    print(f"Formatted {ok} CLF file(s)", end="")
    if fail:
        print(f", {fail} failed", end="")
    print()
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
