# Vendor Display Extensions (`extend`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `extend` CLI subcommand that programmatically adds vendor-specific (non-ACES) display-referred views to OCIO configs from a curated family repository.

**Architecture:** YAML sidecar + OCIO snippet per vendor family. A single orchestrator loads families, resolves dependencies via topological sort, merges color spaces into the base config, wires views to displays, and copies LUT files. Integrates as an `extend` subcommand under the existing `ocio_aces_tools` CLI.

**Tech Stack:** Python 3.10+, PyOpenColorIO (>=2.3), PyYAML (`safe_load`), Pydantic v2 (schema validation), `graphlib.TopologicalSorter` (stdlib)

**Spec:** `docs/superpowers/specs/2026-03-23-vendor-display-extensions-design.md`

---

## File Structure

### New files to create

| File | Responsibility |
|------|---------------|
| `ocio_vendor_extensions/__init__.py` | Package init |
| `ocio_vendor_extensions/family_loader.py` | Load + validate `family.yaml` via Pydantic; load `colorspaces.ocio` via PyOpenColorIO |
| `ocio_vendor_extensions/dependency_resolver.py` | Topological sort of families; auto-include transitive deps |
| `ocio_vendor_extensions/config_merger.py` | Extract color spaces from snippets; add to base config; copy LUTs |
| `ocio_vendor_extensions/display_wiring.py` | Wire vendor views to displays; handle missing displays |
| `ocio_vendor_extensions/extend_config.py` | Main orchestrator + argparse CLI (`main()`) |
| `extend_ocio_config.py` | Legacy wrapper at project root |
| `tests/test_family_loader.py` | Tests for YAML loading + validation |
| `tests/test_dependency_resolver.py` | Tests for topological sort + auto-include |
| `tests/test_config_merger.py` | Tests for color space merging + LUT copy |
| `tests/test_display_wiring.py` | Tests for display matching + view wiring |
| `tests/test_extend_integration.py` | End-to-end integration test |
| `tests/fixtures/` | Test OCIO configs + minimal family packages |

### Files to modify

| File | Change |
|------|--------|
| `ocio_aces_tools/cli.py` | Add `extend` subcommand + dispatch |
| `pyproject.toml` | Add `ocio_vendor_extensions*` to packages, add `pyyaml` + `pydantic` deps |
| `requirements.txt` | Add `pyyaml>=6.0` and `pydantic>=2.0` |
| `CLAUDE.md` | Document the new `extend` subcommand |

### Family data files (created in Task 7)

| Path | Content |
|------|---------|
| `ocio_vendor_extensions/families/arri/family.yaml` | ARRI manifest |
| `ocio_vendor_extensions/families/arri/colorspaces.ocio` | ARRI color spaces |
| `ocio_vendor_extensions/families/arri/luts/*.cube` | ARRI LUT files |
| (same pattern for `arri_reveal/`, `davinci/`, `filmlight/`, `red_ipp2/`, `sony/`) | |

---

## Task 1: Package Scaffold + Dependencies

**Files:**
- Create: `ocio_vendor_extensions/__init__.py`
- Modify: `pyproject.toml`
- Modify: `requirements.txt`

- [ ] **Step 1: Create the package directory and init**

```bash
mkdir -p ocio_vendor_extensions/families
```

```python
# ocio_vendor_extensions/__init__.py
"""OCIO Vendor Display Extensions — add non-ACES vendor views to OCIO configs."""
__version__ = "1.0.0"
```

- [ ] **Step 2: Add dependencies to pyproject.toml**

In `pyproject.toml`, add `pyyaml>=6.0` and `pydantic>=2.0` to `dependencies`. Add `"ocio_vendor_extensions*"` to `[tool.setuptools.packages.find] include`. Add package-data for family files:

```toml
# Under [project] dependencies, add:
#   "pyyaml>=6.0",
#   "pydantic>=2.0",

# Under [tool.setuptools.packages.find] include, add:
#   "ocio_vendor_extensions*",

# Under [tool.setuptools.package-data], add:
# "ocio_vendor_extensions" = [
#     "families/**/*.yaml",
#     "families/**/*.ocio",
#     "families/**/*.cube",
#     "families/**/*.cub",
#     "families/**/*.spimtx",
# ]
```

- [ ] **Step 3: Add to requirements.txt**

Append `pyyaml>=6.0` and `pydantic>=2.0` to `requirements.txt`.

- [ ] **Step 4: Install dependencies**

Run: `pip install pyyaml pydantic`

- [ ] **Step 5: Verify import works**

Run: `python -c "import ocio_vendor_extensions; print(ocio_vendor_extensions.__version__)"`
Expected: `1.0.0`

- [ ] **Step 6: Commit**

```bash
git add ocio_vendor_extensions/__init__.py pyproject.toml requirements.txt
git commit -m "feat(extend): scaffold ocio_vendor_extensions package with dependencies"
```

---

## Task 2: Family Loader (YAML + OCIO Snippet)

**Files:**
- Create: `ocio_vendor_extensions/family_loader.py`
- Test: `tests/test_family_loader.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_family_loader.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_family_loader.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement family_loader.py**

```python
# ocio_vendor_extensions/family_loader.py
"""Load and validate family manifests and OCIO snippets."""
import re
import yaml
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, field_validator


class FamilyManifest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: int = 1
    family: str
    description: str = ""
    depends_on: list[str] = Field(default_factory=list)
    display_mappings: dict[str, list[str]] = Field(default_factory=dict)
    intermediates: list[str] = Field(default_factory=list)

    @field_validator("family")
    @classmethod
    def validate_family_name(cls, v):
        if not re.match(r"^[a-z0-9_]+$", v):
            raise ValueError(f"Family name must match [a-z0-9_]+, got: {v!r}")
        return v


def load_manifest(path: Path) -> FamilyManifest:
    """Load and validate a family.yaml manifest."""
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise RuntimeError(f"Invalid YAML in {path}: {e}") from e
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected mapping at root in {path}, got {type(data).__name__}")
    return FamilyManifest.model_validate(data)


def load_family_snippet(path: Path):
    """Load an OCIO config snippet and return the config object."""
    import PyOpenColorIO as OCIO
    return OCIO.Config.CreateFromFile(str(path))


def discover_families(families_dir: Path) -> dict[str, Path]:
    """Discover available family directories under families_dir.

    Returns a dict mapping family name -> family directory path.
    """
    result = {}
    if not families_dir.is_dir():
        return result
    for entry in sorted(families_dir.iterdir()):
        if entry.is_dir() and (entry / "family.yaml").exists():
            result[entry.name] = entry
    return result


def load_family(family_dir: Path) -> tuple[FamilyManifest, Path, Path]:
    """Load a complete family: manifest, snippet path, luts dir.

    Returns (manifest, colorspaces_ocio_path, luts_dir).
    """
    manifest_path = family_dir / "family.yaml"
    snippet_path = family_dir / "colorspaces.ocio"
    luts_dir = family_dir / "luts"

    manifest = load_manifest(manifest_path)

    if not snippet_path.exists():
        raise FileNotFoundError(f"Missing colorspaces.ocio in {family_dir}")

    return manifest, snippet_path, luts_dir
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_family_loader.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ocio_vendor_extensions/family_loader.py tests/test_family_loader.py
git commit -m "feat(extend): family manifest loader with Pydantic validation"
```

---

## Task 3: Dependency Resolver

**Files:**
- Create: `ocio_vendor_extensions/dependency_resolver.py`
- Test: `tests/test_dependency_resolver.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_dependency_resolver.py
import pytest
from graphlib import CycleError

from ocio_vendor_extensions.dependency_resolver import (
    resolve_processing_order,
    expand_dependencies,
)


class TestExpandDependencies:
    def test_no_deps(self):
        requested = {"arri", "davinci"}
        depends_on = {"arri": [], "davinci": []}
        result = expand_dependencies(requested, depends_on)
        assert result == {"arri", "davinci"}

    def test_transitive_dep(self):
        requested = {"sony"}
        depends_on = {"sony": ["filmlight"], "filmlight": []}
        result = expand_dependencies(requested, depends_on)
        assert result == {"sony", "filmlight"}

    def test_already_included(self):
        requested = {"sony", "filmlight"}
        depends_on = {"sony": ["filmlight"], "filmlight": []}
        result = expand_dependencies(requested, depends_on)
        assert result == {"sony", "filmlight"}


class TestResolveProcessingOrder:
    def test_independent_alphabetical(self):
        families = {"davinci", "arri", "filmlight"}
        depends_on = {"davinci": [], "arri": [], "filmlight": []}
        order = resolve_processing_order(families, depends_on)
        assert order == ["arri", "davinci", "filmlight"]

    def test_dependency_before_dependent(self):
        families = {"sony", "filmlight"}
        depends_on = {"sony": ["filmlight"], "filmlight": []}
        order = resolve_processing_order(families, depends_on)
        assert order.index("filmlight") < order.index("sony")

    def test_circular_dependency_raises(self):
        families = {"a", "b"}
        depends_on = {"a": ["b"], "b": ["a"]}
        with pytest.raises(CycleError):
            resolve_processing_order(families, depends_on)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dependency_resolver.py -v`
Expected: FAIL

- [ ] **Step 3: Implement dependency_resolver.py**

```python
# ocio_vendor_extensions/dependency_resolver.py
"""Topological sort and dependency expansion for vendor families."""
from graphlib import TopologicalSorter


def expand_dependencies(
    requested: set[str],
    depends_on: dict[str, list[str]],
) -> set[str]:
    """Expand requested families to include all transitive dependencies."""
    expanded = set(requested)
    stack = list(requested)
    while stack:
        name = stack.pop()
        for dep in depends_on.get(name, []):
            if dep not in expanded:
                expanded.add(dep)
                stack.append(dep)
    return expanded


def resolve_processing_order(
    families: set[str],
    depends_on: dict[str, list[str]],
) -> list[str]:
    """Return families in dependency-respecting, alphabetically-stable order."""
    ts = TopologicalSorter()
    for name in sorted(families):
        deps = [d for d in depends_on.get(name, []) if d in families]
        ts.add(name, *deps)
    ts.prepare()
    order: list[str] = []
    while ts.is_active():
        batch = sorted(ts.get_ready())
        order.extend(batch)
        ts.done(*batch)
    return order
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dependency_resolver.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ocio_vendor_extensions/dependency_resolver.py tests/test_dependency_resolver.py
git commit -m "feat(extend): dependency resolver with topological sort"
```

---

## Task 4: Config Merger (Color Spaces + LUT Copy)

**Files:**
- Create: `ocio_vendor_extensions/config_merger.py`
- Test: `tests/test_config_merger.py`
- Create: `tests/fixtures/` (test OCIO configs)

- [ ] **Step 1: Create test fixtures**

Create `tests/fixtures/base_config.ocio` — a minimal valid OCIO config with ACES2065-1 and a display:

```yaml
ocio_profile_version: 2.4

environment:
  {}
search_path: ""
strictparsing: true
luma: [0.2126, 0.7152, 0.0722]

roles:
  aces_interchange: ACES2065-1
  scene_linear: ACES2065-1

file_rules:
  - !<Rule> {name: Default, colorspace: ACES2065-1}

displays:
  sRGB - Display:
    - !<View> {name: Raw, colorspace: Raw}

active_displays: [sRGB - Display]
active_views: [Raw]

default_view_transform: ""

colorspaces:
  - !<ColorSpace>
    name: ACES2065-1
    family: ACES
    bitdepth: 32f
    isdata: false
    allocation: uniform

  - !<ColorSpace>
    name: Raw
    family: Utility
    bitdepth: 32f
    isdata: true
    allocation: uniform
```

Create `tests/fixtures/snippet_family/family.yaml`:

```yaml
schema_version: 1
family: testfam
description: "Test family"
depends_on: []
display_mappings:
  "TestFam : sRGB View":
    - "sRGB - Display"
intermediates: []
```

Create `tests/fixtures/snippet_family/colorspaces.ocio` — a minimal snippet with one display-referred color space:

```yaml
ocio_profile_version: 2.4

environment:
  {}
search_path: ""
strictparsing: true
luma: [0.2126, 0.7152, 0.0722]

roles:
  scene_linear: ACES2065-1

file_rules:
  - !<Rule> {name: Default, colorspace: ACES2065-1}

displays:
  sRGB - Display:
    - !<View> {name: Raw, colorspace: Raw}

colorspaces:
  - !<ColorSpace>
    name: ACES2065-1
    family: ACES
    bitdepth: 32f
    isdata: false
    allocation: uniform

  - !<ColorSpace>
    name: Raw
    family: Utility
    bitdepth: 32f
    isdata: true
    allocation: uniform

  - !<ColorSpace>
    name: "TestFam : sRGB View"
    family: TestFam/display_referred/sRGB
    bitdepth: 32f
    description: "sRGB test view"
    isdata: false
    allocation: uniform
    from_scene_reference: !<MatrixTransform> {matrix: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_config_merger.py
import pytest
from pathlib import Path
import PyOpenColorIO as OCIO

from ocio_vendor_extensions.config_merger import (
    merge_colorspaces,
    collect_file_refs,
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_config_merger.py -v`
Expected: FAIL

- [ ] **Step 4: Implement config_merger.py**

```python
# ocio_vendor_extensions/config_merger.py
"""Merge color spaces from OCIO snippets into a base config and copy LUT files."""
import shutil
from pathlib import Path


def merge_colorspaces(base_config, snippet_config, allowed_names: set[str]) -> list[str]:
    """Extract color spaces from snippet and add to base config.

    Only color spaces whose names are in allowed_names are considered.
    Skips color spaces that already exist in the base config (by name).
    Returns list of names actually added.
    """
    existing = {cs.getName() for cs in base_config.getColorSpaces()}
    added = []
    for cs in snippet_config.getColorSpaces():
        name = cs.getName()
        if name not in allowed_names:
            continue
        if name in existing:
            continue
        base_config.addColorSpace(cs)
        existing.add(name)
        added.append(name)
    return added


def collect_file_refs(transform) -> list[str]:
    """Recursively collect FileTransform src paths from a transform."""
    refs: list[str] = []
    if transform is None:
        return refs
    ttype = str(transform.getTransformType())
    if "FILE" in ttype:
        refs.append(transform.getSrc())
    elif "GROUP" in ttype:
        for sub in transform:
            refs.extend(collect_file_refs(sub))
    return refs


def collect_all_file_refs_for_colorspace(cs) -> list[str]:
    """Collect all FileTransform src paths from a color space's transforms."""
    import PyOpenColorIO as OCIO
    refs = []
    for direction in [OCIO.COLORSPACE_DIR_TO_REFERENCE, OCIO.COLORSPACE_DIR_FROM_REFERENCE]:
        t = cs.getTransform(direction)
        if t:
            refs.extend(collect_file_refs(t))
    return refs


def copy_luts(
    file_refs: list[str],
    source_dir: Path,
    target_dir: Path,
) -> list[str]:
    """Copy LUT files from source_dir to target_dir.

    Skips files that already exist at target. Rejects symlinks and paths
    with '..' components. Returns list of files actually copied.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for ref in file_refs:
        if ".." in ref or Path(ref).is_absolute():
            raise ValueError(f"Unsafe LUT path: {ref}")
        src = source_dir / ref
        dst = target_dir / Path(ref).name
        if dst.exists():
            continue
        if not src.exists():
            raise FileNotFoundError(f"LUT file not found: {src}")
        if src.is_symlink():
            raise ValueError(f"Symlink LUT not allowed: {src}")
        shutil.copy2(src, dst)
        copied.append(str(dst))
    return copied
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_config_merger.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add ocio_vendor_extensions/config_merger.py tests/test_config_merger.py tests/fixtures/
git commit -m "feat(extend): config merger for color spaces and LUT files"
```

---

## Task 5: Display Wiring

**Files:**
- Create: `ocio_vendor_extensions/display_wiring.py`
- Test: `tests/test_display_wiring.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_display_wiring.py
import pytest
from pathlib import Path
import PyOpenColorIO as OCIO

from ocio_vendor_extensions.display_wiring import (
    wire_views_to_displays,
    get_existing_displays,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestGetExistingDisplays:
    def test_returns_display_names(self):
        config = OCIO.Config.CreateFromFile(str(FIXTURES / "base_config.ocio"))
        displays = get_existing_displays(config)
        assert "sRGB - Display" in displays


class TestWireViewsToDisplays:
    def test_wires_view_to_existing_display(self):
        config = OCIO.Config.CreateFromFile(str(FIXTURES / "base_config.ocio"))
        cs = OCIO.ColorSpace(name="Test View")
        cs.setFamily("Test/display_referred")
        config.addColorSpace(cs)
        mappings = {"Test View": ["sRGB - Display"]}
        wired, missing = wire_views_to_displays(
            config, mappings, missing_policy="skip"
        )
        assert ("sRGB - Display", "Test View") in wired
        views = list(config.getViews("sRGB - Display"))
        assert "Test View" in views

    def test_skip_missing_display(self):
        config = OCIO.Config.CreateFromFile(str(FIXTURES / "base_config.ocio"))
        mappings = {"Test View": ["NonExistent - Display"]}
        wired, missing = wire_views_to_displays(
            config, mappings, missing_policy="skip"
        )
        assert len(wired) == 0
        assert "NonExistent - Display" in missing

    def test_create_missing_display(self):
        config = OCIO.Config.CreateFromFile(str(FIXTURES / "base_config.ocio"))
        cs = OCIO.ColorSpace(name="Test View")
        cs.setFamily("Test/display_referred")
        config.addColorSpace(cs)
        mappings = {"Test View": ["NewDisplay - Display"]}
        wired, missing = wire_views_to_displays(
            config, mappings, missing_policy="create"
        )
        assert ("NewDisplay - Display", "Test View") in wired
        assert "NewDisplay - Display" in list(config.getDisplays())

    def test_skips_duplicate_view(self):
        config = OCIO.Config.CreateFromFile(str(FIXTURES / "base_config.ocio"))
        mappings = {"Raw": ["sRGB - Display"]}
        wired, missing = wire_views_to_displays(
            config, mappings, missing_policy="skip"
        )
        assert len(wired) == 0


class TestReorderViews:
    def test_vendor_views_before_aces(self):
        from ocio_vendor_extensions.display_wiring import reorder_views_for_display
        config = OCIO.Config.CreateFromFile(str(FIXTURES / "base_config.ocio"))
        # Add an ACES view and a vendor view (vendor added after ACES)
        cs_aces = OCIO.ColorSpace(name="ACES View")
        config.addColorSpace(cs_aces)
        cs_vendor = OCIO.ColorSpace(name="Vendor View")
        config.addColorSpace(cs_vendor)
        config.addDisplayView("sRGB - Display", "ACES View", "ACES View", "")
        config.addDisplayView("sRGB - Display", "Vendor View", "Vendor View", "")
        # Before reorder: Raw, ACES View, Vendor View
        reorder_views_for_display(config, "sRGB - Display", ["Vendor View"])
        views = list(config.getViews("sRGB - Display"))
        assert views.index("Vendor View") < views.index("ACES View")
        assert views[0] == "Raw"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_display_wiring.py -v`
Expected: FAIL

- [ ] **Step 3: Implement display_wiring.py**

```python
# ocio_vendor_extensions/display_wiring.py
"""Wire vendor views to OCIO config displays."""
import re
import sys
import tempfile
import os


def get_existing_displays(config) -> set[str]:
    """Return set of display names in the config."""
    return set(config.getDisplays())


def wire_views_to_displays(
    config,
    display_mappings: dict[str, list[str]],
    missing_policy: str = "skip",
) -> tuple[list[tuple[str, str]], set[str]]:
    """Wire vendor view color spaces to displays.

    Args:
        config: PyOpenColorIO Config object (mutated in place)
        display_mappings: {colorspace_name: [display_name, ...]}
        missing_policy: "skip", "create", or "prompt"

    Returns:
        (wired, missing_displays) where wired is list of (display, view) tuples
        and missing_displays is set of display names that were not found.
    """
    existing_displays = get_existing_displays(config)
    wired: list[tuple[str, str]] = []
    missing_displays: set[str] = set()

    for cs_name, target_displays in display_mappings.items():
        for display_name in target_displays:
            if display_name not in existing_displays:
                if missing_policy == "skip":
                    missing_displays.add(display_name)
                    continue
                elif missing_policy == "create":
                    _create_display(config, display_name)
                    existing_displays.add(display_name)
                elif missing_policy == "prompt":
                    if _prompt_create_display(display_name, cs_name):
                        _create_display(config, display_name)
                        existing_displays.add(display_name)
                    else:
                        missing_displays.add(display_name)
                        continue

            existing_views = set(config.getViews(display_name))
            if cs_name in existing_views:
                continue

            config.addDisplayView(display_name, cs_name, cs_name, "")
            wired.append((display_name, cs_name))

    return wired, missing_displays


def reorder_views_for_display(config, display_name: str, vendor_views: list[str]) -> None:
    """Reorder views so vendor views appear before shared ACES views.

    PyOpenColorIO's addDisplayView always appends. To place vendor views
    before shared ACES views (but after Raw), we snapshot all view metadata,
    remove all views, then re-add in desired order.

    Strategy: after all views are wired, call this once per display.
    It reads the current view list, partitions into [Raw] + vendor + ACES,
    then rebuilds the display's view block.
    """
    import PyOpenColorIO as OCIO
    views = list(config.getViews(display_name))
    vendor_set = set(vendor_views)
    raw_views = [v for v in views if v == "Raw"]
    vendor_ordered = [v for v in views if v in vendor_set]
    aces_views = [v for v in views if v not in vendor_set and v != "Raw"]
    desired = raw_views + vendor_ordered + aces_views
    if desired == views:
        return
    # Snapshot view metadata BEFORE removal
    snapshots: dict[str, tuple[str, str]] = {}
    for v in views:
        cs = config.getDisplayViewColorSpaceName(display_name, v)
        looks = ""
        try:
            looks = config.getDisplayViewLooks(display_name, v)
        except Exception:
            pass
        snapshots[v] = (cs if cs else v, looks if looks else "")
    # Remove all views
    for v in views:
        config.removeDisplayView(display_name, v)
    # Re-add in desired order using snapshotted metadata
    for v in desired:
        cs, looks = snapshots[v]
        config.addDisplayView(display_name, v, cs, looks)


def update_active_views(config, new_view_names: list[str]) -> None:
    """Add new view names to active_views if the config already has an active list."""
    try:
        current = config.getActiveViews()
        if current:
            current_set = {v.strip() for v in current.split(",")} if isinstance(current, str) else set(current)
            for name in new_view_names:
                if name not in current_set:
                    config.addActiveView(name)
    except Exception:
        pass


def _create_display(config, display_name: str) -> None:
    """Create a new display with a Raw view.

    Uses CIE XYZ-D65 - Display-referred as the display colorspace
    if it exists in the config (per spec), otherwise falls back to Raw.
    """
    display_cs = "CIE XYZ-D65 - Display-referred"
    if config.getColorSpace(display_cs) is None:
        display_cs = "Raw"
    config.addDisplayView(display_name, "Raw", display_cs, "")


def _prompt_create_display(display_name: str, cs_name: str) -> bool:
    """Prompt user whether to create a missing display. Returns True if yes."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print(
            f"Display '{display_name}' not found (needed by '{cs_name}'). "
            "Use --create-missing-displays or --skip-missing-displays.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    answer = input(
        f"Display '{display_name}' not found. Create it? [y/N] "
    ).strip().lower()
    return answer in ("y", "yes")
```

**Note on view ordering:** PyOpenColorIO's `addDisplayView` always appends. After all families are processed, the orchestrator calls `reorder_views_for_display()` for each display that received vendor views. This function reads the current view list, partitions it into `[Raw] + vendor + ACES`, removes all views, and re-adds them in the desired order. If `removeDisplayView` is unavailable in the installed PyOpenColorIO version, a fallback approach serializes the config to text, reorders the YAML view block via regex, and reloads. The implementer should verify `removeDisplayView` availability and add the fallback if needed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_display_wiring.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ocio_vendor_extensions/display_wiring.py tests/test_display_wiring.py
git commit -m "feat(extend): display wiring with missing display handling"
```

---

## Task 6: Main Orchestrator + CLI

**Files:**
- Create: `ocio_vendor_extensions/extend_config.py`
- Create: `extend_ocio_config.py`
- Modify: `ocio_aces_tools/cli.py`
- Test: `tests/test_extend_integration.py`

- [ ] **Step 1: Implement extend_config.py (orchestrator + argparse)**

This is the main module. It contains `main()` with argparse and the orchestration pipeline. Due to its size, implement it in full — see the spec for the complete pipeline (Steps 1-6). Key structure:

```python
# ocio_vendor_extensions/extend_config.py
"""Extend OCIO configs with vendor display views."""
import argparse
import re
import sys
import tempfile
import os
from datetime import datetime
from pathlib import Path

import PyOpenColorIO as OCIO

from ocio_vendor_extensions.family_loader import (
    discover_families,
    load_family,
    load_family_snippet,
)
from ocio_vendor_extensions.dependency_resolver import (
    expand_dependencies,
    resolve_processing_order,
)
from ocio_vendor_extensions.config_merger import (
    merge_colorspaces,
    collect_all_file_refs_for_colorspace,
    copy_luts,
)
from ocio_vendor_extensions.display_wiring import (
    wire_views_to_displays,
    update_active_views,
)


FAMILIES_DIR = Path(__file__).parent / "families"


def _load_config_permissive(config_path: Path):
    """Load OCIO config, falling back to version-bumped copy if needed."""
    try:
        return OCIO.Config.CreateFromFile(str(config_path))
    except OCIO.Exception:
        txt = open(config_path).read()
        txt = re.sub(
            r"^(ocio_profile_version:\s*)[\d.]+",
            r"\g<1>2.5",
            txt,
            count=1,
            flags=re.MULTILINE,
        )
        fd, tmp = tempfile.mkstemp(suffix=".ocio")
        try:
            os.write(fd, txt.encode())
            os.close(fd)
            return OCIO.Config.CreateFromFile(tmp)
        finally:
            os.unlink(tmp)


def _read_declared_version(config_path: Path) -> tuple[int, int]:
    """Read declared OCIO version from config header."""
    with open(config_path) as f:
        header = f.read(512)
    m = re.search(r"ocio_profile_version:\s*([\d.]+)", header)
    if m:
        parts = m.group(1).split(".")
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    return 2, 4


def _list_families():
    """Print available families and exit."""
    available = discover_families(FAMILIES_DIR)
    if not available:
        print("No families found.")
        return
    print("Available vendor families:\n")
    for name, fam_dir in sorted(available.items()):
        from ocio_vendor_extensions.family_loader import load_manifest
        try:
            m = load_manifest(fam_dir / "family.yaml")
            views = len(m.display_mappings)
            print(f"  {name:<16} {m.description}")
            print(f"  {'':<16} Views: {views}")
        except Exception as e:
            print(f"  {name:<16} (error loading: {e})")


def main():
    parser = argparse.ArgumentParser(
        description="Extend OCIO config with vendor display views",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-i", "--input", type=Path, required=False,
                        help="Input OCIO config file (.ocio)")
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="Output path (default: auto with timestamp)")
    parser.add_argument("--families", nargs="+", default=None,
                        help="Family names to add, or 'all'")
    parser.add_argument("--list-families", action="store_true",
                        help="List available families and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be added without writing")

    mx = parser.add_mutually_exclusive_group()
    mx.add_argument("--create-missing-displays", action="store_true")
    mx.add_argument("--skip-missing-displays", action="store_true")

    args = parser.parse_args()

    if args.list_families:
        _list_families()
        return 0

    if not args.input:
        parser.error("--input is required")
    if not args.input.exists():
        print(f"Error: Input config not found: {args.input}", file=sys.stderr)
        return 1
    if not args.families:
        parser.error("--families is required (or use --list-families)")

    if args.output and args.input.resolve() == args.output.resolve():
        print("Error: --input and --output must differ", file=sys.stderr)
        return 1

    if args.output is None and not args.dry_run:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = args.input.stem
        args.output = args.input.parent / f"{stem}_extended_{ts}.ocio"

    # Determine missing display policy: dry-run → flags → env var → prompt
    if args.dry_run:
        missing_policy = "skip"
    elif args.create_missing_displays:
        missing_policy = "create"
    elif args.skip_missing_displays:
        missing_policy = "skip"
    else:
        env_val = os.environ.get("OCIO_ACES_EXTEND_MISSING_DISPLAYS", "").lower()
        if env_val == "create":
            missing_policy = "create"
        elif env_val == "skip":
            missing_policy = "skip"
        else:
            missing_policy = "prompt"

    # Validate family names
    available = discover_families(FAMILIES_DIR)
    if not available:
        print("Error: No families found in repository", file=sys.stderr)
        return 1

    requested = set(args.families)
    if "all" in requested:
        requested = set(available.keys())
    else:
        import re as _re
        for name in requested:
            if not _re.match(r"^[a-z0-9_]+$", name):
                print(f"Error: Invalid family name: {name!r}", file=sys.stderr)
                return 1
            if name not in available:
                print(f"Error: Unknown family: {name}", file=sys.stderr)
                print(f"Available: {', '.join(sorted(available.keys()))}")
                return 1

    # Load manifests and resolve dependencies
    manifests = {}
    snippet_paths = {}
    luts_dirs = {}
    depends_on_map = {}

    for name in available:
        try:
            manifest, snippet_path, luts_dir = load_family(available[name])
            manifests[name] = manifest
            snippet_paths[name] = snippet_path
            luts_dirs[name] = luts_dir
            depends_on_map[name] = manifest.depends_on
        except Exception as e:
            if name in requested:
                print(f"Error loading family '{name}': {e}", file=sys.stderr)
                return 1

    expanded = expand_dependencies(requested, depends_on_map)
    auto_included = expanded - requested
    if auto_included:
        print(f"Auto-including dependencies: {', '.join(sorted(auto_included))}")

    order = resolve_processing_order(expanded, depends_on_map)

    # Load base config + version gate (2.3–2.5 only)
    declared_major, declared_minor = _read_declared_version(args.input)
    if declared_major != 2 or declared_minor not in (3, 4, 5):
        print(
            f"Error: Unsupported OCIO version {declared_major}.{declared_minor}. "
            "Only 2.3, 2.4, and 2.5 are supported.",
            file=sys.stderr,
        )
        return 1
    config = _load_config_permissive(args.input)

    print(f"\n{'='*70}")
    print(f"OCIO VENDOR DISPLAY EXTENSIONS")
    print(f"{'='*70}")
    print(f"Input:    {args.input}")
    if not args.dry_run:
        print(f"Output:   {args.output}")
    print(f"Families: {', '.join(order)}")
    print(f"OCIO:     {declared_major}.{declared_minor}")
    print(f"{'='*70}\n")

    # Resolve search_path / LUT target
    config_dir = args.output.parent if args.output else args.input.parent
    search_path = config.getSearchPath()
    target_luts_dir = None
    if search_path:
        for sp in search_path.split(":"):
            sp = sp.strip()
            if sp:
                candidate = config_dir / sp
                if candidate.is_dir() or not target_luts_dir:
                    target_luts_dir = candidate
                    break
    if not target_luts_dir:
        target_luts_dir = config_dir / "luts"
        if not args.dry_run:
            target_luts_dir.mkdir(parents=True, exist_ok=True)
            if not search_path or "luts" not in search_path:
                new_sp = f"luts:{search_path}" if search_path else "luts"
                config.setSearchPath(new_sp)

    total_cs_added = 0
    total_views_wired = 0
    total_luts_copied = 0
    all_missing_displays: set[str] = set()
    all_new_view_names: list[str] = []
    all_wired_pairs: list[tuple[str, str]] = []

    for family_name in order:
        manifest = manifests[family_name]
        is_dep_only = family_name not in requested

        print(f"  Family: {family_name}" + (" (dependency)" if is_dep_only else ""))

        snippet = load_family_snippet(snippet_paths[family_name])

        # Determine which color spaces to extract
        if is_dep_only:
            allowed = set(manifest.intermediates)
        else:
            allowed = set(manifest.display_mappings.keys()) | set(manifest.intermediates)

        # Merge color spaces
        added = merge_colorspaces(config, snippet, allowed)
        total_cs_added += len(added)
        for name in added:
            print(f"    + CS: {name}")

        # Copy LUTs for added color spaces
        for cs_name in added:
            cs = config.getColorSpace(cs_name)
            if cs:
                refs = collect_all_file_refs_for_colorspace(cs)
                if refs and not args.dry_run:
                    copied = copy_luts(refs, luts_dirs[family_name], target_luts_dir)
                    total_luts_copied += len(copied)
                elif refs:
                    print(f"    LUTs: {len(refs)} files (dry-run)")

        # Wire views to displays (skip for dependency-only families)
        if not is_dep_only:
            wired, missing = wire_views_to_displays(
                config, manifest.display_mappings, missing_policy=missing_policy
            )
            total_views_wired += len(wired)
            all_missing_displays.update(missing)
            all_wired_pairs.extend(wired)
            for display, view in wired:
                print(f"    + View: {view} -> {display}")
                all_new_view_names.append(view)
            if missing:
                for d in sorted(missing):
                    print(f"    ! Missing display: {d}")

    # Reorder views: vendor before shared ACES, after Raw
    from ocio_vendor_extensions.display_wiring import reorder_views_for_display
    displays_with_vendor_views: dict[str, list[str]] = {}
    for display, view in all_wired_pairs:
        displays_with_vendor_views.setdefault(display, []).append(view)
    for display, vendor_views in displays_with_vendor_views.items():
        reorder_views_for_display(config, display, vendor_views)

    # Update active_views
    if all_new_view_names:
        update_active_views(config, all_new_view_names)

    # Validate and serialize
    if not args.dry_run:
        try:
            config.validate()
        except OCIO.Exception as e:
            print(f"\nValidation error: {e}", file=sys.stderr)
            return 1

        serialized = config.serialize()
        if (config.getMajorVersion(), config.getMinorVersion()) != (declared_major, declared_minor):
            serialized = re.sub(
                r"^(ocio_profile_version:\s*)[\d.]+",
                rf"\g<1>{declared_major}.{declared_minor}",
                serialized,
                count=1,
                flags=re.MULTILINE,
            )

        args.output.parent.mkdir(parents=True, exist_ok=True)
        tmp_out = args.output.with_suffix(".tmp")
        tmp_out.write_text(serialized)
        tmp_out.replace(args.output)

    # Report
    mode = "DRY RUN" if args.dry_run else "COMPLETE"
    print(f"\n{'='*70}")
    print(f"EXTENSION {mode}")
    print(f"{'='*70}")
    print(f"Families processed: {len(order)}")
    print(f"Color spaces added: {total_cs_added}")
    print(f"Views wired:        {total_views_wired}")
    print(f"LUTs copied:        {total_luts_copied}")
    if all_missing_displays:
        print(f"Missing displays:   {', '.join(sorted(all_missing_displays))}")
    if not args.dry_run:
        print(f"Output:             {args.output}")
    print(f"{'='*70}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Create legacy wrapper**

```python
# extend_ocio_config.py
#!/usr/bin/env python3
"""Legacy entry: python extend_ocio_config.py -> same as python -m ocio_aces_tools extend"""
if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.argv = ["ocio_aces_tool", "extend"] + sys.argv[1:]
    from ocio_aces_tools.cli import main
    sys.exit(main())
```

- [ ] **Step 3: Register in cli.py**

In `ocio_aces_tools/cli.py`:

Add to subparsers section (after `repo`):
```python
    # ---- extend ----
    subparsers.add_parser("extend", help="Extend OCIO config with vendor display views")
```

Add to dispatch section (before `return 1`):
```python
    if args.subcommand == "extend":
        return _run_via_argv("extend_ocio_config.py", remainder, "ocio_vendor_extensions.extend_config")
```

Add to `_run_via_argv` function:
```python
        elif module_path == "ocio_vendor_extensions.extend_config":
            from ocio_vendor_extensions import extend_config as mod
```

Update the epilog to include `extend`.

- [ ] **Step 4: Write integration test**

```python
# tests/test_extend_integration.py
import pytest
from pathlib import Path
import subprocess
import sys

FIXTURES = Path(__file__).parent / "fixtures"


class TestExtendCLI:
    def test_list_families(self):
        result = subprocess.run(
            [sys.executable, "-m", "ocio_aces_tools", "extend", "--list-families"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    def test_missing_input(self):
        result = subprocess.run(
            [sys.executable, "-m", "ocio_aces_tools", "extend",
             "-i", "nonexistent.ocio", "--families", "arri"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0

    def test_dry_run_with_fixture(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "-m", "ocio_aces_tools", "extend",
             "-i", str(FIXTURES / "base_config.ocio"),
             "--families", "all",
             "--dry-run",
             "--skip-missing-displays"],
            capture_output=True, text=True,
        )
        assert "DRY RUN" in result.stdout or result.returncode == 0
```

- [ ] **Step 5: Run integration tests**

Run: `python -m pytest tests/test_extend_integration.py -v`
Expected: PASS (at least `list_families` and `missing_input`; `dry_run` may need families)

- [ ] **Step 6: Commit**

```bash
git add ocio_vendor_extensions/extend_config.py extend_ocio_config.py ocio_aces_tools/cli.py tests/test_extend_integration.py
git commit -m "feat(extend): main orchestrator, CLI, and legacy wrapper"
```

---

## Task 7: Populate Family Data (ARRI as first family)

**Files:**
- Create: `ocio_vendor_extensions/families/arri/family.yaml`
- Create: `ocio_vendor_extensions/families/arri/colorspaces.ocio`
- Copy: LUT files from `INPUT_OCIO/FACES_OCIO/FACES_OCIO/transforms/ARRI_*.cube`

This task uses ARRI as the first family because it's the simplest (no custom intermediates needed — ARRI LogC3 is already in standard ACES configs, and views are `from_scene_reference` only).

- [ ] **Step 1: Create ARRI family.yaml**

Extract the ARRI display-referred color spaces from the FACES config and create the manifest. Map each view to the correct display names from standard ACES configs.

- [ ] **Step 2: Create ARRI colorspaces.ocio**

Build a minimal valid OCIO config containing only the ARRI display-referred color spaces from the FACES config (the 7 views: Rec.1886 Rec.709, Rec.1886 Rec.709 Classic, DCI P3 D65, Rec.2020, Rec.2100 HLG, Rec.2100 PQ). Include ACES2065-1 and Raw as required base spaces.

- [ ] **Step 3: Copy ARRI LUT files**

```bash
mkdir -p ocio_vendor_extensions/families/arri/luts
cp INPUT_OCIO/FACES_OCIO/FACES_OCIO/transforms/ARRI_LogC2Video_*.cube ocio_vendor_extensions/families/arri/luts/
```

- [ ] **Step 4: Test ARRI family end-to-end**

Run against a real ACES studio config:

```bash
python -m ocio_aces_tools extend \
  -i INPUT_OCIO/STUDIO/studio-config-all-views-v4.0.0_aces-v2.0_ocio-v2.5.ocio \
  --families arri \
  --dry-run \
  --skip-missing-displays
```

Expected: Shows ARRI views that would be added to matching displays.

- [ ] **Step 5: Commit**

```bash
git add ocio_vendor_extensions/families/arri/
git commit -m "feat(extend): add ARRI vendor family (LogC3 ALF-2)"
```

---

## Task 8: Populate Remaining Families

Repeat the Task 7 pattern for each remaining family. Each is a separate commit.

- [ ] **Step 1: ARRI Reveal family** — LogC4-based views, 8 views. LUTs from `ARRI_Reveal_*.cube`.

- [ ] **Step 2: DaVinci family** — DVI/DVWG-based views, ~14 views. LUTs from `DVI-DVWG_*.cube`.

- [ ] **Step 3: FilmLight family** — T-Log/E-Gamut 2 intermediates + ~28 display views. LUTs from `FilmLight_*.cub` and `*.spimtx`. Intermediates: `FilmLight : Linear : E-Gamut 2` and `FilmLight : T-Log : E-Gamut 2`.

- [ ] **Step 4: RED IPP2 family** — Log3G10/RWG-based views, ~8 views. LUTs from `RWG_*.cube`.

- [ ] **Step 5: Sony family** — `depends_on: [filmlight]`. Views via FilmLight intermediates. LUTs from `Sony_*.cub` and `*.spimtx`.

- [ ] **Step 6: Full integration test with all families**

```bash
python -m ocio_aces_tools extend \
  -i INPUT_OCIO/STUDIO/studio-config-all-views-v4.0.0_aces-v2.0_ocio-v2.5.ocio \
  -o /tmp/test_extended.ocio \
  --families all \
  --skip-missing-displays
```

Verify the output config loads and validates:

```bash
python -c "import PyOpenColorIO as OCIO; c = OCIO.Config.CreateFromFile('/tmp/test_extended.ocio'); c.validate(); print('OK:', len(list(c.getColorSpaces())), 'color spaces')"
```

Each family step (1–5) should be committed individually after verification:

```bash
git add ocio_vendor_extensions/families/<family_name>/
git commit -m "feat(extend): add <FamilyName> vendor family"
```

- [ ] **Step 7: Full integration test commit**

After all families pass the integration test:

```bash
git add tests/test_extend_integration.py  # if updated
git commit -m "test(extend): verify all vendor families end-to-end"
```

---

## Task 9: Update CLAUDE.md + Final Verification

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add extend documentation to CLAUDE.md**

Add the `extend` subcommand to the "Unified CLI" section and add a new subsection documenting the vendor extensions module.

- [ ] **Step 2: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: All tests pass.

- [ ] **Step 3: Run end-to-end validation against FACES reference**

Compare the tool's output against the manually-created FACES config to verify the same color spaces and display wiring are produced:

```bash
python -m ocio_aces_tools extend \
  -i INPUT_OCIO/FACES_OCIO/studio-config-all-ACES-all-views-v2.4.ocio \
  -o /tmp/faces_extended.ocio \
  --families all \
  --create-missing-displays
```

Verify the output has the same vendor color spaces as the reference FACES config.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add extend subcommand to CLAUDE.md"
```

---

## Summary: Task Dependencies

```
Task 1 (scaffold) ──> Task 2 (family loader) ──> Task 3 (dep resolver)
                                                         │
Task 4 (config merger) <─────────────────────────────────┘
         │
Task 5 (display wiring)
         │
Task 6 (orchestrator + CLI) ──> Task 7 (ARRI family) ──> Task 8 (remaining families)
                                                                    │
                                                          Task 9 (docs + verification)
```

Tasks 2-5 can be developed in parallel if desired (they have no code dependencies on each other). Task 6 integrates them all. Tasks 7-8 require Task 6 to be complete. Task 9 is the final verification.
