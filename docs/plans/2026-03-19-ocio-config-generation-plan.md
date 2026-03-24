# OCIO Multi-Version Config Generation -- Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Generate 24 OCIO configs covering ACES 2.0, ACES 1.3.1, and combined 1.3+2.0 for both OCIO v2.5 and v2.3, in CG and Studio variants (default + all-views).

**Architecture:** Fork upstream `OpenColorIO-Config-ACES` at `v4.0.0`. All changes are in CSV mapping files, `BUILD_CONFIGURATIONS`, CLF baking, and a new invoke task. Core generation code is untouched.

**Tech Stack:** Python 3.11+, PyOpenColorIO >= 2.4, invoke, numpy, git

**Design doc:** `docs/plans/2026-03-19-ocio-config-generation-design.md`

---

## Task 1: Fork and set up the upstream repo

**Files:**
- Clone: `~/Dev_prj/OpenColorIO-Config-ACES/` (new directory)

**Step 1: Fork the upstream repo**

```bash
cd ~/Dev_prj
git clone https://github.com/AcademySoftwareFoundation/OpenColorIO-Config-ACES.git
cd OpenColorIO-Config-ACES
git checkout v4.0.0
git checkout -b multi-version-configs
```

**Step 2: Initialize the aces-dev submodule**

```bash
git submodule update --init --recursive
```

**Step 3: Install dependencies**

```bash
pip install -e ".[development]"
```

**Step 4: Verify the baseline build works**

```bash
cd opencolorio_config_aces/config/cg/generate
python config.py
```

Expected: generates ACES 2.0 CG configs in `build/` without errors.

**Step 5: Commit**

```bash
git add -A
git commit -m "chore: baseline fork from v4.0.0"
```

---

## Task 2: Fetch and normalize the ACES 1.3 Reference CSV

**Files:**
- Source: tag `v2.1.0-v2.2.0` file `opencolorio_config_aces/config/reference/generate/resources/OpenColorIO-Config-ACES Reference Transforms - v2 - Reference Config - Mapping.csv`
- Create: `opencolorio_config_aces/config/reference/generate/resources/Reference Config - ACES 1.3 - Mapping.csv`

The v2.2.0 Reference CSV has this schema:
```
Ordering,ACEStransformID,Colorspace,Legacy,BuiltinTransform Style,Linked DisplayColorSpace Style,Interface,Encoding,Categories,Aliases
```

The v4.0.0 Reference CSV has this schema:
```
Ordering,ACEStransformID,Colorspace,Legacy,BuiltinTransform Style,Linked DisplayColorSpace Style,Interface,ViewingRule,Encoding,Categories,Aliases,InteropId
```

**Step 1: Extract the old CSV from git history**

```bash
cd ~/Dev_prj/OpenColorIO-Config-ACES
git show v2.1.0-v2.2.0:"opencolorio_config_aces/config/reference/generate/resources/OpenColorIO-Config-ACES Reference Transforms - v2 - Reference Config - Mapping.csv" > /tmp/aces13_ref_raw.csv
```

**Step 2: Write a normalization script**

Create: `scripts/normalize_csv.py`

```python
"""Normalize an ACES 1.3 Reference CSV from v2.2.0 schema to v4.0.0 schema.

Adds missing columns: ViewingRule, InteropId (both empty).
Reorders columns to match v4.0.0 header.
"""

import csv
import sys

V4_HEADERS = [
    "Ordering", "ACEStransformID", "Colorspace", "Legacy",
    "BuiltinTransform Style", "Linked DisplayColorSpace Style",
    "Interface", "ViewingRule", "Encoding", "Categories", "Aliases",
    "InteropId",
]

def normalize(src, dst):
    with open(src, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        with open(dst, "w", newline="", encoding="utf-8") as out:
            writer = csv.DictWriter(out, fieldnames=V4_HEADERS)
            writer.writeheader()
            for row in reader:
                normalized = {}
                for h in V4_HEADERS:
                    normalized[h] = row.get(h, "")
                writer.writerow(normalized)

if __name__ == "__main__":
    normalize(sys.argv[1], sys.argv[2])
```

**Step 3: Run normalization**

```bash
python scripts/normalize_csv.py /tmp/aces13_ref_raw.csv \
  "opencolorio_config_aces/config/reference/generate/resources/Reference Config - ACES 1.3 - Mapping.csv"
```

**Step 4: Verify the normalized CSV**

```bash
head -3 "opencolorio_config_aces/config/reference/generate/resources/Reference Config - ACES 1.3 - Mapping.csv"
```

Expected: header matches v4.0.0 schema exactly, data rows have empty `ViewingRule` and `InteropId`.

**Step 5: Commit**

```bash
git add scripts/normalize_csv.py "opencolorio_config_aces/config/reference/generate/resources/Reference Config - ACES 1.3 - Mapping.csv"
git commit -m "feat: add normalized ACES 1.3 Reference CSV in v4.0.0 schema"
```

---

## Task 3: Audit transforms.json for missing input transforms

**Files:**
- Read: `~/Dev_prj/OCIO_ACES_MERGER_AND_PARSER/transforms.json`
- Read: ACES 2.0 Reference CSV (existing v4.0.0)
- Read: ACES 1.3 Reference CSV (from Task 2)
- Create: `scripts/audit_missing_transforms.py`

**Step 1: Write the audit script**

```python
"""Compare transforms.json CSC entries against Reference CSVs.

Reports input transforms (CSC type) that have a BuiltinTransform style
in OCIO but are missing from the Reference CSV.
"""

import csv
import json
import re
import sys
from pathlib import Path

import PyOpenColorIO as ocio

def get_all_builtin_styles():
    """Return set of all registered BuiltinTransform styles."""
    return set(ocio.BuiltinTransformRegistry())

def get_csv_styles(csv_path):
    """Return set of BuiltinTransform styles used in a CSV."""
    styles = set()
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            style = row.get("BuiltinTransform Style", "").strip()
            if style:
                styles.add(style)
    return styles

def get_csc_transforms(transforms_json_path, aces_version):
    """Return CSC transforms from transforms.json for a given ACES version."""
    with open(transforms_json_path) as f:
        data = json.load(f)
    transforms_data = data.get("transformsData", data)
    version_data = transforms_data.get(aces_version, {})
    return [
        t for t in version_data.get("transforms", [])
        if t.get("transformType") == "CSC"
    ]

def audit(transforms_json, csv_path, aces_version):
    builtins = get_all_builtin_styles()
    csv_styles = get_csv_styles(csv_path)
    csc_transforms = get_csc_transforms(transforms_json, aces_version)

    print(f"ACES version: {aces_version}")
    print(f"CSV styles count: {len(csv_styles)}")
    print(f"CSC transforms count: {len(csc_transforms)}")
    print()

    missing = []
    for t in csc_transforms:
        tid = t["transformId"]
        name = t.get("userName", tid)
        # Derive likely BuiltinTransform style from transform ID
        # CSC transforms typically map to styles like "CAMERA_to_ACES2065-1"
        # Check if any builtin contains the camera name
        found_in_csv = False
        for style in csv_styles:
            if style in tid or tid in style:
                found_in_csv = True
                break
        if not found_in_csv:
            # Check if there's a matching builtin
            matching_builtins = [
                b for b in builtins
                if name.replace(" ", "_").upper() in b.upper()
                or any(part in b for part in name.split() if len(part) > 3)
            ]
            if matching_builtins:
                missing.append((tid, name, matching_builtins))

    print("Potentially missing transforms:")
    for tid, name, builtins_list in missing:
        print(f"  {name}")
        print(f"    ID: {tid}")
        print(f"    Possible BuiltinTransform styles: {builtins_list}")
        print()

if __name__ == "__main__":
    audit(sys.argv[1], sys.argv[2], sys.argv[3])
```

**Step 2: Run audit for ACES 2.0**

```bash
python scripts/audit_missing_transforms.py \
  ~/Dev_prj/OCIO_ACES_MERGER_AND_PARSER/transforms.json \
  "opencolorio_config_aces/config/reference/generate/resources/Loading... - Reference Config - Mapping.csv" \
  "v2.0.0+2025.04.04"
```

**Step 3: Run audit for ACES 1.3**

```bash
python scripts/audit_missing_transforms.py \
  ~/Dev_prj/OCIO_ACES_MERGER_AND_PARSER/transforms.json \
  "opencolorio_config_aces/config/reference/generate/resources/Reference Config - ACES 1.3 - Mapping.csv" \
  "v1.3"
```

**Step 4: Review output and manually add missing transforms to CSVs**

For each missing CSC transform that has a valid BuiltinTransform style, add a row to the appropriate Reference CSV with:
- `Ordering`: 100 (standard for input transforms)
- `ACEStransformID`: the transform ID from transforms.json
- `Colorspace`: derived from userName (e.g., "Input - Sony - S-Log1")
- `Legacy`: TRUE
- `BuiltinTransform Style`: the matched style
- `Interface`: ColorSpace
- `Encoding`: log or scene-linear as appropriate
- `Categories`: file-io

**Step 5: Commit**

```bash
git add scripts/audit_missing_transforms.py
git add "opencolorio_config_aces/config/reference/generate/resources/"*.csv
git commit -m "feat: audit and add missing input transforms to Reference CSVs"
```

---

## Task 4: Build the combined ACES 1.3+2.0 Reference CSV

**Files:**
- Read: ACES 2.0 Reference CSV (v4.0.0, possibly updated from Task 3)
- Read: ACES 1.3 Reference CSV (from Task 2, possibly updated from Task 3)
- Create: `opencolorio_config_aces/config/reference/generate/resources/Reference Config - Combined ACES 1.3+2.0 - Mapping.csv`
- Create: `scripts/merge_reference_csvs.py`

**Step 1: Write the merge script**

```python
"""Merge ACES 2.0 and ACES 1.3 Reference CSVs into a combined superset.

Rules:
- ACES 2.0 CSV is the base (all rows included)
- ACES 1.3 output transforms (ViewTransform interface) are added
  since they use different BuiltinTransform styles (_1.0/_1.1 vs _2.0)
- ACES 1.3 input CSCs are included only if their BuiltinTransform style
  is NOT already present in the ACES 2.0 CSV (avoids duplicates)
- Looks from both versions are included
- Ordering is preserved; ACES 1.3 additions get ordering offset +10000
  to sort after ACES 2.0 equivalents
"""

import csv
import sys
from pathlib import Path

V4_HEADERS = [
    "Ordering", "ACEStransformID", "Colorspace", "Legacy",
    "BuiltinTransform Style", "Linked DisplayColorSpace Style",
    "Interface", "ViewingRule", "Encoding", "Categories", "Aliases",
    "InteropId",
]

def read_csv(path):
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows

def merge(aces20_path, aces13_path, output_path):
    aces20_rows = read_csv(aces20_path)
    aces13_rows = read_csv(aces13_path)

    # Collect ACES 2.0 BuiltinTransform styles for dedup
    aces20_styles = {
        row["BuiltinTransform Style"].strip()
        for row in aces20_rows
        if row.get("BuiltinTransform Style", "").strip()
    }

    combined = list(aces20_rows)

    for row in aces13_rows:
        style = row.get("BuiltinTransform Style", "").strip()
        interface = row.get("Interface", "").strip()

        # Always include output transforms (ViewTransform) -- different styles
        if interface == "ViewTransform":
            row["Ordering"] = str(int(row.get("Ordering", "0") or "0") + 10000)
            combined.append(row)
        # Include Looks
        elif interface == "Look":
            row["Ordering"] = str(int(row.get("Ordering", "0") or "0") + 10000)
            combined.append(row)
        # Include input CSCs only if style not already present
        elif interface == "ColorSpace" and style and style not in aces20_styles:
            row["Ordering"] = str(int(row.get("Ordering", "0") or "0") + 10000)
            combined.append(row)

    with open(output_path, "w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=V4_HEADERS, extrasaction="ignore")
        writer.writeheader()
        for row in combined:
            writer.writerow(row)

    print(f"Combined CSV: {len(combined)} rows ({len(aces20_rows)} from ACES 2.0 + {len(combined) - len(aces20_rows)} from ACES 1.3)")

if __name__ == "__main__":
    merge(sys.argv[1], sys.argv[2], sys.argv[3])
```

**Step 2: Run the merge**

```bash
python scripts/merge_reference_csvs.py \
  "opencolorio_config_aces/config/reference/generate/resources/Loading... - Reference Config - Mapping.csv" \
  "opencolorio_config_aces/config/reference/generate/resources/Reference Config - ACES 1.3 - Mapping.csv" \
  "opencolorio_config_aces/config/reference/generate/resources/Reference Config - Combined ACES 1.3+2.0 - Mapping.csv"
```

**Step 3: Verify the combined CSV**

```bash
wc -l "opencolorio_config_aces/config/reference/generate/resources/Reference Config - Combined ACES 1.3+2.0 - Mapping.csv"
# Should be > sum of unique rows from both
head -5 "opencolorio_config_aces/config/reference/generate/resources/Reference Config - Combined ACES 1.3+2.0 - Mapping.csv"
```

**Step 4: Commit**

```bash
git add scripts/merge_reference_csvs.py
git add "opencolorio_config_aces/config/reference/generate/resources/Reference Config - Combined ACES 1.3+2.0 - Mapping.csv"
git commit -m "feat: add combined ACES 1.3+2.0 Reference CSV"
```

---

## Task 5: Build CG and Studio CSVs for ACES 1.3 and combined variants

**Files:**
- Source: tag `v2.1.0-v2.2.0` CG/Studio CSVs
- Create: `opencolorio_config_aces/config/cg/generate/resources/CG Config - ACES 1.3 - Mapping.csv`
- Create: `opencolorio_config_aces/config/studio/generate/resources/Studio Config - ACES 1.3 - Mapping.csv`
- Create: `opencolorio_config_aces/config/cg/generate/resources/CG Config - Combined ACES 1.3+2.0 - Mapping.csv`
- Create: `opencolorio_config_aces/config/studio/generate/resources/Studio Config - Combined ACES 1.3+2.0 - Mapping.csv`
- Create: `scripts/normalize_cg_csv.py`
- Create: `scripts/merge_cg_csvs.py`

**Step 1: Extract old CG/Studio CSVs**

```bash
git show v2.1.0-v2.2.0:"opencolorio_config_aces/config/cg/generate/resources/OpenColorIO-Config-ACES CG and Studio Transforms - v2 - CG Config - Mapping.csv" > /tmp/aces13_cg_raw.csv
git show v2.1.0-v2.2.0:"opencolorio_config_aces/config/studio/generate/resources/OpenColorIO-Config-ACES CG and Studio Transforms - v2 - Studio Config - Mapping.csv" > /tmp/aces13_studio_raw.csv
```

**Step 2: Write CG/Studio CSV normalization script**

The v2.2.0 CG CSV schema:
```
Ordering,Colorspace,Legacy,ACEStransformID,CLFtransformID,Interface,BuiltinTransform Style,Aliases,Encoding,Categories
```

The v4.0.0 CG CSV schema:
```
Ordering,Colorspace,Legacy,ACEStransformID,CLFtransformID,Interface,BuiltinTransform Style,Aliases,Encoding,Categories,InteropId
```

```python
"""Normalize ACES 1.3 CG/Studio CSV from v2.2.0 schema to v4.0.0 schema.

Adds missing column: InteropId (empty).
"""

import csv
import sys

V4_CG_HEADERS = [
    "Ordering", "Colorspace", "Legacy", "ACEStransformID",
    "CLFtransformID", "Interface", "BuiltinTransform Style",
    "Aliases", "Encoding", "Categories", "InteropId",
]

def normalize(src, dst):
    with open(src, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        with open(dst, "w", newline="", encoding="utf-8") as out:
            writer = csv.DictWriter(out, fieldnames=V4_CG_HEADERS)
            writer.writeheader()
            for row in reader:
                normalized = {}
                for h in V4_CG_HEADERS:
                    normalized[h] = row.get(h, "")
                writer.writerow(normalized)

if __name__ == "__main__":
    normalize(sys.argv[1], sys.argv[2])
```

**Step 3: Normalize both CSVs**

```bash
python scripts/normalize_cg_csv.py /tmp/aces13_cg_raw.csv \
  "opencolorio_config_aces/config/cg/generate/resources/CG Config - ACES 1.3 - Mapping.csv"
python scripts/normalize_cg_csv.py /tmp/aces13_studio_raw.csv \
  "opencolorio_config_aces/config/studio/generate/resources/Studio Config - ACES 1.3 - Mapping.csv"
```

**Step 4: Write CG/Studio merge script**

Same logic as Reference merge but using CG/Studio headers. The merge script for CG/Studio CSVs follows the same deduplication rules: include all ACES 2.0 rows, add ACES 1.3 output transforms, add ACES 1.3 input CSCs only if their BuiltinTransform style is not already present.

```python
"""Merge ACES 2.0 and ACES 1.3 CG (or Studio) CSVs."""

import csv
import sys

V4_CG_HEADERS = [
    "Ordering", "Colorspace", "Legacy", "ACEStransformID",
    "CLFtransformID", "Interface", "BuiltinTransform Style",
    "Aliases", "Encoding", "Categories", "InteropId",
]

def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def merge(aces20_path, aces13_path, output_path):
    aces20_rows = read_csv(aces20_path)
    aces13_rows = read_csv(aces13_path)

    aces20_styles = {
        row["BuiltinTransform Style"].strip()
        for row in aces20_rows
        if row.get("BuiltinTransform Style", "").strip()
    }

    combined = list(aces20_rows)
    for row in aces13_rows:
        style = row.get("BuiltinTransform Style", "").strip()
        interface = row.get("Interface", "").strip()
        if interface in ("ViewTransform", "Look"):
            row["Ordering"] = str(int(row.get("Ordering", "0") or "0") + 10000)
            combined.append(row)
        elif interface == "ColorSpace" and style and style not in aces20_styles:
            row["Ordering"] = str(int(row.get("Ordering", "0") or "0") + 10000)
            combined.append(row)

    with open(output_path, "w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=V4_CG_HEADERS, extrasaction="ignore")
        writer.writeheader()
        for row in combined:
            writer.writerow(row)

    print(f"Combined: {len(combined)} rows")

if __name__ == "__main__":
    merge(sys.argv[1], sys.argv[2], sys.argv[3])
```

**Step 5: Run CG/Studio merges**

```bash
python scripts/merge_cg_csvs.py \
  "opencolorio_config_aces/config/cg/generate/resources/Loading... - CG Config - Mapping.csv" \
  "opencolorio_config_aces/config/cg/generate/resources/CG Config - ACES 1.3 - Mapping.csv" \
  "opencolorio_config_aces/config/cg/generate/resources/CG Config - Combined ACES 1.3+2.0 - Mapping.csv"

python scripts/merge_cg_csvs.py \
  "opencolorio_config_aces/config/studio/generate/resources/Loading... - Studio Config - Mapping.csv" \
  "opencolorio_config_aces/config/studio/generate/resources/Studio Config - ACES 1.3 - Mapping.csv" \
  "opencolorio_config_aces/config/studio/generate/resources/Studio Config - Combined ACES 1.3+2.0 - Mapping.csv"
```

**Step 6: Commit**

```bash
git add scripts/normalize_cg_csv.py scripts/merge_cg_csvs.py
git add "opencolorio_config_aces/config/cg/generate/resources/"*.csv
git add "opencolorio_config_aces/config/studio/generate/resources/"*.csv
git commit -m "feat: add ACES 1.3 and combined CG/Studio CSVs"
```

---

## Task 6: Extend BUILD_CONFIGURATIONS

**Files:**
- Modify: `opencolorio_config_aces/config/generation/configuration.py`

**Step 1: Add new build configurations**

Add entries for all 6 ACES/OCIO combinations. The `variant` field controls default vs all-views. Each entry needs a way to select the correct CSV. We add an optional `csv_label` field to `BuildConfiguration` to select the CSV file.

In `configuration.py`, extend the dataclass:

```python
@dataclass
class BuildConfiguration:
    aces: Version = field(default_factory=lambda: Version(0))
    colorspaces: Version = field(default_factory=lambda: Version(0))
    ocio: Version = field(default_factory=lambda: PROFILE_VERSION_DEFAULT)
    variant: str = field(default_factory=lambda: "")
    csv_label: str = field(default_factory=lambda: "")
```

Then extend `BUILD_CONFIGURATIONS`:

```python
BUILD_CONFIGURATIONS: list[BuildConfiguration] = [
    # --- ACES 2.0 / OCIO v2.5 (existing) ---
    BuildConfiguration(
        aces=Version(2, 0),
        colorspaces=Version(4, 0, 0),
        ocio=Version(2, 5),
        variant="",
    ),
    BuildConfiguration(
        aces=Version(2, 0),
        colorspaces=Version(4, 0, 0),
        ocio=Version(2, 5),
        variant="All Views",
    ),

    # --- ACES 1.3 / OCIO v2.5 ---
    BuildConfiguration(
        aces=Version(1, 3),
        colorspaces=Version(4, 0, 0),
        ocio=Version(2, 5),
        variant="",
        csv_label="ACES 1.3",
    ),
    BuildConfiguration(
        aces=Version(1, 3),
        colorspaces=Version(4, 0, 0),
        ocio=Version(2, 5),
        variant="All Views",
        csv_label="ACES 1.3",
    ),

    # --- Combined ACES 1.3+2.0 / OCIO v2.5 ---
    BuildConfiguration(
        aces=Version(2, 0),
        colorspaces=Version(4, 0, 0),
        ocio=Version(2, 5),
        variant="",
        csv_label="Combined ACES 1.3+2.0",
    ),
    BuildConfiguration(
        aces=Version(2, 0),
        colorspaces=Version(4, 0, 0),
        ocio=Version(2, 5),
        variant="All Views",
        csv_label="Combined ACES 1.3+2.0",
    ),

    # --- ACES 2.0 / OCIO v2.3 ---
    BuildConfiguration(
        aces=Version(2, 0),
        colorspaces=Version(4, 0, 0),
        ocio=Version(2, 3),
        variant="",
    ),
    BuildConfiguration(
        aces=Version(2, 0),
        colorspaces=Version(4, 0, 0),
        ocio=Version(2, 3),
        variant="All Views",
    ),

    # --- ACES 1.3 / OCIO v2.3 ---
    BuildConfiguration(
        aces=Version(1, 3),
        colorspaces=Version(4, 0, 0),
        ocio=Version(2, 3),
        variant="",
        csv_label="ACES 1.3",
    ),
    BuildConfiguration(
        aces=Version(1, 3),
        colorspaces=Version(4, 0, 0),
        ocio=Version(2, 3),
        variant="All Views",
        csv_label="ACES 1.3",
    ),

    # --- Combined ACES 1.3+2.0 / OCIO v2.3 ---
    BuildConfiguration(
        aces=Version(2, 0),
        colorspaces=Version(4, 0, 0),
        ocio=Version(2, 3),
        variant="",
        csv_label="Combined ACES 1.3+2.0",
    ),
    BuildConfiguration(
        aces=Version(2, 0),
        colorspaces=Version(4, 0, 0),
        ocio=Version(2, 3),
        variant="All Views",
        csv_label="Combined ACES 1.3+2.0",
    ),
]
```

Note: the "D60 Views" variant from upstream is dropped (user only needs default + all-views).

**Step 2: Update CSV selection logic in config generators**

In each generator (`reference/generate/config.py`, `cg/generate/config.py`, `studio/generate/config.py`), the CSV file is loaded by a hardcoded glob pattern. We need to modify the CSV selection to check `build_configuration.csv_label` and load the matching CSV file.

Find the CSV loading pattern in each generator (typically something like):
```python
csv_path = next(resources_directory.glob("*Mapping.csv"))
```

Replace with:
```python
label = getattr(build_configuration, "csv_label", "")
if label:
    csv_path = resources_directory / f"... - {label} - Mapping.csv"
else:
    csv_path = next(resources_directory.glob("*Mapping.csv"))
```

The exact pattern depends on the generator. Inspect each file and adapt.

**Step 3: Commit**

```bash
git add opencolorio_config_aces/config/generation/configuration.py
git add opencolorio_config_aces/config/reference/generate/config.py
git add opencolorio_config_aces/config/cg/generate/config.py
git add opencolorio_config_aces/config/studio/generate/config.py
git commit -m "feat: extend BUILD_CONFIGURATIONS for all ACES/OCIO combos"
```

---

## Task 7: Identify and bake CLF files for OCIO v2.3 targets

**Files:**
- Read: `opencolorio_config_aces/config/generation/factories.py` (BUILTIN_TRANSFORMS dict)
- Create: `scripts/bake_v23_clfs.py`
- Create: `opencolorio_config_aces/config/cg/generate/resources/clf/` (CLF output directory)

**Step 1: Identify transforms needing CLF fallback**

From `factories.py`, the following BuiltinTransforms require OCIO > v2.3:

| BuiltinTransform Style | Min OCIO Version |
|------------------------|------------------|
| All `ACES-OUTPUT - *_2.0` patterns | v2.4 |
| `APPLE_LOG_to_ACES2065-1` | v2.4 |
| `CURVE - APPLE_LOG_to_LINEAR` | v2.4 |
| `DJI_DLOG_to_ACES2065-1` (if present) | v2.5 |

All ACES 1.x BuiltinTransforms (`_1.0`, `_1.1`) are available at v2.3.

**Step 2: Write the CLF baking script**

This script reuses logic from `generate_lut_based_config.py` to bake each affected BuiltinTransform into a self-contained CLF file.

```python
"""Bake BuiltinTransforms unavailable at OCIO v2.3 into CLF files.

Output CLFs are placed in the CG resources directory for use by
v2.3-targeted CG/Studio CSVs.

Requires an OCIO >= 2.4 runtime to access the BuiltinTransforms.
"""

import os
import re
import sys
from pathlib import Path

import PyOpenColorIO as ocio

# Import baking utilities from existing script
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "OCIO_ACES_MERGER_AND_PARSER"))
# Alternatively, inline the baking logic

OUTPUT_DIR = Path(__file__).parent.parent / "opencolorio_config_aces/config/cg/generate/resources/clf"

def get_transforms_needing_clf():
    """Return list of (style, min_version) for transforms needing CLF at v2.3."""
    transforms = []
    for style in ocio.BuiltinTransformRegistry():
        if re.match(r"^ACES-OUTPUT - .*_2\.0$", style):
            transforms.append((style, "v2.4"))
    transforms.append(("APPLE_LOG_to_ACES2065-1", "v2.4"))
    transforms.append(("CURVE - APPLE_LOG_to_LINEAR", "v2.4"))
    return transforms

def bake_output_transform_clf(style, output_dir):
    """Bake an ACES output BuiltinTransform to a forward+inverse CLF pair."""
    # Use the same Matrix+Log+LUT3D structure as generate_lut_based_config.py
    # ... (implementation follows generate_lut_based_config.py patterns)
    pass

def bake_curve_clf(style, output_dir):
    """Bake a curve BuiltinTransform to a 1D LUT CLF."""
    # ... (implementation follows bake_1d_luts pattern)
    pass

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    transforms = get_transforms_needing_clf()
    for style, min_ver in transforms:
        print(f"Baking {style} (requires {min_ver})...")
        if style.startswith("ACES-OUTPUT"):
            bake_output_transform_clf(style, OUTPUT_DIR)
        elif style.startswith("CURVE"):
            bake_curve_clf(style, OUTPUT_DIR)
        else:
            bake_curve_clf(style, OUTPUT_DIR)  # CSC transforms use 1D approach

if __name__ == "__main__":
    main()
```

The actual baking implementation should be extracted/adapted from `generate_lut_based_config.py` lines 792-973. The key functions to reuse:
- `build_forward_clf()` for output transforms
- `bake_1d_luts()` for curve/CSC transforms

**Step 3: Run the baking**

```bash
python scripts/bake_v23_clfs.py
ls opencolorio_config_aces/config/cg/generate/resources/clf/
```

Expected: one CLF file per ACES 2.0 output transform, plus Apple Log CLFs.

**Step 4: Commit**

```bash
git add scripts/bake_v23_clfs.py
git add "opencolorio_config_aces/config/cg/generate/resources/clf/"
git commit -m "feat: bake CLF files for OCIO v2.3 fallbacks"
```

---

## Task 8: Create v2.3-targeted CG/Studio CSVs

**Files:**
- Read: ACES 2.0 CG CSV (v4.0.0)
- Read: ACES 1.3 CG CSV (from Task 5)
- Read: Combined CG CSV (from Task 5)
- Create: `scripts/create_v23_csvs.py`
- Create: v2.3-targeted CG/Studio CSVs for all 3 ACES variants

**Step 1: Write the v2.3 CSV creation script**

```python
"""Create v2.3-targeted CG/Studio CSVs by replacing unavailable
BuiltinTransform styles with CLFtransformID references.

For each row where the BuiltinTransform style requires OCIO > 2.3:
- Clear the 'BuiltinTransform Style' column
- Set 'CLFtransformID' to the corresponding CLF file path
"""

import csv
import re
import sys
from pathlib import Path

TRANSFORMS_NEEDING_CLF = set()
# Populated dynamically from OCIO registry
import PyOpenColorIO as ocio
for style in ocio.BuiltinTransformRegistry():
    if re.match(r"^ACES-OUTPUT - .*_2\.0$", style):
        TRANSFORMS_NEEDING_CLF.add(style)
TRANSFORMS_NEEDING_CLF.add("APPLE_LOG_to_ACES2065-1")
TRANSFORMS_NEEDING_CLF.add("CURVE - APPLE_LOG_to_LINEAR")

def style_to_clf_id(style):
    """Map a BuiltinTransform style to its CLFtransformID."""
    # The CLF files are named based on the style, sanitized
    sanitized = style.replace(" ", "_").replace("/", "_")
    return f"urn:aswf:ocio:transformId:v0.1:CLF.{sanitized}"

V4_CG_HEADERS = [
    "Ordering", "Colorspace", "Legacy", "ACEStransformID",
    "CLFtransformID", "Interface", "BuiltinTransform Style",
    "Aliases", "Encoding", "Categories", "InteropId",
]

def create_v23_csv(src_path, dst_path):
    rows = []
    with open(src_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            style = row.get("BuiltinTransform Style", "").strip()
            if style in TRANSFORMS_NEEDING_CLF:
                row["CLFtransformID"] = style_to_clf_id(style)
                row["BuiltinTransform Style"] = ""
            rows.append(row)

    with open(dst_path, "w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=V4_CG_HEADERS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    replaced = sum(1 for r in rows if r.get("CLFtransformID", ""))
    print(f"{dst_path}: {len(rows)} rows, {replaced} with CLF fallback")

if __name__ == "__main__":
    create_v23_csv(sys.argv[1], sys.argv[2])
```

**Step 2: Generate all v2.3 CSVs**

```bash
# CG CSVs
python scripts/create_v23_csvs.py \
  "opencolorio_config_aces/config/cg/generate/resources/Loading... - CG Config - Mapping.csv" \
  "opencolorio_config_aces/config/cg/generate/resources/CG Config - ACES 2.0 v2.3 - Mapping.csv"

python scripts/create_v23_csvs.py \
  "opencolorio_config_aces/config/cg/generate/resources/CG Config - ACES 1.3 - Mapping.csv" \
  "opencolorio_config_aces/config/cg/generate/resources/CG Config - ACES 1.3 v2.3 - Mapping.csv"

python scripts/create_v23_csvs.py \
  "opencolorio_config_aces/config/cg/generate/resources/CG Config - Combined ACES 1.3+2.0 - Mapping.csv" \
  "opencolorio_config_aces/config/cg/generate/resources/CG Config - Combined ACES 1.3+2.0 v2.3 - Mapping.csv"

# Studio CSVs (same logic)
python scripts/create_v23_csvs.py \
  "opencolorio_config_aces/config/studio/generate/resources/Loading... - Studio Config - Mapping.csv" \
  "opencolorio_config_aces/config/studio/generate/resources/Studio Config - ACES 2.0 v2.3 - Mapping.csv"

python scripts/create_v23_csvs.py \
  "opencolorio_config_aces/config/studio/generate/resources/Studio Config - ACES 1.3 - Mapping.csv" \
  "opencolorio_config_aces/config/studio/generate/resources/Studio Config - ACES 1.3 v2.3 - Mapping.csv"

python scripts/create_v23_csvs.py \
  "opencolorio_config_aces/config/studio/generate/resources/Studio Config - Combined ACES 1.3+2.0 - Mapping.csv" \
  "opencolorio_config_aces/config/studio/generate/resources/Studio Config - Combined ACES 1.3+2.0 v2.3 - Mapping.csv"
```

Note: ACES 1.3 v2.3 CSVs should have zero CLF replacements (all 1.x BuiltinTransforms are native at v2.3).

**Step 3: Commit**

```bash
git add scripts/create_v23_csvs.py
git add "opencolorio_config_aces/config/cg/generate/resources/"*.csv
git add "opencolorio_config_aces/config/studio/generate/resources/"*.csv
git commit -m "feat: add v2.3-targeted CG/Studio CSVs with CLF fallbacks"
```

---

## Task 9: Add the build-all-variants invoke task

**Files:**
- Modify: `tasks.py`

**Step 1: Add the new task**

```python
@task
def build_all_variants(ctx: Context) -> None:
    """
    Build all OCIO config variants (24 configs total).

    Generates CG and Studio configs for:
    - ACES 2.0 / OCIO v2.5 (default + all-views)
    - ACES 1.3 / OCIO v2.5 (default + all-views)
    - Combined ACES 1.3+2.0 / OCIO v2.5 (default + all-views)
    - ACES 2.0 / OCIO v2.3 (default + all-views)
    - ACES 1.3 / OCIO v2.3 (default + all-views)
    - Combined ACES 1.3+2.0 / OCIO v2.3 (default + all-views)
    """
    from opencolorio_config_aces.config.generation.configuration import (
        BUILD_CONFIGURATIONS,
    )

    message_box("Building all OCIO config variants...")

    for i, bc in enumerate(BUILD_CONFIGURATIONS):
        label = f"ACES {bc.aces} / OCIO {bc.ocio}"
        if bc.csv_label:
            label = f"{bc.csv_label} / OCIO {bc.ocio}"
        if bc.variant:
            label += f" ({bc.variant})"

        message_box(f"[{i+1}/{len(BUILD_CONFIGURATIONS)}] Building {label}...")

        # Build CG
        with ctx.cd("opencolorio_config_aces/config/cg/generate"):
            ctx.run(f"python config.py --build-index {i}")

        # Build Studio
        with ctx.cd("opencolorio_config_aces/config/studio/generate"):
            ctx.run(f"python config.py --build-index {i}")

    message_box(f"Done! Built {len(BUILD_CONFIGURATIONS)} config variants.")
```

Note: This requires adding `--build-index` CLI argument support to the CG and Studio generators, or alternatively iterating through `BUILD_CONFIGURATIONS` programmatically. The exact integration depends on how the generators accept build configuration parameters. Inspect the `if __name__ == "__main__"` block in each generator.

**Step 2: Commit**

```bash
git add tasks.py
git commit -m "feat: add build-all-variants invoke task"
```

---

## Task 10: Generate all 24 configs and validate

**Step 1: Run the full build**

```bash
invoke build-all-variants
```

Or, if the invoke task needs refinement, run each generator individually:

```bash
cd opencolorio_config_aces/config/cg/generate && python config.py
cd opencolorio_config_aces/config/studio/generate && python config.py
```

**Step 2: Validate each generated config**

```python
"""Validate all generated OCIO configs."""

import glob
import sys
import PyOpenColorIO as ocio

configs = glob.glob("build/**/*.ocio", recursive=True)
print(f"Found {len(configs)} configs")

errors = []
for path in sorted(configs):
    try:
        config = ocio.Config.CreateFromFile(path)
        config.validate()
        cs_count = config.getNumColorSpaces()
        vt_count = len(config.getViewTransforms())
        version = f"{config.getMajorVersion()}.{config.getMinorVersion()}"
        print(f"  OK: {path} (v{version}, {cs_count} colorspaces, {vt_count} view transforms)")
    except Exception as e:
        errors.append((path, str(e)))
        print(f"  FAIL: {path}: {e}")

if errors:
    print(f"\n{len(errors)} configs failed validation!")
    sys.exit(1)
else:
    print(f"\nAll {len(configs)} configs validated successfully.")
```

**Step 3: Spot-check transform counts**

Expected approximate counts per config type:

| Config | ACES 2.0 | ACES 1.3 | Combined |
|--------|----------|----------|----------|
| CG (default) | ~50 CS | ~45 CS | ~70 CS |
| CG (all-views) | ~50 CS | ~45 CS | ~70 CS |
| Studio (default) | ~80 CS | ~70 CS | ~120 CS |
| Studio (all-views) | ~80 CS | ~70 CS | ~120 CS |

The all-views variants should have more view transforms (D60 + D65) but same number of colorspaces.

**Step 4: Commit**

```bash
git add build/
git commit -m "feat: generate all 24 OCIO config variants"
```

---

## Summary of all files created/modified

### New scripts (in `scripts/`)
- `normalize_csv.py` -- normalize Reference CSV schema
- `normalize_cg_csv.py` -- normalize CG/Studio CSV schema
- `audit_missing_transforms.py` -- find missing input transforms
- `merge_reference_csvs.py` -- merge Reference CSVs
- `merge_cg_csvs.py` -- merge CG/Studio CSVs
- `create_v23_csvs.py` -- create v2.3-targeted CSVs with CLF fallbacks
- `bake_v23_clfs.py` -- bake CLF files for v2.3 targets

### New CSV files
- Reference: ACES 1.3, Combined ACES 1.3+2.0
- CG: ACES 1.3, Combined ACES 1.3+2.0, ACES 2.0 v2.3, ACES 1.3 v2.3, Combined v2.3
- Studio: ACES 1.3, Combined ACES 1.3+2.0, ACES 2.0 v2.3, ACES 1.3 v2.3, Combined v2.3

### Modified upstream files
- `opencolorio_config_aces/config/generation/configuration.py` -- extended BuildConfiguration + BUILD_CONFIGURATIONS
- `opencolorio_config_aces/config/reference/generate/config.py` -- CSV selection by label
- `opencolorio_config_aces/config/cg/generate/config.py` -- CSV selection by label
- `opencolorio_config_aces/config/studio/generate/config.py` -- CSV selection by label
- `tasks.py` -- new build-all-variants task

### New CLF files
- `opencolorio_config_aces/config/cg/generate/resources/clf/` -- baked CLFs for v2.3 targets
