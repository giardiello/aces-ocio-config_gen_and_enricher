# OCIO Vendor Display Extensions (`extend`) — Design Spec

**Date:** 2026-03-23
**Status:** Draft
**Author:** AI-assisted design session
**Deepened:** 2026-03-23

## Enhancement Summary

**Research agents used:** PyOpenColorIO API, YAML schema design, topological sort, CLI design, architecture review, performance analysis, codebase exploration, OCIO display/view API, security audit

### Key Improvements
1. Added concrete PyOpenColorIO API patterns and gotchas for config merging, display wiring, and version handling
2. Added implementation guidance for YAML schema validation (Pydantic v2 + safe_load), dependency resolution (graphlib.TopologicalSorter), and CLI patterns (argparse subparsers + TTY detection)
3. Added security considerations (safe YAML loading, path traversal prevention, atomic writes)
4. Added performance guidance (single validate pass, lazy snippet loading, batched LUT copy)
5. Identified shared code to reuse from existing codebase (permissive config loader, LUT file collection, display view merge patterns from build_all_configs.py)

---

## Problem Statement

The existing OCIO ACES tooling in this repository creates, enriches, and merges ACES-based OCIO configurations. However, production workflows often require vendor-specific (non-ACES) display-referred views — FilmLight Baselight looks, DaVinci Resolve tone maps, ARRI ALF-2/Reveal DRTs, RED IPP2 looks, and Sony display transforms. Currently these are added manually (as seen in the FACES_OCIO config). This tool automates that process.

## Goals

- Programmatically extend any ACES OCIO config with vendor-specific display-referred views
- Support adding views by vendor "family" (FilmLight, DaVinci, ARRI, ARRI-Reveal, RED-IPP2, Sony)
- Automatically wire vendor views to the correct displays in the base config
- Automatically resolve dependencies (add intermediate color spaces if missing)
- Ship a curated repository of vendor LUT files
- Support OCIO v2.3, v2.4, and v2.5 configs as input
- Be fully independent from the existing enricher module

## Non-Goals

- Decomposing vendor LUTs into OCIO view_transform + display_colorspace (future iteration)
- Modifying or removing existing ACES views in the base config
- Updating the enricher module's interface

## Assumptions

- The base config is an ACES-based config (has `ACES2065-1` as `aces_interchange` role and the standard ACES input color spaces that vendor intermediates depend on)
- The `colorspaces.ocio` snippets are authored against the same ACES scene reference as the base config
- Recommended pipeline order: **enrich first, then extend** (enrichment adds ACES IDs and missing ACES color spaces; extension adds vendor views on top)

---

## Architecture

### Module Structure

```
ocio_vendor_extensions/
  __init__.py
  extend_config.py          # Core logic: load families, resolve deps, inject
  manifest_schema.py        # YAML sidecar loading & validation
  display_matcher.py        # Maps vendor views to existing config displays
  families/
    filmlight/
      family.yaml           # Metadata sidecar: display mappings, depends_on
      colorspaces.ocio       # OCIO snippet with all FilmLight color spaces
      luts/
        *.cub, *.spimtx
    davinci/
      family.yaml
      colorspaces.ocio
      luts/
        *.cube
    arri/
      family.yaml
      colorspaces.ocio
      luts/
        *.cube
    arri_reveal/
      family.yaml
      colorspaces.ocio
      luts/
        *.cube
    red_ipp2/
      family.yaml
      colorspaces.ocio
      luts/
        *.cube
    sony/
      family.yaml
      colorspaces.ocio
      luts/
        *.cub, *.spimtx
```

Additionally:
- `extend` subcommand registered under `ocio_aces_tools` CLI
- `extend_ocio_config.py` legacy wrapper at project root

### Research Insights: Module Structure

**Reuse from existing codebase:**
- `_load_config_permissive` and version detection logic (currently duplicated in `enrich_ocio_config.py` and `build_all_configs.py`) should be centralized in `ocio_aces_tools/ocio_utils.py` and shared by both enricher and extend
- `_collect_file_refs(transform)` and `_resolve_search_path(config_path, config)` from the enricher are directly applicable for LUT handling
- Display view merging pattern from `build_all_configs.merge_aces20_into_base` (lines 335-450) is the closest in-repo pattern: it handles `isViewShared` vs `addDisplayView`, updates `active_views` conditionally, and manages view ordering
- CLI registration follows the `_run_via_argv` delegation pattern in `cli.py`

**Packaging note:** If the package is installed via pip, `families/` must be declared as `package_data` (or use `importlib.resources`) so paths resolve correctly when CWD is not the repo root.

### Family Repository Format

Each family consists of two files plus a LUT directory:

**`colorspaces.ocio`** — A valid OCIO config snippet containing all color space definitions for the family (both scene-referred intermediates and display-referred views). This is a real OCIO config that can be validated with PyOpenColorIO. The tool extracts **only color spaces** from it (not roles, file rules, looks, named transforms, or display definitions) and merges them into the base config.

**`family.yaml`** — A thin metadata sidecar containing only what OCIO configs cannot express:

```yaml
family: FilmLight
description: "FilmLight Baselight display rendering via T-Log/E-Gamut 2"
depends_on: []

# Exact display names from ACES configs -> color space names to wire
display_mappings:
  "FilmLight : sRGB Display: 2.2 Gamma : Rec.709":
    - "sRGB - Display"
  "FilmLight : DCI: 2.6 Gamma : P3 D65":
    - "Display P3 - Display"
    - "P3-D65 - Display"
  "FilmLight : Rec.1886: 2.4 Gamma : Rec.709":
    - "Rec.1886 Rec.709 - Display"
  "FilmLight : Rec.2100 : ST 2084 PQ : Rec.2020 : 1000 nits":
    - "Rec.2100-PQ - Display"
  # ... all view-to-display mappings

# Color spaces that are intermediates (not display views)
intermediates:
  - "FilmLight : Linear : E-Gamut 2"
  - "FilmLight : T-Log : E-Gamut 2"
```

**`luts/`** — Directory containing all LUT files referenced by the family's `colorspaces.ocio`.

### Research Insights: YAML Schema Validation

**Recommended stack:** Pydantic v2 + `yaml.safe_load` (PyYAML). Parse YAML to dict, then validate with a Pydantic model. This gives type safety, nested structure validation, and JSON Schema export for documentation.

```python
from pydantic import BaseModel, Field, ConfigDict

class FamilyManifest(BaseModel):
    model_config = ConfigDict(extra="ignore")  # forward compatibility
    family: str
    description: str = ""
    depends_on: list[str] = Field(default_factory=list)
    display_mappings: dict[str, list[str]] = Field(default_factory=dict)
    intermediates: list[str] = Field(default_factory=list)
```

**YAML special characters:** OCIO color space names contain colons (e.g., `FilmLight : sRGB Display: 2.2 Gamma : Rec.709`) and Unicode primes (e.g., `X′Y′Z′`). Keys and values with colons must be quoted in YAML. Document this requirement for family authors.

**Schema versioning:** Include `schema_version: 1` at the top level for future migrations. Use `extra="ignore"` in Pydantic for forward compatibility (unknown keys from newer schemas are silently dropped).

### Display Matching

Display matching uses **exact display name references**. The `family.yaml` sidecar lists the exact ACES config display names each vendor view should be wired to. At runtime:

1. The tool reads the base config's display list
2. For each vendor view, checks if the target display name exists
3. If yes: wires the view as a direct `{name:, colorspace:}` entry on that display
4. If no: prompts the user whether to create the missing display
5. Non-interactive flags (`--create-missing-displays`, `--skip-missing-displays`) for scripting

Vendor views are inserted **before** the shared ACES views reference (`!<Views> [...]`) on each display, grouped after `Raw`. If the display has no `Raw` view, vendor views are prepended. If the display has no shared views reference, vendor views are appended. Multiple vendor views on the same display appear in the order their families were processed (topological sort), and within a family in the order they appear in `display_mappings`.

### View Wiring Pattern

Vendor views use the **per-display direct colorspace pattern** (not shared_views/view_transforms). Each vendor view is a color space with a `from_scene_reference` transform chain, wired as:

```yaml
- !<View> {name: "FilmLight : sRGB Display: 2.2 Gamma : Rec.709",
           colorspace: "FilmLight : sRGB Display: 2.2 Gamma : Rec.709"}
```

This matches the proven pattern from the existing FACES config and preserves exact vendor LUT output. Decomposition into view_transform + display_colorspace is deferred to a future iteration.

### Research Insights: PyOpenColorIO Display/View API

**Adding direct views:** `config.addDisplayView(display, view, colorSpaceName, looks="")` — the first-form overload maps a view directly to a color space. There is no separate `addDisplay` API; a display is created implicitly when the first view is attached.

**Creating new displays:** Call `addDisplayView` with a new display name string. The display appears automatically.

**Active views/displays:** If the base config has explicit `active_views`, new views are hidden until added via `config.addActiveView(view_name)`. Match the pattern from `build_all_configs.py` (lines 444-456): only extend active lists when the base already has them.

**View ordering gotcha:** `addDisplayView` typically **appends**. Serialization order may not match the desired insertion point ("before shared ACES views"). Implementation must verify ordering via round-trip testing on real studio configs. If the API doesn't support insertion at a specific position, a YAML post-processing pass may be needed.

**Version-specific:** OCIO 2.5 adds `isViewShared()`, `hasView()`, `AreViewsEqual()` helpers. For 2.3/2.4 targets, use `getDisplayViewColorSpaceName()` to distinguish direct vs VT-based views.

### Dependency Resolution

Each family declares its dependencies via `depends_on` in `family.yaml`. The processing order is determined by topological sort.

**Intermediate resolution:** For each intermediate listed in `family.yaml`, the tool checks if a color space with that name already exists in the base config. Standard ACES intermediates (ARRI LogC3, DaVinci Intermediate WideGamut, etc.) are typically already present. Family-specific intermediates (FilmLight T-Log/E-Gamut 2) are added from the family's `colorspaces.ocio` if missing.

**Cross-family dependencies:** If the user requests `--families sony` and Sony depends on FilmLight, the tool automatically includes FilmLight's intermediates (but not its display views) and prints a notice. The `depends_on` field in `family.yaml` always means "intermediates only" — it never pulls in the dependency's display views. If the user wants both families' display views, they must list both explicitly.

**Deterministic ordering:** When two families have no dependency relationship, they are processed in alphabetical order to ensure reproducible output.

### Research Insights: Dependency Resolution

**Use `graphlib.TopologicalSorter` (Python 3.9+ stdlib).** Key API detail: `add(child, *predecessors)` — if family A has `depends_on: [B]`, then B is a predecessor: `ts.add("A", "B")`.

**Deterministic tie-breaking:** `static_order()` does not guarantee alphabetical order among independent nodes. Use the `get_ready()` / `done()` loop with `sorted(ts.get_ready())` per batch:

```python
from graphlib import TopologicalSorter

def deterministic_order(families, depends_on):
    ts = TopologicalSorter()
    for name in sorted(families):
        ts.add(name, *depends_on.get(name, []))
    ts.prepare()  # raises CycleError if circular
    order = []
    while ts.is_active():
        batch = sorted(ts.get_ready())
        order.extend(batch)
        ts.done(*batch)
    return order
```

**Cycle detection:** `prepare()` raises `graphlib.CycleError` with the cycle path in `e.args[1]`. Format for users: `" -> ".join(cycle)`.

**Auto-inclusion:** Before building the graph, expand the user's requested set with a BFS over `depends_on` edges to find all transitive dependencies.

---

## CLI Interface

### Subcommand

```bash
python -m ocio_aces_tools extend [args...]
```

### Arguments

| Flag | Required | Description |
|---|---|---|
| `-i / --input` | Yes | Input OCIO config file (.ocio) |
| `-o / --output` | No | Output path. Auto-named with `_extended_YYYYMMDD_HHMMSS` suffix if omitted |
| `--families` | Yes* | Space-separated family names, or `all`. *Not required with `--list-families` |
| `--create-missing-displays` | No | Non-interactive: auto-create displays not found in base config |
| `--skip-missing-displays` | No | Non-interactive: silently skip missing displays |
| `--list-families` | No | Print available families with descriptions and exit |
| `--dry-run` | No | Show what would be added without modifying anything |

### Examples

```bash
# List available families
python -m ocio_aces_tools extend --list-families

# Add FilmLight and DaVinci views to a studio config
python -m ocio_aces_tools extend \
  -i studio-config-v2.5.ocio \
  -o studio-extended.ocio \
  --families filmlight davinci

# Add all vendor families
python -m ocio_aces_tools extend \
  -i studio-config.ocio \
  -o studio-all-vendors.ocio \
  --families all

# Dry run to preview changes
python -m ocio_aces_tools extend \
  -i studio-config.ocio \
  --families arri red_ipp2 \
  --dry-run

# Non-interactive: skip any missing displays
python -m ocio_aces_tools extend \
  -i config.ocio -o out.ocio \
  --families all --skip-missing-displays
```

### Legacy Wrapper

`extend_ocio_config.py` at project root, matching the pattern of other scripts:

```bash
python extend_ocio_config.py -i config.ocio -o out.ocio --families filmlight davinci
```

### Research Insights: CLI Design

**Subcommand registration:** Follow the existing `_run_via_argv` pattern in `cli.py`. Add `subparsers.add_parser("extend", ...)` and a dispatch branch. All argparse flags live in the extend module's `main()`, not in `cli.py`.

**Mutually exclusive flags:** Use `parser.add_mutually_exclusive_group()` for `--create-missing-displays` / `--skip-missing-displays`. argparse rejects both being set before your code runs.

**TTY detection:** Check `sys.stdin.isatty() and sys.stdout.isatty()` before prompting. Non-TTY environments should fail with a clear message suggesting the appropriate flag.

**Missing display policy resolution order:** explicit flags -> env var (`OCIO_ACES_EXTEND_MISSING_DISPLAYS=create|skip`) -> interactive prompt if TTY -> error if non-TTY.

**Exit codes:** 0 = success, 1 = processing error, 2 = usage/argparse error. Document in `--help` epilog.

**`--dry-run`:** Run the full pipeline (load, resolve, validate) but skip file writes and LUT copies. Print planned actions. Exit 0 if the plan would succeed.

**Legacy wrapper pattern:**

```python
#!/usr/bin/env python3
if __name__ == "__main__":
    import sys
    sys.argv = ["ocio_aces_tool", "extend"] + sys.argv[1:]
    from ocio_aces_tools.cli import main
    sys.exit(main())
```

---

## Processing Pipeline

### Step 1: Load & Validate Base Config

- Load input OCIO config via PyOpenColorIO
- Detect version (must be 2.3, 2.4, or 2.5)
- Inventory existing displays, color spaces, and views

### Step 2: Resolve Families

- Parse `--families` argument (or `all`)
- Load each family's `family.yaml` and `colorspaces.ocio`
- Resolve cross-family dependencies
- Topological sort to determine processing order

### Step 3: Process Each Family (in dependency order)

**3a. Add intermediates:**
- For each intermediate in `family.yaml`, check if it exists in the base config
- If missing, extract from `colorspaces.ocio` and add
- Copy referenced LUT files to config's search_path

**3b. Add display-referred views:**
- For each color space in `colorspaces.ocio` that is either listed as a key in `display_mappings` or listed in `intermediates`:
  - Skip if already exists in config
  - Add color space to config
  - Copy referenced LUT files
- Color spaces in the snippet that are not referenced in `display_mappings` or `intermediates` are ignored (prevents accidental pollution from helper/legacy spaces in the snippet)

**3c. Wire views to displays:**
- For each entry in `display_mappings`:
  - If target display exists: add view before ACES shared views
  - If target display missing: prompt user / create / skip based on flags

### Step 4: Update active_views

- Add newly created view names to `active_views` list only if `active_views` is already populated in the base config (if the base config has no `active_views`, leave it empty — OCIO treats that as "all views active")

### Step 5: Serialize & Save

- Validate config via `config.validate()` — **once**, after all mutations (never per-colorspace or per-family)
- Serialize preserving original OCIO version
- If the in-memory config was version-bumped for compatibility (permissive load), restore the declared version in the serialized YAML header (same pattern as enricher and `build_all_configs.py`)
- Write to output path using atomic write (temp file + `os.replace`)

### Step 6: Report

- Summary: families processed, color spaces added, views wired, LUTs copied, displays created/skipped

### Research Insights: Processing Pipeline

**Performance:** The pipeline is dominated by `config.validate()` and LUT file I/O, not by parsing or topological sort. Key optimizations:
- **Single validate** at the end (Step 5), never per-insert
- **Lazy snippet loading**: only load `colorspaces.ocio` for families that will actually run (after dependency resolution)
- **Release snippet configs** after extracting color spaces to reduce peak memory
- **Copy LUTs only for color spaces actually added** (skip if collision detected)
- **Existence check before copy** (`os.path.exists`) to short-circuit idempotent re-runs

**Config merging pattern (from `build_all_configs.py`):**

```python
base_names = {cs.getName() for cs in base.getColorSpaces()}
for cs in snippet.getColorSpaces():
    if cs.getName() in base_names:
        continue
    base.addColorSpace(cs)
```

**Version handling:** Read the declared version from YAML header before loading (regex on first 512 bytes). After serialize, restore the declared version if the in-memory config was bumped. Strip interchange attributes when targeting < v2.5 (same as enricher).

**BuiltinTransform compatibility:** Test each color space's transforms against the target version by building a minimal temp config at the declared version and calling `serialize()`. Skip incompatible color spaces with a warning (same pattern as enricher lines 394-417).

---

## Resolution Policies

### Missing Display Behavior

When a target display from `display_mappings` is not found in the base config:

- **Interactive mode (default):** Prompt the user per missing display. If stdin is not a TTY, fall back to error with a message suggesting `--skip-missing-displays` or `--create-missing-displays`.
- **`--skip-missing-displays`:** Silently skip; log at INFO level.
- **`--create-missing-displays`:** Create the display with a `Raw` view, then wire vendor views. The new display uses `CIE XYZ-D65 - Display-referred` as its display colorspace (the standard ACES display-referred reference space used by all ACES configs). The display name is taken exactly from the `family.yaml` mapping.
- **Both flags set:** Error — mutually exclusive.
- **`--dry-run`:** Report missing displays as `[MISSING DISPLAY]` without prompting.

### Color Space Collision

When a color space name from a family's `colorspaces.ocio` already exists in the base config:

- **Same name:** Skip the family's version, keep the existing one, log a warning.
- No transform-equality comparison is performed (too fragile across OCIO versions). The assumption is that if the name matches, it's the same or compatible color space.

### Idempotent Re-runs

Running the tool twice on the same output is safe: existing color spaces are skipped (name match), existing views on displays are skipped (duplicate detection), and LUT files are not overwritten. The output is identical to a single run.

### search_path and LUT Deployment

LUT files are copied to the **first writable directory** in the config's `search_path`. If no `search_path` entry is writable (or `search_path` is empty/unset), a `luts/` directory is created alongside the output config and `search_path` is updated to include `luts`. Relative paths in `colorspaces.ocio` FileTransform `src` attributes are preserved as-is (they resolve via `search_path`). Absolute paths in `src` are not supported — family snippets must use relative paths only. LUT files that already exist at the target are not overwritten.

### Input/Output Path Safety

- If `--input` equals `--output`, the tool exits with an error (no in-place modification; use a temp file and rename manually if needed).
- If the output directory does not exist, it is created.

---

## Error Handling

### Pre-flight Validation

- Input config loads successfully via PyOpenColorIO
- OCIO version is 2.3, 2.4, or 2.5
- Each requested family exists in the repository
- Each family's `colorspaces.ocio` loads and validates
- All LUT files referenced by family color spaces exist in `luts/`
- Cross-family dependencies are satisfiable (no circular deps)

### Runtime Errors

| Scenario | Behavior |
|---|---|
| Input config won't load | Exit with error, suggest checking OCIO version |
| Family not found in repository | Exit with error, list available families |
| LUT file missing from family's `luts/` | Exit with error, name the missing file and which view needs it |
| Intermediate missing and not in `colorspaces.ocio` | Exit with error, explain the dependency |
| Cross-family dependency missing from `--families` | Auto-include dependency intermediates with notice |
| Color space name collision (same name, different transform) | Skip with warning, keep existing |
| Output config fails `config.validate()` | Exit with error, don't write output, show validation messages |
| LUT file already exists in target search_path | Skip copy, use existing (no overwrite) |

---

## Vendor Families at Launch

All six families ship in v1:

| Family | Intermediate | View Count | Display Types |
|---|---|---|---|
| `filmlight` | T-Log/E-Gamut 2 (added if missing) | ~28 | sRGB, DCI, Dolby, Dolby Cin, Rec.1886, Rec.2020, Rec.2100 |
| `davinci` | DaVinci Intermediate WideGamut (in ACES config) | ~14 | DCI, Dolby, Dolby Cin, Rec.1886, Rec.2020, Rec.2100, sRGB |
| `arri` | ARRI LogC3 EI800 (in ACES config) | ~7 | Rec.1886, DCI, Rec.2020, Rec.2100 |
| `arri_reveal` | ARRI LogC4 (in ACES config) | ~8 | DCI, Dolby, Rec.1886, Rec.2020, Rec.2100 |
| `red_ipp2` | Log3G10 REDWideGamutRGB (in ACES config) | ~8 | Rec.1886, Rec.2020 |
| `sony` | FilmLight intermediates (depends_on: filmlight) | ~2 | Rec.1886, DCI |

---

## Security Considerations

**Threat model:** The tool operates on **curated family packages** (shipped with the repo) and **trusted base configs** (ACES studio configs from known sources). User-contributed families are a future feature with a higher trust boundary.

**YAML loading:** Always use `yaml.safe_load` (never `yaml.load` without a safe Loader). Validate parsed data against a strict Pydantic schema. Reject unknown keys in strict mode. Cap file size of `family.yaml` to prevent YAML bombs.

**Path traversal:** All LUT file references in `colorspaces.ocio` must be relative paths. The implementation must normalize paths (`os.path.realpath`) and verify they resolve within the family's `luts/` directory. Reject `..` components, absolute paths, and symlinks in LUT source paths.

**File I/O safety:** Use atomic writes (temp file + `os.replace`) for the output config. Use `os.path.exists` (not `lstat` following symlinks) for LUT existence checks. Refuse to copy if the destination is a symlink.

**Family name validation:** `--families` tokens must match `^[a-z0-9_]+$` and exist in the known family catalog. Reject path separators and special characters.

**Interactive prompts:** Sanitize display names in terminal output (strip ANSI escape sequences and control characters) to prevent terminal injection.

---

## Known Limitations

- **Display name brittleness:** Display matching uses exact string names from standard ACES configs. If a studio renames displays, the `family.yaml` sidecars need updating. A `--display-alias` mechanism is a potential future addition.
- **No transform equality checking:** Color space collision detection is name-based only. Two color spaces with the same name but different transforms are not detected.
- **Vendor LUTs are opaque:** The tool treats vendor LUTs as black boxes. It cannot validate that a LUT produces correct output for a given display — that's the responsibility of the family curator.

---

## Future Iterations

- **view_transform factoring:** Decompose vendor LUTs into view_transform + display_colorspace where mathematically feasible, with numerical validation against original LUT output
- **Additional families:** Panasonic VariCam, Canon Cinema, Nikon N-Log, etc.
- **User-contributed families:** Documentation and tooling for creating custom family packages
- **Display alias map:** `--display-aliases aliases.yaml` for studios with non-standard display names
- **Enricher integration:** Optional `--extend-families` flag on the enricher for single-pipeline workflows
- **Centralized config utilities:** Extract `_load_config_permissive`, `_collect_file_refs`, `_resolve_search_path` into `ocio_aces_tools/ocio_utils.py` for shared use by enricher and extend
