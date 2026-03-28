# Execution Plan: Unified ACES v1.x + v2.0 URN Support in OpenColorIO-Config-ACES

## Goal

Make the v4.0 OpenColorIO-Config-ACES generator produce combined configs where
every color space, view transform, and display color space carries URNs from
**all** ACES versions that define it. Currently, combined configs are missing
v1.x URNs on display color spaces and cross-version equivalent URNs on shared
working spaces.

## Root Causes

1. **`URN_CTL` is hardcoded to `v2.0`** — v1.x CTL files (with `v1.5` URNs)
   cannot be parsed.
2. **`TRANSFORM_TYPES_CTL` only lists v2.0 types** — v1.x types (`ODT`,
   `InvODT`, `RRTODT`, etc.) are rejected.
3. **`TRANSFORM_FAMILIES_CTL` only maps v2.0 directories** — v1.x directory
   names (`odt`, `rrt`, `csc`, etc.) are not recognized.
4. **`ACESTransformID._parse()` expects exactly 4 components** — v1.x IDs have
   3, 4, or 5 components.
5. **`generate_amf_components()` is called with
   `include_previous_transform_ids=False`** — cross-version equivalent URNs
   (from `transforms.json`) are not loaded.
6. **MIRROR NEGS display style divergence** — v2.0 uses
   `DISPLAY - CIE-XYZ-D65_to_sRGB - MIRROR NEGS` while v1.x uses
   `DISPLAY - CIE-XYZ-D65_to_sRGB`. URNs accumulate under different keys and
   never merge onto the same display color space.

## Workstream

All changes are in `/Users/fgiardiello/Dev_prj/OpenColorIO-Config-ACES/`.

---

### Phase 1: Add v1.x CTL submodule

**File: `.gitmodules` + submodule init**

- Add `ampas/aces-dev` as a second submodule at
  `opencolorio_config_aces/config/reference/aces-dev` (matching the v2.2
  worktree's layout).
- Pin to the same commit the v2.2 worktree uses: `ea2afeb` (v1.3 + DisplayP3
  patch, tag `v1.3-25-gea2afeb`).

```
git submodule add https://github.com/ampas/aces-dev.git \
    opencolorio_config_aces/config/reference/aces-dev
cd opencolorio_config_aces/config/reference/aces-dev
git checkout ea2afeb
cd -
git add .gitmodules opencolorio_config_aces/config/reference/aces-dev
```

---

### Phase 2: Extend CTL discovery infrastructure

**File: `opencolorio_config_aces/config/reference/discover/classify.py`**

#### 2a. Add `ROOT_TRANSFORMS_CTL_LEGACY` constant (after `ROOT_TRANSFORMS_CTL`)

```python
ROOT_TRANSFORMS_CTL_LEGACY: str = os.path.normpath(
    os.environ.get(
        "OPENCOLORIO_CONFIG_CTL__CTL_TRANSFORMS_ROOT_LEGACY",
        os.path.join(
            os.path.dirname(__file__), "../", "aces-dev", "transforms", "ctl"
        ),
    )
)
```

#### 2b. Extend `TRANSFORM_TYPES_CTL`

Add v1.x types to the existing list:

```python
TRANSFORM_TYPES_CTL: list[str] = [
    # v2.0
    "CSC", "Lib", "Look", "InvLook", "Output", "InvOutput",
    # v1.x
    "ACEScsc", "ACESlib", "ACESutil", "IDT",
    "InvLMT", "InvODT", "InvRRT", "InvRRTODT",
    "LMT", "ODT", "RRT", "RRTODT",
]
```

#### 2c. Extend `TRANSFORM_FAMILIES_CTL`

Add v1.x directory-to-family mappings:

```python
TRANSFORM_FAMILIES_CTL: dict[str, str] = {
    # v2.0 modular structure
    "aces-core": "lib",
    "aces-input-and-colorspaces": "csc",
    "aces-look": "look",
    "aces-output": "output",
    # v1.x aces-dev structure
    "csc": "csc",
    "idt": "input_transform",
    "lib": "lib",
    "lmt": "lmt",
    "odt": "output_transform",
    "outputTransform": "output_transform",
    "rrt": "rrt",
    "utilities": "utility",
}
```

#### 2d. Relax `URN_CTL` validation

Replace the single-value constant with a set:

```python
URNS_CTL: set[str] = {
    "urn:ampas:aces:transformId:v2.0",
    "urn:ampas:aces:transformId:v1.5",
}
```

Update the assertion in `ACESTransformID._parse()`:

```python
# Before:
attest(self._urn == URN_CTL, ...)
# After:
attest(self._urn in URNS_CTL, ...)
```

Keep `URN_CTL` as an alias for backward compatibility if needed:
`URN_CTL = "urn:ampas:aces:transformId:v2.0"`.

#### 2e. Merge `ACESTransformID._parse()` component handling

Replace the fixed-4-component logic with the unified logic that handles both
v1.x (3/4/5 components) and v2.0 (4 components):

```python
attest(
    len(components) in (3, 4, 5),
    f'{self._aces_transform_id} is an invalid "ACEStransformID"!',
)

if len(components) == 3:
    (self._major_version, self._minor_version, self._patch_version) = components
elif len(components) == 4:
    if self._type in ("ACESlib", "ACESutil"):
        (self._name, self._major_version, self._minor_version,
         self._patch_version) = components
    elif self._type == "IDT":
        (self._namespace, self._name, self._major_version,
         self._minor_version) = components
    else:
        # v2.0 standard: namespace.name.major.minor
        (self._namespace, self._name, self._major_version,
         self._minor_version) = components
elif len(components) == 5:
    (self._namespace, self._name, self._major_version,
     self._minor_version, self._patch_version) = components
```

#### 2f. Merge source/target extraction

Add v1.x type branches after the existing v2.0 branches:

```python
if self._name is not None:
    # v2.0 types
    if self._type == "CSC":
        ...  # existing Unity + _to_ logic
    elif self._type in ("Look", "InvLook"):
        self._source, self._target = "ACES2065-1", "ACES2065-1"
    elif self._type == "Output":
        self._source, self._target = "ACES2065-1", self._name
    elif self._type == "InvOutput":
        self._source, self._target = self._name, "ACES2065-1"
    # v1.x types
    elif self._type == "ACEScsc":
        source, target = self._name.split("_to_")
        if source == "ACES": source = "ACES2065-1"
        if target == "ACES": target = "ACES2065-1"
        self._source, self._target = source, target
    elif self._type in ("IDT", "LMT"):
        self._source, self._target = self._name, "ACES2065-1"
    elif self._type == "InvLMT":
        self._source, self._target = "ACES2065-1", self._name
    elif self._type == "ODT":
        self._source, self._target = "OCES", self._name
    elif self._type == "InvODT":
        self._source, self._target = self._name, "OCES"
    elif self._type == "RRTODT":
        self._source, self._target = "ACES2065-1", self._name
    elif self._type == "InvRRTODT":
        self._source, self._target = self._name, "ACES2065-1"
else:
    if self._type == "RRT":
        self._source, self._target = "ACES2065-1", "OCES"
    elif self._type == "InvRRT":
        self._source, self._target = "OCES", "ACES2065-1"
```

---

### Phase 3: Dual-root CTL discovery

**File: `opencolorio_config_aces/config/reference/generate/config.py`**

#### 3a. Import the legacy root

```python
from opencolorio_config_aces.config.reference.discover.classify import (
    ROOT_TRANSFORMS_CTL_LEGACY,
    ...
)
```

#### 3b. Discover CTLs from both roots

In `generate_config_aces()`, around line 928-931, change:

```python
# Before:
ctl_transforms = unclassify_ctl_transforms(
    classify_aces_ctl_transforms(discover_aces_ctl_transforms())
)

# After:
ctl_v2 = discover_aces_ctl_transforms()  # v2.0 (default root)
ctl_v1 = {}
if os.path.isdir(ROOT_TRANSFORMS_CTL_LEGACY):
    ctl_v1 = discover_aces_ctl_transforms(ROOT_TRANSFORMS_CTL_LEGACY)
# Merge: v1.x directories won't collide with v2.0 directories
ctl_merged = {**ctl_v2, **ctl_v1}
ctl_transforms = unclassify_ctl_transforms(
    classify_aces_ctl_transforms(ctl_merged)
)
```

---

### Phase 4: Enable cross-version equivalent URNs for combined builds

**File: `opencolorio_config_aces/config/reference/generate/config.py`**

#### 4a. Pass `include_previous_transform_ids=True` for combined builds

Around line 931 (after CTL discovery):

```python
is_combined = getattr(build_configuration, "csv_label", "") == "Combined ACES 1.3+2.0"
amf_components = generate_amf_components(
    include_previous_transform_ids=is_combined
)
```

This ensures that for combined builds, `amf_components` entries for v2.0 URNs
also include their v1.x `previousEquivalentTransformIds`, and vice versa. This
fixes shared working spaces (ACEScc, ACEScct, ACEScg) which only have one CSV
row (v2.0) but need both v1.x and v2.0 URNs.

---

### Phase 5: MIRROR NEGS display style redirect

**File: `opencolorio_config_aces/config/reference/generate/config.py`**

#### 5a. Redirect v1.x display URNs to MIRROR NEGS style for combined builds

In the CSV parsing loop, after the existing display style validation (around
line 995-1009), add logic to merge v1.x URNs onto the MIRROR NEGS variant when
both exist:

```python
style = transform_data["linked_display_colorspace_style"]
if style and is_combined and not style.endswith("- MIRROR NEGS"):
    mirror_negs_style = f"{style} - MIRROR NEGS"
    if mirror_negs_style in BUILTIN_TRANSFORMS:
        # v2.0 supersedes v1.x for this display; redirect URNs
        if not amf_components.get(mirror_negs_style):
            amf_components[mirror_negs_style] = []
        aces_tid = transform_data.get("aces_transform_id")
        if aces_tid:
            amf_components[mirror_negs_style].extend(
                {aces_tid, *amf_components.get(aces_tid, [])}
            )
```

This ensures that when the combined CSV has a v1.x ODT row pointing to
`DISPLAY - CIE-XYZ-D65_to_sRGB` and a v2.0 Output row pointing to
`DISPLAY - CIE-XYZ-D65_to_sRGB - MIRROR NEGS`, the v1.x URNs get merged onto
the MIRROR NEGS key (which is what the combined config's `sRGB - Display` color
space actually uses).

---

### Phase 6: Verify and test

#### 6a. Run the reference tier generator for combined build

```bash
cd /Users/fgiardiello/Dev_prj/OpenColorIO-Config-ACES
PYTHONPATH=. python -m opencolorio_config_aces.config.reference.generate.config
```

#### 6b. Verify URNs on key items

Check the generated combined config (`build/config/aces/reference/*aces-v1.3-v2.0*`):

| Item | Expected |
|------|----------|
| `ACEScc` | v2.0 CSC URN + v1.x ACEScsc equivalent URNs |
| `ACEScct` | v2.0 CSC URN + v1.x ACEScsc equivalent URNs |
| `sRGB - Display` | v2.0 Output URNs + v1.x ODT URNs |
| `Display P3 - Display` | v2.0 Output URNs + v1.x ODT URNs |
| `Rec.1886 Rec.709 - Display` | v2.0 Output URNs + v1.x ODT URNs |
| `ACES 1.0 - SDR Video` (VT) | v1.x ODT URNs (unchanged) |
| `ACES 2.0 - SDR 100 nits` (VT) | v2.0 Output URNs (unchanged) |

#### 6c. Verify pure configs are unchanged

Run the pure ACES 2.0 and pure ACES 1.3 builds and confirm they produce
identical output to before the changes.

#### 6d. Run CG and studio tiers

Since CG and studio inherit `amf_components` from reference, they should
automatically benefit from the changes. Verify their combined configs too.

#### 6e. Integration test with build_all_configs.py

Run the full pipeline from the OCIO_ACES_MERGER_AND_PARSER repo:

```bash
cd /Users/fgiardiello/Dev_prj/OCIO_ACES_MERGER_AND_PARSER
python build_all_configs.py --ocio-versions 2.5 --aces-versions combined
```

Verify the output configs have correct URNs.

---

## File Change Summary

| # | File | Changes |
|---|------|---------|
| 1 | `.gitmodules` | Add `ampas/aces-dev` submodule |
| 2 | `classify.py` | Add `ROOT_TRANSFORMS_CTL_LEGACY`, extend `TRANSFORM_TYPES_CTL`, extend `TRANSFORM_FAMILIES_CTL`, add `URNS_CTL` set, merge `ACESTransformID._parse()` for v1.x+v2.0 |
| 3 | `config.py` (reference) | Dual-root CTL discovery, `include_previous_transform_ids` for combined, MIRROR NEGS redirect |

CG and studio generators require **no changes** — they inherit `amf_components`
from reference.

---

## Risks and Mitigations

- **v1.x CTL parsing failures**: The v1.x CTLs may have edge cases not covered
  by the merged parser. Mitigation: the existing `patch_invalid_aces_transform_id()`
  function handles known quirks; add new patches if needed.
- **Sibling relationships across versions**: v1.x ODT siblings will be other
  v1.x ODTs (correct), not v2.0 Outputs. This is the desired behavior — each
  version's transforms are grouped with their own peers.
- **MIRROR NEGS redirect scope**: Only applies to combined builds
  (`is_combined` guard). Pure v1.3 and v2.0 builds are unaffected.
- **Submodule size**: `ampas/aces-dev` is ~50MB. Acceptable for a build-time
  dependency.
