#!/usr/bin/env python3
"""Generate OCIO reference mapping CSVs from transforms.json.

Reads the ACES transforms registry and produces CSV files matching the format
expected by OpenColorIO-Config-ACES's reference config generator.

Columns that can be inferred (ACEStransformID, Colorspace, Interface, Encoding,
Categories, Ordering) are auto-filled; OCIO-specific columns (BuiltinTransform
Style, Linked DisplayColorSpace Style, Aliases, InteropId) are populated from
an existing template CSV when a matching URN is found, or left empty for manual
editing.

Usage:
    python generate_mapping_csv.py transforms.json --version v1.3.1 -o output/
    python generate_mapping_csv.py transforms.json --version v2.0.0+2025.04.04 -o output/
    python generate_mapping_csv.py transforms.json --version v1.3.1 --template existing.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

try:
    import PyOpenColorIO as ocio

    HAS_OCIO = True
except ImportError:
    HAS_OCIO = False

HEADER = [
    "Ordering",
    "ACEStransformID",
    "Colorspace",
    "Legacy",
    "BuiltinTransform Style",
    "Linked DisplayColorSpace Style",
    "Interface",
    "ViewingRule",
    "Encoding",
    "Categories",
    "Aliases",
    "InteropId",
]

INCLUDED_TYPES_V2 = {"CSC", "Output", "Look"}
INCLUDED_TYPES_V1 = {"ACEScsc", "ODT", "RRTODT", "LMT"}

FORWARD_CSC_PATTERN = re.compile(r"_to_ACES\b")

TYPE_TO_INTERFACE = {
    "CSC": "ColorSpace",
    "ACEScsc": "ColorSpace",
    "Output": "ViewTransform",
    "ODT": "ViewTransform",
    "RRTODT": "ViewTransform",
    "Look": "Look",
    "LMT": "Look",
}

ORDERING_BANDS = {
    "CSC": 100,
    "ACEScsc": 100,
    "Look": 300,
    "LMT": 300,
    "Output": 400,
    "ODT": 400,
    "RRTODT": 440,
}

CORE_ACES_NAMES = {"ACEScc", "ACEScct", "ACEScg", "ADX10", "ADX16"}

VENDOR_ORDERING = {
    "Apple": 105,
    "Arri": 110,
    "BMD": 115,
    "Blackmagic": 115,
    "Canon": 120,
    "DJI": 125,
    "Panasonic": 130,
    "Red": 135,
    "Sony": 140,
    "Venice": 140,
}


def is_forward_csc(transform_id: str, transform_type: str) -> bool:
    if transform_type in ("CSC", "ACEScsc"):
        return bool(FORWARD_CSC_PATTERN.search(transform_id))
    return True


def guess_encoding(transform: dict) -> str:
    tid = transform["transformId"]
    ttype = transform["transformType"]
    name = transform.get("userName", "")

    if ttype in ("CSC", "ACEScsc"):
        if "ACEScg" in tid:
            return "scene-linear"
        return "log"
    if ttype in ("Output", "ODT", "RRTODT"):
        lower = (tid + name).lower()
        if "hlg" in lower:
            return "hdr-video"
        if "st2084" in lower or "pq" in lower:
            nit_match = re.search(r"(\d+)nit", lower)
            if nit_match:
                nits = int(nit_match.group(1))
                if nits > 108:
                    return "hdr-video"
            return "hdr-video"
        if "hdr" in lower:
            if "edr" in lower or "1000" in lower:
                return "edr-video"
            return "hdr-video"
        return "sdr-video"
    return ""


def guess_categories(transform: dict) -> str:
    ttype = transform["transformType"]
    tid = transform["transformId"]

    if ttype in ("CSC", "ACEScsc"):
        if "ACEScct" in tid:
            return "file-io,working-space"
        if "ACEScg" in tid:
            return "file-io,working-space,texture"
        return "file-io"
    if ttype in ("Output", "ODT", "RRTODT"):
        return "file-io"
    return ""


def guess_colorspace(transform: dict, is_v2: bool) -> str:
    ttype = transform["transformType"]
    tid = transform["transformId"]
    name = transform.get("userName", "")

    if ttype in ("CSC", "ACEScsc"):
        for core in CORE_ACES_NAMES:
            if core in tid:
                return f"ACES - {core}" if "ADX" not in core else f"Input - ADX - {core}"
        return ""

    if ttype in ("Output", "ODT", "RRTODT"):
        if is_v2:
            return ""
        cleaned = name.replace("ACES 1.0 Output - ", "Output - ")
        cleaned = cleaned.replace("ACES 1.3 Output - ", "Output - ")
        return cleaned

    if ttype in ("Look", "LMT"):
        if "BlueLightArtifact" in tid:
            return "Utility - Look - Blue Light Artifact Fix"
        return ""

    return ""


def guess_legacy(transform: dict) -> str:
    tid = transform["transformId"]
    for core in CORE_ACES_NAMES:
        if core in tid:
            return "TRUE"
    if "BlueLightArtifact" in tid:
        return "TRUE"
    return "FALSE"


def guess_ordering(transform: dict) -> int:
    ttype = transform["transformType"]
    tid = transform["transformId"]

    base = ORDERING_BANDS.get(ttype, 500)

    if ttype in ("CSC", "ACEScsc"):
        for core in CORE_ACES_NAMES:
            if core in tid:
                return 100
        for vendor, order in VENDOR_ORDERING.items():
            if vendor.lower() in tid.lower():
                return order
        return base

    return base


def guess_viewing_rule(transform: dict, is_v2: bool) -> str:
    ttype = transform["transformType"]
    if ttype in ("Output", "ODT", "RRTODT") and is_v2:
        return "Any Scene-linear or Log"
    return ""


def get_builtin_styles() -> dict[str, str]:
    """Return a dict mapping lowercase style to actual style from OCIO registry."""
    if not HAS_OCIO:
        return {}
    bt = ocio.BuiltinTransformRegistry()
    return {s.lower(): s for s in bt}


def guess_builtin_style(transform: dict, builtin_styles: dict[str, str]) -> str:
    """Try to match a transform to an OCIO builtin style by name patterns."""
    tid = transform["transformId"]
    ttype = transform["transformType"]

    if ttype in ("CSC", "ACEScsc"):
        local = tid.rsplit(":", 1)[-1]
        parts = local.split(".")
        if len(parts) >= 3:
            func_name = parts[2]
            version_stripped = re.sub(r"\.a\d.*$", "", func_name)
            candidate = version_stripped.replace("_to_ACES", "_to_ACES2065-1")
            for low, actual in builtin_styles.items():
                if low == candidate.lower():
                    return actual
            candidate_upper = candidate.upper().replace("_TO_ACES2065-1", "_to_ACES2065-1")
            for low, actual in builtin_styles.items():
                if low == candidate_upper.lower():
                    return actual
    return ""


def load_template(csv_path: Path) -> dict[str, dict]:
    """Load an existing CSV as a URN-keyed lookup for OCIO-specific columns."""
    lookup = {}
    with open(csv_path) as f:
        reader = csv.DictReader(f, fieldnames=HEADER)
        next(reader)
        for row in reader:
            urn = row.get("ACEStransformID", "").strip()
            if urn:
                lookup[urn] = row
    return lookup


def build_equivalent_lookup(
    transforms: list[dict], template: dict[str, dict]
) -> dict[str, dict]:
    """For transforms not directly in the template, check if any of their
    previousEquivalentTransformIds match a template row."""
    equiv_lookup = {}
    for t in transforms:
        tid = t["transformId"]
        if tid in template:
            continue
        for eq_id in t.get("previousEquivalentTransformIds", []):
            if eq_id in template:
                equiv_lookup[tid] = template[eq_id]
                break
    return equiv_lookup


def generate_csv(
    transforms_json: Path,
    version_key: str,
    output_path: Path,
    template_paths: list[Path] | None = None,
) -> None:
    with open(transforms_json) as f:
        all_data = json.load(f)

    transforms_data = all_data.get("transformsData", {})
    if version_key not in transforms_data:
        print(f"Error: version '{version_key}' not found. Available: {list(transforms_data.keys())}")
        sys.exit(1)

    transforms = transforms_data[version_key]["transforms"]
    is_v2 = version_key.startswith("v2")
    included_types = INCLUDED_TYPES_V2 if is_v2 else INCLUDED_TYPES_V1

    template: dict[str, dict] = {}
    for tp in (template_paths or []):
        template.update(load_template(tp))
    builtin_styles = get_builtin_styles()

    filtered = [t for t in transforms if t["transformType"] in included_types and is_forward_csc(t["transformId"], t["transformType"])]
    equiv_lookup = build_equivalent_lookup(filtered, template)

    rows = []
    for t in filtered:
        ttype = t["transformType"]
        tid = t["transformId"]

        tmpl = template.get(tid, equiv_lookup.get(tid, {}))

        builtin = tmpl.get("BuiltinTransform Style", "")
        if not builtin:
            builtin = guess_builtin_style(t, builtin_styles)

        row = {
            "Ordering": tmpl.get("Ordering") or str(guess_ordering(t)),
            "ACEStransformID": tid,
            "Colorspace": tmpl.get("Colorspace") or guess_colorspace(t, is_v2),
            "Legacy": tmpl.get("Legacy") or guess_legacy(t),
            "BuiltinTransform Style": builtin,
            "Linked DisplayColorSpace Style": tmpl.get("Linked DisplayColorSpace Style", ""),
            "Interface": tmpl.get("Interface") or TYPE_TO_INTERFACE.get(ttype, ""),
            "ViewingRule": tmpl.get("ViewingRule") or guess_viewing_rule(t, is_v2),
            "Encoding": tmpl.get("Encoding") or guess_encoding(t),
            "Categories": tmpl.get("Categories") or guess_categories(t),
            "Aliases": tmpl.get("Aliases", ""),
            "InteropId": tmpl.get("InteropId", ""),
        }
        rows.append(row)

    rows.sort(key=lambda r: (int(r["Ordering"]), r["ACEStransformID"]))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)

    filled = sum(1 for r in rows if r["BuiltinTransform Style"])
    empty_bt = [r for r in rows if not r["BuiltinTransform Style"]]
    print(f"Wrote {len(rows)} rows to {output_path}")
    print(f"  {filled} rows fully populated (BuiltinTransform Style present)")
    print(f"  {len(empty_bt)} rows need manual BuiltinTransform Style:")
    for r in empty_bt:
        print(f"    [{r['Interface']}] {r['ACEStransformID']}")


def main():
    parser = argparse.ArgumentParser(description="Generate OCIO mapping CSV from transforms.json")
    parser.add_argument("transforms_json", type=Path, help="Path to transforms.json")
    parser.add_argument("--version", required=True, help="Version key (e.g. v1.3.1, v2.0.0+2025.04.04)")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Output CSV path")
    parser.add_argument("--template", type=Path, nargs="+", help="Existing CSV(s) to use as template for OCIO-specific columns")
    args = parser.parse_args()

    generate_csv(args.transforms_json, args.version, args.output, args.template)


if __name__ == "__main__":
    main()
