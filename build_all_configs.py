#!/usr/bin/env python3
"""
Unified OCIO config generation pipeline.

Pipeline stages
─────────────────────────────────────────────────────────────────────
1. GENERATE  – produce the base .ocio config
2. ENRICH    – add ACES transform IDs, equivalent/inverse IDs,
               and missing color spaces from the repository

Routing table  (stage 1)
─────────────────────────────────────────────────────────────────────
OCIO v2.5  + any ACES           OpenColorIO-Config-ACES worktree (v4.0.0)
OCIO v2.4                ──►  downgrade from OCIO v2.5 (interchange → description)
OCIO v2.3  + ACES 1.3           OpenColorIO-Config-ACES-v23 worktree (v2.2.0)
OCIO v2.3  + ACES combined      v23 worktree (1.3 base) + CLF merge (2.0 views)
OCIO v2.3  + ACES 2.0   ──►  generate_lut_based_config.py  (CLF/LUT baking)
OCIO v2.1                ──►  downgrade from OCIO v2.3 (strip v2.2+ features)
─────────────────────────────────────────────────────────────────────

OCIO v2.4 configs are produced by downgrading the v2.5 outputs.  v2.4 has all
the same BuiltinTransforms as v2.5 (including ACES 2.0 output transforms) but
uses description-based ACEStransformID lines instead of interchange attributes.

For ACES 2.0 + OCIO 2.3, the ACES 2.0 output transforms are baked into
self-contained CLF files (Matrix + Log + LUT3D) because the BuiltinTransform
styles for ACES 2.0 output were only introduced in OCIO 2.4.  A suitable OCIO v2.5
source config is built automatically as a prerequisite when one is not yet present.

OCIO v2.1 configs are produced by downgrading the v2.3 outputs (stripping
named_transforms, aliases, encoding attributes, and interchange roles).

Usage
─────────────────────────────────────────────────────────────────────
# Build everything (all OCIO versions × all ACES versions × all types):
    python build_all_configs.py

# One specific combination:
    python build_all_configs.py --ocio-version 2.3 --aces-version 2.0 --type studio

# OCIO v2.5, all types/ACES versions, custom output dir:
    python build_all_configs.py --ocio-version 2.5 -o /path/to/output

# Quick iteration: small LUT size (lower quality, faster):
    python build_all_configs.py --ocio-version 2.3 --aces-version 2.0 --lut-size 33

# Skip the enrichment pass (generation only):
    python build_all_configs.py --skip-enrich
─────────────────────────────────────────────────────────────────────
"""

import argparse
import fnmatch
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_V25 = Path(__file__).resolve().parent.parent / "OpenColorIO-Config-ACES"
DEFAULT_V23 = Path(__file__).resolve().parent.parent / "OpenColorIO-Config-ACES-v23"
SCRIPT_DIR = Path(__file__).resolve().parent

# Worktree tiers to run for each config type.
# "reference" only exists in the v2.5 worktree.
TYPE_TO_TIERS: dict[str, list[str]] = {
    "reference": ["reference"],
    "studio":    ["studio"],
    "cg":        ["cg"],
    "all":       ["reference", "cg", "studio"],
}

# Glob patterns that identify which .ocio files belong to each ACES version.
# Combined uses a distinct tag so it is never accidentally included in "1.3" or "2.0".
ACES_PATTERNS: dict[str, str] = {
    "1.3":      "*_aces-v1.3_ocio-*",    # pure 1.3 – excludes 1.3-v2.0
    "2.0":      "*_aces-v2.0_ocio-*",    # pure 2.0 – excludes 1.3-v2.0
    "combined": "*_aces-v1.3-v2.0_ocio-*",
}

# CLF path: patterns to select the v2.5 source config for each type.
# The "studio" tier in the worktree produces BOTH standard and all-views variants.
CLF_SOURCE_PATTERNS: dict[str, list[str]] = {
    "studio":    [
        "studio-config-v*_aces-v2.0_ocio-v2.5.ocio",
        "studio-config-all-views-v*_aces-v2.0_ocio-v2.5.ocio",
    ],
    "cg":        ["cg-config-v*_aces-v2.0_ocio-v2.5.ocio"],
    "reference": [
        "reference-config-v*_aces-v2.0_ocio-v2.5.ocio",
    ],
    "all": [
        "studio-config-v*_aces-v2.0_ocio-v2.5.ocio",
        "studio-config-all-views-v*_aces-v2.0_ocio-v2.5.ocio",
        "cg-config-v*_aces-v2.0_ocio-v2.5.ocio",
        "reference-config-v*_aces-v2.0_ocio-v2.5.ocio",
    ],
}

# Maps each (ocio_version, aces_version) pair to the generator strategy.
# "worktree_v25"  – use the v4.0.0 worktree
# "worktree_v23"  – use the v2.2.0 worktree
# "clf"           – CLF/LUT baking via generate_lut_based_config.py
# A pair may map to multiple strategies (list).
def _strategies(ocio: str, aces: str) -> list[str]:
    """Return generation strategies for a given OCIO/ACES pair.

    OCIO 2.1 and 2.4 are NOT handled here — they are produced by downgrading
    v2.3 and v2.5 configs respectively, after generation and enrichment.
    """
    if ocio == "2.5":
        return ["worktree_v25"]
    if ocio == "2.3":
        if aces == "2.0":
            return ["clf"]
        if aces == "combined":
            return ["worktree_v23", "clf"]
        return ["worktree_v23"]
    return []  # unknown combination (2.1 and 2.4 are derived versions)


# ---------------------------------------------------------------------------
# Helper: pretty section header
# ---------------------------------------------------------------------------

def _config_kind(stem: str) -> str:
    """Extract config kind from a filename stem.

    ``"studio-config-all-views-v2.2.0_aces-v1.3_ocio-v2.3"`` → ``"studio-config-all-views"``
    ``"cg-config-v4.0.0_aces-v2.0_ocio-v2.3-clf"`` → ``"cg-config"``
    """
    m = re.match(r'(.+-config(?:-all-views)?)-v', stem)
    return m.group(1) if m else stem.split("-v")[0]


def _header(msg: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {msg}")
    print(f"{'=' * 70}")


# ---------------------------------------------------------------------------
# Worktree generator
# ---------------------------------------------------------------------------

def run_worktree_tier(worktree: Path, tier: str, label: str) -> bool:
    """Invoke one tier's generator inside *worktree* via ``python -m``."""
    module = f"opencolorio_config_aces.config.{tier}.generate.config"
    _header(f"[{label}] {tier} generator in {worktree.name}")

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{worktree}:{env.get('PYTHONPATH', '')}"

    result = subprocess.run(
        [sys.executable, "-m", module],
        cwd=str(worktree),
        env=env,
    )
    ok = result.returncode == 0
    print("  OK" if ok else f"  FAILED (exit {result.returncode})")
    return ok


def collect_configs(
    build_root: Path,
    tier: str,
    dst_dir: Path,
    aces_version: str = "all",
) -> list[Path]:
    """Copy matching .ocio files from a worktree build dir into *dst_dir*.

    Each config is placed in its own subfolder: ``dst_dir/{stem}/{name}.ocio``.
    *aces_version* filters which files are copied; ``"all"`` copies everything.
    """
    src = build_root / "config" / "aces" / tier
    if not src.exists():
        return []

    dst_dir.mkdir(parents=True, exist_ok=True)
    pattern = ACES_PATTERNS.get(aces_version, "*.ocio") if aces_version != "all" else "*.ocio"

    copied: list[Path] = []
    for f in sorted(src.glob("*.ocio")):
        if aces_version != "all" and not fnmatch.fnmatch(f.name, pattern):
            continue
        folder = dst_dir / f.stem
        folder.mkdir(parents=True, exist_ok=True)
        dst = folder / f.name
        shutil.copy2(f, dst)
        copied.append(dst)
    return copied


# ---------------------------------------------------------------------------
# CLF / LUT path
# ---------------------------------------------------------------------------

def _ensure_v25_sources(
    v25_dir: Path,
    config_type: str,
    v25_worktree: Path,
    aces_version: str = "2.0",
) -> list[Path]:
    """Return v2.5 source configs, building them first when absent.

    The CLF path requires an ACES 2.0 OCIO v2.5 config as its input.
    This function checks whether suitable sources already exist in *v25_dir*
    and runs the v2.5 worktree generator if they do not.
    """
    source_patterns = CLF_SOURCE_PATTERNS.get(config_type, [])
    if not source_patterns:
        return []

    existing = []
    for pat in source_patterns:
        # Search both at the top level and inside per-config subfolders.
        existing.extend(sorted(v25_dir.glob(pat)))
        existing.extend(sorted(v25_dir.glob(f"*/{pat}")))

    if len(existing) >= len(source_patterns):
        return existing

    # Need to build first.
    print(
        "\n  ACES 2.0 + OCIO 2.3 requires an OCIO v2.5 source config.\n"
        "  Generating it now as a prerequisite…"
    )

    tiers_needed = {
        "studio-config-v*":           "studio",
        "studio-config-all-views-v*": "studio",
        "cg-config-v*":               "cg",
        "reference-config-v*":        "reference",
    }
    tiers_to_run: set[str] = set()
    for pat in source_patterns:
        for prefix, tier in tiers_needed.items():
            if fnmatch.fnmatch(pat, f"{prefix}*"):
                tiers_to_run.add(tier)

    if not v25_worktree.exists():
        print(f"  ERROR: v2.5 worktree not found at {v25_worktree}")
        return []

    for tier in sorted(tiers_to_run):
        ok = run_worktree_tier(v25_worktree, tier, "OCIO-v2.5 prerequisite")
        if ok:
            collect_configs(v25_worktree / "build", tier, v25_dir, aces_version="all")

    result: list[Path] = []
    for pat in source_patterns:
        result.extend(sorted(v25_dir.glob(pat)))
        result.extend(sorted(v25_dir.glob(f"*/{pat}")))
    return result


def generate_clf_configs(
    sources: list[Path],
    dst_dir: Path,
    target_ocio: str,
    lut_size: int,
) -> tuple[list[Path], list[str]]:
    """Bake CLF/LUT-based configs from *sources* for OCIO *target_ocio*.

    Each source config gets its own subdirectory so the ``luts/`` folders
    never collide:

        dst_dir/
          studio-config-v4.0.0_aces-v2.0_ocio-v2.3-clf/
            studio-config-v4.0.0_aces-v2.0_ocio-v2.3-clf.ocio
            luts/

    Returns ``(generated_ocio_paths, failure_labels)``.
    """
    script = SCRIPT_DIR / "generate_lut_based_config.py"
    if not script.exists():
        print(f"  ERROR: {script} not found.")
        return [], [str(script)]

    generated: list[Path] = []
    failures: list[str] = []

    for src in sources:
        # Derive the output subdirectory name from the source filename.
        clf_stem = re.sub(r"ocio-v2\.[45]", f"ocio-v{target_ocio}-clf", src.stem)
        subdir = dst_dir / clf_stem
        subdir.mkdir(parents=True, exist_ok=True)

        _header(f"[CLF/LUT] {src.name}  →  OCIO {target_ocio}")

        result = subprocess.run(
            [
                sys.executable, str(script),
                str(src),
                "-o", str(subdir),
                "--target-ocio-version", target_ocio,
                "-s", str(lut_size),
            ],
        )
        ok = result.returncode == 0
        if not ok:
            print(f"  FAILED (exit {result.returncode})")
            failures.append(f"CLF/{src.name}")
            continue

        ocio_files = list(subdir.glob("*.ocio"))
        if ocio_files:
            for ocf in ocio_files:
                _prune_folder_luts(ocf)
            generated.extend(ocio_files)
            print(f"  OK  →  {ocio_files[0].name}")
        else:
            failures.append(f"CLF/{src.name} (no .ocio produced)")

    return generated, failures


# ---------------------------------------------------------------------------
# Merge ACES 2.0 CLF elements into a base (ACES 1.3) config
# ---------------------------------------------------------------------------

def _load_config_permissive(path: Path):
    """Load an OCIO config, bumping version if needed for incompatible BuiltIns."""
    import PyOpenColorIO as OCIO
    import tempfile
    path_str = str(path.resolve())
    try:
        return OCIO.Config.CreateFromFile(path_str)
    except OCIO.Exception:
        txt = path.read_text()
        txt = re.sub(
            r'^(ocio_profile_version:\s*)[\d.]+',
            r'\g<1>2.5', txt, count=1, flags=re.MULTILINE,
        )
        fd, tmp = tempfile.mkstemp(suffix='.ocio', dir=str(path.parent))
        os.write(fd, txt.encode())
        os.close(fd)
        try:
            return OCIO.Config.CreateFromFile(tmp)
        finally:
            os.unlink(tmp)


def merge_aces20_into_base(
    base_path: Path,
    clf_path: Path,
    output_path: Path,
) -> bool:
    """Merge ACES 2.0 elements from a CLF config into a base (ACES 1.3) config.

    Adds color spaces, named transforms, view transforms, shared views, and
    display-level shared view references from *clf_path* that are not already
    present in *base_path*.  Also copies the CLF ``luts/`` directory alongside
    the output and sets up ``search_path`` if needed.

    Returns True on success.
    """
    import PyOpenColorIO as OCIO

    try:
        base_cfg = _load_config_permissive(base_path)
        clf_cfg = _load_config_permissive(clf_path)
    except Exception as exc:
        print(f"  MERGE ERROR loading configs: {exc}")
        return False

    base_cs_names = {cs.getName() for cs in base_cfg.getColorSpaces()}
    base_nt_names = {nt.getName() for nt in base_cfg.getNamedTransforms()}
    base_vt_names = {vt.getName() for vt in base_cfg.getViewTransforms()}
    base_shared = set(base_cfg.getSharedViews())

    base_cs_aliases: set[str] = set()
    for cs in base_cfg.getColorSpaces():
        base_cs_aliases.update(cs.getAliases())

    base_nt_aliases: set[str] = set()
    for nt in base_cfg.getNamedTransforms():
        base_nt_aliases.update(nt.getAliases())

    added_cs = added_nt = added_vt = added_sv = added_dv = 0

    # --- Viewing rules (must come before shared views that reference them) ---
    base_vr = base_cfg.getViewingRules()
    clf_vr = clf_cfg.getViewingRules()
    base_rule_names = {base_vr.getName(i) for i in range(base_vr.getNumEntries())}
    for i in range(clf_vr.getNumEntries()):
        rule_name = clf_vr.getName(i)
        if rule_name not in base_rule_names:
            idx = base_vr.getNumEntries()
            base_vr.insertRule(idx, rule_name)
            for enc in clf_vr.getEncodings(i):
                base_vr.addEncoding(idx, enc)
            for cs_name in clf_vr.getColorSpaces(i):
                base_vr.addColorSpace(idx, cs_name)
    base_cfg.setViewingRules(base_vr)

    # --- Color spaces ---
    for cs in clf_cfg.getColorSpaces():
        if cs.getName() not in base_cs_names:
            if set(cs.getAliases()) & base_cs_aliases:
                continue
            base_cfg.addColorSpace(cs)
            base_cs_aliases.update(cs.getAliases())
            added_cs += 1

    # --- Named transforms ---
    for nt in clf_cfg.getNamedTransforms():
        if nt.getName() not in base_nt_names:
            if set(nt.getAliases()) & base_nt_aliases:
                continue
            base_cfg.addNamedTransform(nt)
            base_nt_aliases.update(nt.getAliases())
            added_nt += 1

    # --- View transforms ---
    for vt in clf_cfg.getViewTransforms():
        if vt.getName() not in base_vt_names:
            base_cfg.addViewTransform(vt)
            added_vt += 1

    # --- Shared views ---
    for sv_name in clf_cfg.getSharedViews():
        if sv_name not in base_shared:
            vt_name = clf_cfg.getDisplayViewTransformName(
                clf_cfg.getDisplays()[0], sv_name
            ) if False else ""
            # Shared views are defined globally; extract their definition
            # by looking at how they're used in the CLF config.
            # We need to find a display that has this shared view to get
            # its view transform and color space.
            found = False
            for d in clf_cfg.getDisplays():
                if clf_cfg.isViewShared(d, sv_name):
                    vt_name = clf_cfg.getDisplayViewTransformName(d, sv_name)
                    cs_name = clf_cfg.getDisplayViewColorSpaceName(d, sv_name)
                    looks = clf_cfg.getDisplayViewLooks(d, sv_name)
                    rule = clf_cfg.getDisplayViewRule(d, sv_name)
                    desc = clf_cfg.getDisplayViewDescription(d, sv_name)
                    base_cfg.addSharedView(
                        sv_name, vt_name, cs_name, looks, rule, desc,
                    )
                    added_sv += 1
                    found = True
                    break
            if not found:
                print(f"    WARNING: shared view '{sv_name}' not found on any display")

    # --- Display views (shared view references + non-shared views) ---
    for display in clf_cfg.getDisplays():
        base_views = set(base_cfg.getViews(display))
        for view in clf_cfg.getViews(display):
            if view in base_views:
                continue
            if clf_cfg.isViewShared(display, view):
                base_cfg.addDisplaySharedView(display, view)
            else:
                vt_name = clf_cfg.getDisplayViewTransformName(display, view)
                cs_name = clf_cfg.getDisplayViewColorSpaceName(display, view)
                looks = clf_cfg.getDisplayViewLooks(display, view)
                rule = clf_cfg.getDisplayViewRule(display, view)
                desc = clf_cfg.getDisplayViewDescription(display, view)
                base_cfg.addDisplayView(
                    display, view, vt_name, cs_name, looks, rule, desc,
                )
            added_dv += 1

    # --- Active views: add new views so they're visible ---
    base_active_views = set(base_cfg.getActiveViews())
    if base_active_views:  # only if the base has an explicit active list
        for av in clf_cfg.getActiveViews():
            if av not in base_active_views:
                base_cfg.addActiveView(av)

    # --- Active displays: add new displays ---
    base_active_displays = set(base_cfg.getActiveDisplays())
    if base_active_displays:
        for ad in clf_cfg.getActiveDisplays():
            if ad not in base_active_displays:
                base_cfg.addActiveDisplay(ad)

    # --- search_path: copy only the CLF luts the merged config references ---
    clf_luts_dir = clf_path.parent / "luts"
    needs_luts = False
    if clf_luts_dir.is_dir():
        referenced = _collect_file_refs_from_config(base_cfg)
        needed = [f for f in clf_luts_dir.iterdir() if f.name in referenced]
        if needed:
            dst_luts = output_path.parent / "luts"
            dst_luts.mkdir(parents=True, exist_ok=True)
            for f in needed:
                shutil.copy2(f, dst_luts / f.name)
            needs_luts = True

    # Serialize, patching back the original declared version.
    original_text = base_path.read_text()[:512]
    ver_match = re.search(r'ocio_profile_version:\s*([\d.]+)', original_text)
    original_version = ver_match.group(1) if ver_match else None

    # If we added LUTs, ensure search_path includes "luts".
    if needs_luts:
        sp = base_cfg.getSearchPath()
        if "luts" not in sp:
            new_sp = f"luts:{sp}" if sp else "luts"
            base_cfg.setSearchPath(new_sp)

    try:
        base_cfg.validate()
    except OCIO.Exception as exc:
        print(f"  MERGE WARNING: validation issue: {exc}")

    # Serialize — may need to temporarily bump to v2.5 if the merged config
    # contains BuiltinTransforms that require a higher version.
    try:
        text = base_cfg.serialize()
    except OCIO.Exception:
        base_cfg.setMajorVersion(2)
        base_cfg.setMinorVersion(5)
        text = base_cfg.serialize()

    if original_version:
        text = re.sub(
            r'^(ocio_profile_version:\s*)[\d.]+',
            rf'\g<1>{original_version}',
            text, count=1, flags=re.MULTILINE,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text)

    print(
        f"  MERGED: +{added_cs} cs, +{added_nt} named, "
        f"+{added_vt} view transforms, +{added_sv} shared views, "
        f"+{added_dv} display views"
    )
    return True


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

ENRICHER_SCRIPT = SCRIPT_DIR / "ocio_aces_enricher" / "scripts" / "enrich_ocio_config.py"

# Pipeline ACES version → enricher --aces-version value.
_ACES_TO_ENRICHER: dict[str, str] = {
    "1.3":      "1.3",
    "2.0":      "2.0",
    "combined": "all",
}

# Pipeline config type → enricher --config-type value.
_TYPE_TO_ENRICHER: dict[str, str] = {
    "studio":    "studio",
    "cg":        "cg",
    "reference": "reference",
}


def _infer_enricher_params(config_path: Path) -> tuple[str, str]:
    """Best-effort inference of (aces_version, config_type) from a filename.

    Used when the caller doesn't have explicit metadata (e.g. configs collected
    from a worktree build directory where the ACES version and type are encoded
    in the filename).
    """
    name = config_path.name

    if "_aces-v1.3-v2.0_" in name or "_aces-v1.3+v2.0_" in name:
        aces = "all"
    elif "_aces-v2.0" in name:
        aces = "2.0"
    elif "_aces-v1.3" in name or "_aces-v1." in name:
        aces = "1.3"
    else:
        aces = "all"

    if name.startswith("reference-config") or name.startswith("ref-config"):
        cfg_type = "reference"
    else:
        cfg_type = "studio"

    return aces, cfg_type


def enrich_config(
    config_path: Path,
    aces_version: str,
    config_type: str,
    ocio_version: str,
    transforms_json: Path | None = None,
) -> bool:
    """Run the enricher on a single config, overwriting it in place.

    For single-version configs (ACES 1.3 or 2.0) the enricher is called with
    ``--prune`` so that any stray URNs from the other ACES generation are
    removed.  Combined configs use ``--aces-version all`` without pruning so
    both 1.x and 2.0 IDs are kept.

    Returns True on success.
    """
    if not ENRICHER_SCRIPT.exists():
        print(f"  WARNING: enricher not found at {ENRICHER_SCRIPT} — skipping.")
        return False

    enricher_aces = _ACES_TO_ENRICHER.get(aces_version, aces_version)
    enricher_type = _TYPE_TO_ENRICHER.get(config_type, "studio")

    cmd = [
        sys.executable, str(ENRICHER_SCRIPT),
        "-i", str(config_path),
        "-o", str(config_path),
        "--aces-version", enricher_aces,
        "--config-type", enricher_type,
    ]

    # For single-version configs, prune URNs that don't belong.
    if aces_version in ("1.3", "2.0"):
        cmd.append("--prune")

    # For OCIO 2.3 and 2.4 configs, skip the v2.5 upgrade step so the
    # enricher adds IDs to description fields (not interchange attributes).
    if ocio_version in ("2.3", "2.4"):
        cmd.append("--skip-upgrade")

    if transforms_json is not None:
        cmd.extend(["--transforms", str(transforms_json)])

    # Read the original declared version so we can restore it after enrichment.
    # The enricher may internally bump the version to load configs with
    # incompatible BuiltinTransforms (e.g. CLF-based v2.3 configs).
    import re as _re
    original_text_head = config_path.read_text()[:512]
    ver_match = _re.search(r'ocio_profile_version:\s*([\d.]+)', original_text_head)
    original_version = ver_match.group(1) if ver_match else None

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"  ENRICH FAILED for {config_path.name}:")
        stderr = result.stderr.strip()
        if stderr:
            for line in stderr.splitlines()[-5:]:
                print(f"    {line}")
        return False

    # Restore the original declared version if the enricher changed it.
    if original_version:
        text = config_path.read_text()
        new_match = _re.search(r'ocio_profile_version:\s*([\d.]+)', text[:512])
        if new_match and new_match.group(1) != original_version:
            text = _re.sub(
                r'^(ocio_profile_version:\s*)[\d.]+',
                rf'\g<1>{original_version}',
                text, count=1, flags=_re.MULTILINE,
            )
            config_path.write_text(text)

    return True


def enrich_all(
    configs: list[Path],
    aces_version: str,
    config_type: str,
    ocio_version: str,
    transforms_json: Path | None = None,
) -> tuple[int, int]:
    """Enrich a list of configs.  Returns (success_count, failure_count)."""
    if not configs:
        return 0, 0

    ok_count = 0
    fail_count = 0

    for cfg in configs:
        # Use explicit params when available, fall back to filename inference.
        if aces_version and config_type:
            a_ver, c_type = aces_version, config_type
        else:
            a_ver, c_type = _infer_enricher_params(cfg)

        prune_tag = "+prune" if a_ver in ("1.3", "2.0") else ""
        print(f"    enriching {cfg.name}  (ACES {a_ver}, {c_type}{prune_tag}) …", end="", flush=True)
        if enrich_config(cfg, a_ver, c_type, ocio_version, transforms_json):
            print("  OK")
            ok_count += 1
        else:
            print("  FAILED")
            fail_count += 1

    return ok_count, fail_count


# ---------------------------------------------------------------------------
# Main build function
# ---------------------------------------------------------------------------

def build(
    ocio_versions: list[str],
    aces_versions: list[str],
    config_types: list[str],
    output: Path,
    v25_worktree: Path,
    v23_worktree: Path,
    lut_size: int,
    do_enrich: bool = True,
    transforms_json: Path | None = None,
    requested_ocio_versions: set[str] | None = None,
) -> tuple[list[Path], list[str]]:
    """Run all generation + enrichment steps and return (all_configs, failures).

    *requested_ocio_versions* is the set of OCIO versions the user originally
    asked for (before parent injection for derived versions).  When a parent
    version (e.g. 2.5) was added only as a build prerequisite for a derived
    version (e.g. 2.4), the parent's output folder is removed at the end so
    the user only sees what they requested.
    """

    all_configs: list[Path] = []
    failures: list[str] = []
    enrich_ok = 0
    enrich_fail = 0

    # Track which worktree tiers we've already run in this session so we don't
    # repeat expensive generator runs when multiple ACES versions share a tier.
    ran_v25_tiers: set[str] = set()
    ran_v23_tiers: set[str] = set()

    for ocio_ver in ocio_versions:
        for aces_ver in aces_versions:
            for cfg_type in config_types:

                tiers = TYPE_TO_TIERS.get(cfg_type, ["studio"])
                strategies = _strategies(ocio_ver, aces_ver)

                if not strategies:
                    print(
                        f"\n  SKIP  OCIO {ocio_ver} + ACES {aces_ver} + {cfg_type} "
                        f"(no generator available)"
                    )
                    continue

                # For combined ACES + OCIO 2.3, strategies are
                # ["worktree_v23", "clf"].  The worktree produces the ACES 1.3
                # base; the CLF path produces standalone ACES 2.0 configs.
                # We merge the ACES 2.0 elements into the base configs.
                base_configs: list[Path] = []  # from worktree (combined case)
                final_batch: list[Path] = []

                for strategy in strategies:
                    batch: list[Path] = []

                    # ── Worktree v2.5 ───────────────────────────────────────
                    if strategy == "worktree_v25":
                        if not v25_worktree.exists():
                            failures.append(f"worktree_v25 missing ({v25_worktree})")
                            continue
                        dst = output / "OCIO-v2.5"
                        for tier in tiers:
                            if tier == "reference" and ocio_ver != "2.5":
                                continue
                            if tier not in ran_v25_tiers:
                                ok = run_worktree_tier(
                                    v25_worktree, tier, "OCIO-v2.5"
                                )
                                if ok:
                                    ran_v25_tiers.add(tier)
                                else:
                                    failures.append(f"OCIO-v2.5/{tier}")
                                    continue
                            configs = collect_configs(
                                v25_worktree / "build", tier, dst, aces_ver
                            )
                            batch.extend(configs)

                    # ── Worktree v2.3 ───────────────────────────────────────
                    elif strategy == "worktree_v23":
                        if not v23_worktree.exists():
                            failures.append(f"worktree_v23 missing ({v23_worktree})")
                            continue
                        dst = output / "OCIO-v2.3"
                        for tier in tiers:
                            if tier == "reference":
                                if cfg_type != "reference":
                                    continue
                            if tier not in ran_v23_tiers:
                                ok = run_worktree_tier(
                                    v23_worktree, tier, "OCIO-v2.3"
                                )
                                if ok:
                                    ran_v23_tiers.add(tier)
                                else:
                                    failures.append(f"OCIO-v2.3/{tier}")
                                    continue
                            configs = collect_configs(
                                v23_worktree / "build", tier, dst, aces_ver
                            )
                            batch.extend(configs)

                    # ── CLF / LUT baking ────────────────────────────────────
                    elif strategy == "clf":
                        target = ocio_ver
                        dst_root = output / f"OCIO-v{target}"

                        v25_dir = output / "OCIO-v2.5"
                        sources = _ensure_v25_sources(
                            v25_dir, cfg_type, v25_worktree, aces_version="2.0"
                        )
                        if not sources:
                            if CLF_SOURCE_PATTERNS.get(cfg_type):
                                failures.append(
                                    f"CLF/{ocio_ver}/{aces_ver}/{cfg_type}: "
                                    f"no v2.5 source found"
                                )
                            continue

                        clf_configs, clf_fails = generate_clf_configs(
                            sources, dst_root, target, lut_size
                        )
                        failures.extend(clf_fails)

                        if aces_ver == "combined" and base_configs:
                            # Merge ACES 2.0 CLF elements into the base
                            # configs produced by the worktree_v23 strategy.
                            _header(
                                f"[MERGE] ACES 2.0 CLF → combined "
                                f"OCIO {ocio_ver} / {cfg_type}"
                            )
                            for base_p in base_configs:
                                base_kind = _config_kind(base_p.stem)
                                matching_clf = [
                                    c for c in clf_configs
                                    if _config_kind(c.stem) == base_kind
                                ]
                                if not matching_clf:
                                    # Fallback: e.g. reference-config CLF
                                    # matches reference-config-all-views base.
                                    matching_clf = [
                                        c for c in clf_configs
                                        if base_kind.startswith(
                                            _config_kind(c.stem))
                                    ]
                                if not matching_clf:
                                    print(
                                        f"  No CLF match for {base_p.name} "
                                        f"(kind={base_kind})"
                                    )
                                    continue
                                clf_p = matching_clf[0]
                                print(
                                    f"  {base_p.name}  ←  {clf_p.name}"
                                )
                                if not merge_aces20_into_base(
                                    base_p, clf_p, base_p
                                ):
                                    failures.append(
                                        f"merge/{base_p.name}"
                                    )
                            # Don't add CLF configs to the batch — they were
                            # merged into the base configs.
                            batch = []
                        else:
                            batch.extend(clf_configs)

                    if aces_ver == "combined" and strategy == "worktree_v23":
                        base_configs.extend(batch)

                    final_batch.extend(batch)

                # ── Enrich this batch ────────────────────────────────────
                all_configs.extend(final_batch)

                if do_enrich and final_batch:
                    _header(
                        f"[ENRICH] OCIO {ocio_ver} / ACES {aces_ver} / {cfg_type}"
                    )
                    ok_n, fail_n = enrich_all(
                        final_batch,
                        aces_version=aces_ver,
                        config_type=cfg_type,
                        ocio_version=ocio_ver,
                        transforms_json=transforms_json,
                    )
                    enrich_ok += ok_n
                    enrich_fail += fail_n
                    if fail_n:
                        failures.append(
                            f"enrich/{ocio_ver}/{aces_ver}/{cfg_type}: "
                            f"{fail_n} config(s) failed"
                        )

    if do_enrich:
        print(f"\n  Enrichment: {enrich_ok} succeeded, {enrich_fail} failed")

    # ── Safety: remove stale loose artifacts at OCIO-vX/ level ─────────
    _header("[CLEANUP] Remove stale loose artifacts")
    _cleanup_loose_artifacts(all_configs)

    # ── OCIO v2.4 downgrade ──────────────────────────────────────────────
    # v2.4 configs are produced by downgrading the fully-generated v2.5
    # configs (migrating interchange to description, stripping interop_id).
    if "2.4" in ocio_versions:
        v25_configs = [c for c in all_configs if "/OCIO-v2.5/" in str(c)]
        if v25_configs:
            v24_configs, v24_fails = _downgrade_v25_to_v24(
                v25_configs, output
            )
            all_configs.extend(v24_configs)
            failures.extend(v24_fails)
        else:
            failures.append(
                "OCIO 2.4: no v2.5 configs to downgrade (run with "
                "--ocio-version 2.5 first, or include 2.5 in the build)"
            )

    # ── OCIO v2.1 downgrade ──────────────────────────────────────────────
    # v2.1 configs are produced by downgrading the fully-generated v2.3
    # configs (stripping named_transforms, aliases, encoding, interchange).
    if "2.1" in ocio_versions:
        v23_configs = [c for c in all_configs if "/OCIO-v2.3/" in str(c)]
        if v23_configs:
            v21_configs, v21_fails = _downgrade_v23_to_v21(
                v23_configs, output
            )
            all_configs.extend(v21_configs)
            failures.extend(v21_fails)
        else:
            failures.append(
                "OCIO 2.1: no v2.3 configs to downgrade (run with "
                "--ocio-version 2.3 first, or include 2.3 in the build)"
            )

    # ── Remove intermediate parent configs the user didn't ask for ──────
    # This covers two cases:
    #  1. Parent versions injected for downgrades (e.g. 2.5 for 2.4).
    #  2. Prerequisite v2.5 configs generated by _ensure_v25_sources for CLF
    #     baking when v2.5 wasn't in the generation list at all.
    # Only versions that participated in *this* build are candidates; we never
    # touch directories left over from a previous run.
    if requested_ocio_versions is not None:
        built_versions = set(ocio_versions)
        # _ensure_v25_sources may also create OCIO-v2.5 as a prerequisite
        # even when 2.5 is not in ocio_versions.
        v25_dir = output / "OCIO-v2.5"
        if v25_dir.is_dir() and "2.5" not in built_versions:
            built_versions.add("2.5")

        intermediates = built_versions - requested_ocio_versions
        if intermediates:
            _header("[CLEANUP] Remove intermediate parent configs")
            for ver in sorted(intermediates):
                ver_dir = output / f"OCIO-v{ver}"
                if not ver_dir.is_dir():
                    continue
                tag = f"/OCIO-v{ver}/"
                parent_cfgs = [c for c in all_configs if tag in str(c)]
                if parent_cfgs:
                    print(f"  Removing {len(parent_cfgs)} intermediate "
                          f"OCIO v{ver} config(s) (not explicitly requested)")
                    all_configs = [c for c in all_configs if tag not in str(c)]
                shutil.rmtree(ver_dir)
                print(f"  Removed {ver_dir.name}/ "
                      f"(prerequisite, not requested)")

    return all_configs, failures


def _collect_file_refs_from_transform(transform) -> set[str]:
    """Recursively collect FileTransform ``src`` basenames from *transform*."""
    import PyOpenColorIO as OCIO
    refs: set[str] = set()
    if transform is None:
        return refs
    if isinstance(transform, OCIO.FileTransform):
        src = transform.getSrc()
        if src:
            refs.add(os.path.basename(src))
    elif isinstance(transform, OCIO.GroupTransform):
        for sub in transform:
            refs.update(_collect_file_refs_from_transform(sub))
    return refs


def _collect_file_refs_from_config(cfg) -> set[str]:
    """Return ``FileTransform`` ``src`` basenames from an in-memory config.

    Walks all ColorSpaces, Looks, ViewTransforms, and NamedTransforms.
    *cfg* is a ``PyOpenColorIO.Config`` object already loaded in memory.
    """
    import PyOpenColorIO as OCIO
    refs: set[str] = set()

    for cs in cfg.getColorSpaces():
        for direction in (OCIO.COLORSPACE_DIR_TO_REFERENCE,
                          OCIO.COLORSPACE_DIR_FROM_REFERENCE):
            refs.update(_collect_file_refs_from_transform(
                cs.getTransform(direction)))

    for look in cfg.getLooks():
        refs.update(_collect_file_refs_from_transform(look.getTransform()))
        refs.update(_collect_file_refs_from_transform(
            look.getInverseTransform()))

    for vt in cfg.getViewTransforms():
        for direction in (OCIO.VIEWTRANSFORM_DIR_TO_REFERENCE,
                          OCIO.VIEWTRANSFORM_DIR_FROM_REFERENCE):
            refs.update(_collect_file_refs_from_transform(
                vt.getTransform(direction)))

    for nt in cfg.getNamedTransforms():
        refs.update(_collect_file_refs_from_transform(
            nt.getTransform(OCIO.TRANSFORM_DIR_FORWARD)))
        refs.update(_collect_file_refs_from_transform(
            nt.getTransform(OCIO.TRANSFORM_DIR_INVERSE)))

    return refs




def _prune_folder_luts(cfg: Path) -> None:
    """Remove LUT files not referenced by *cfg* from its sibling ``luts/``."""
    luts_dir = cfg.parent / "luts"
    if not luts_dir.is_dir():
        return

    text = cfg.read_text(errors="replace")
    referenced = {
        os.path.basename(m.group(1))
        for m in re.finditer(r'src:\s*([^\s,}]+)', text)
        if '.' in m.group(1)
    }

    pruned = 0
    for f in list(luts_dir.iterdir()):
        if f.name not in referenced:
            f.unlink()
            pruned += 1

    if pruned:
        print(f"    pruned {pruned} unreferenced LUT(s) from {cfg.parent.name}/")

    if luts_dir.is_dir() and not any(luts_dir.iterdir()):
        luts_dir.rmdir()


def _cleanup_loose_artifacts(configs: list[Path]) -> None:
    """Remove stale loose ``.ocio`` files and shared ``luts/`` at the OCIO-vX level.

    With per-config folders, there should be no loose configs or shared LUT
    directories at the OCIO-version level.  This is a safety net only.
    """
    seen_parents: set[Path] = set()
    for cfg in configs:
        seen_parents.add(cfg.parent.parent)

    for parent in seen_parents:
        shared_luts = parent / "luts"
        if shared_luts.is_dir():
            shutil.rmtree(shared_luts)
            print(f"  Cleaned up shared luts/ in {parent.name}/")

        for loose in parent.glob("*.ocio"):
            loose.unlink()
            print(f"  Cleaned up stale {loose.name}")


def _downgrade_v23_to_v21(
    v23_configs: list[Path],
    output: Path,
) -> tuple[list[Path], list[str]]:
    """Downgrade a list of v2.3 configs to v2.1.

    Each v2.3 config lives in its own per-config folder.  We copy the
    entire folder into OCIO-v2.1/, rename with the version string
    replaced, then apply the text-level downgrade.
    """
    from generate_lut_based_config import downgrade_v23_to_v21

    _header("[DOWNGRADE] OCIO 2.3 → 2.1")

    v21_dir = output / "OCIO-v2.1"
    v21_dir.mkdir(parents=True, exist_ok=True)

    produced: list[Path] = []
    fails: list[str] = []

    for src in v23_configs:
        src_folder = src.parent
        # Build the v2.1 folder name by replacing version strings.
        v21_folder_name = src_folder.name.replace("ocio-v2.3", "ocio-v2.1")
        dst_folder = v21_dir / v21_folder_name

        # Copy the entire config folder.
        if dst_folder.exists():
            shutil.rmtree(dst_folder)
        shutil.copytree(src_folder, dst_folder)

        # Rename the .ocio file inside.
        v21_ocio_name = src.name.replace("ocio-v2.3", "ocio-v2.1")
        dst_old = dst_folder / src.name
        dst = dst_folder / v21_ocio_name
        if dst_old.exists() and dst_old != dst:
            dst_old.rename(dst)

        # Apply the downgrade.
        try:
            downgrade_v23_to_v21(dst, dst)
            _prune_folder_luts(dst)
            print(f"  {src_folder.name}/  →  {v21_folder_name}/")
            produced.append(dst)
        except Exception as exc:
            print(f"  FAIL  {src.name}: {exc}")
            fails.append(f"downgrade/{src.name}: {exc}")

    print(f"  Downgraded {len(produced)} config(s) to OCIO 2.1")
    return produced, fails


def _downgrade_v25_to_v24(
    v25_configs: list[Path],
    output: Path,
) -> tuple[list[Path], list[str]]:
    """Downgrade a list of v2.5 configs to v2.4.

    Each v2.5 config lives in its own per-config folder.  We copy the
    entire folder into OCIO-v2.4/, rename with the version string
    replaced, then apply the text-level downgrade.
    """
    from generate_lut_based_config import downgrade_v25_to_v24

    _header("[DOWNGRADE] OCIO 2.5 → 2.4")

    v24_dir = output / "OCIO-v2.4"
    v24_dir.mkdir(parents=True, exist_ok=True)

    produced: list[Path] = []
    fails: list[str] = []

    for src in v25_configs:
        src_folder = src.parent
        v24_folder_name = src_folder.name.replace("ocio-v2.5", "ocio-v2.4")
        dst_folder = v24_dir / v24_folder_name

        if dst_folder.exists():
            shutil.rmtree(dst_folder)
        shutil.copytree(src_folder, dst_folder)

        v24_ocio_name = src.name.replace("ocio-v2.5", "ocio-v2.4")
        dst_old = dst_folder / src.name
        dst = dst_folder / v24_ocio_name
        if dst_old.exists() and dst_old != dst:
            dst_old.rename(dst)

        try:
            downgrade_v25_to_v24(dst, dst)
            _prune_folder_luts(dst)
            print(f"  {src_folder.name}/  →  {v24_folder_name}/")
            produced.append(dst)
        except Exception as exc:
            print(f"  FAIL  {src.name}: {exc}")
            fails.append(f"downgrade/{src.name}: {exc}")

    print(f"  Downgraded {len(produced)} config(s) to OCIO 2.4")
    return produced, fails


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _expand_all(values: list[str], choices: list[str]) -> list[str]:
    """Replace 'all' with the full list of choices (preserving explicit items)."""
    if "all" in values:
        return choices
    return values


def main() -> None:
    valid_ocio  = ["2.1", "2.3", "2.4", "2.5"]
    valid_aces  = ["1.3", "2.0", "combined"]
    valid_types = ["reference", "studio", "cg"]

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--ocio-version",
        nargs="+",
        choices=valid_ocio + ["all"],
        default=["all"],
        metavar="{2.1,2.3,2.4,2.5,all}",
        help="OCIO profile version(s) to generate (default: all)",
    )
    parser.add_argument(
        "--aces-version",
        nargs="+",
        choices=valid_aces + ["all"],
        default=["all"],
        metavar="{1.3,2.0,combined,all}",
        help="ACES version(s) to generate (default: all)",
    )
    parser.add_argument(
        "--type",
        nargs="+",
        choices=valid_types + ["all"],
        default=["all"],
        metavar="{reference,studio,cg,all}",
        help="Config type(s) to generate (default: all).  "
             "studio produces both standard and all-views variants.",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=SCRIPT_DIR / "OUTPUT_CONFIGS",
        help="Root output directory (default: OUTPUT_CONFIGS/)",
    )
    parser.add_argument(
        "--lut-size",
        type=int,
        default=65,
        help="3D LUT cube size for CLF baking (default: 65; use 33 for fast preview)",
    )
    parser.add_argument(
        "--skip-enrich",
        action="store_true",
        help="Skip the enrichment pass (generation only, no ACES ID enrichment).",
    )
    parser.add_argument(
        "--transforms",
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to a local ACES transforms.json for enrichment.  "
             "If omitted, the enricher downloads the official registry.",
    )
    parser.add_argument(
        "--v25-worktree",
        type=Path,
        default=DEFAULT_V25,
        help=f"Path to the v4.0.0 worktree (OCIO v2.5, default: {DEFAULT_V25})",
    )
    parser.add_argument(
        "--v23-worktree",
        type=Path,
        default=DEFAULT_V23,
        help=f"Path to the v2.2.0 worktree (OCIO v2.3, default: {DEFAULT_V23})",
    )
    args = parser.parse_args()

    ocio_versions = _expand_all(args.ocio_version,  valid_ocio)
    aces_versions = _expand_all(args.aces_version,  valid_aces)
    config_types  = _expand_all(args.type,          valid_types)

    requested_ocio = set(ocio_versions)

    # v2.4 is derived from v2.5, so ensure v2.5 is in the generation list.
    if "2.4" in ocio_versions and "2.5" not in ocio_versions:
        ocio_versions.insert(ocio_versions.index("2.4"), "2.5")

    # v2.1 is derived from v2.3, so ensure v2.3 is in the generation list.
    if "2.1" in ocio_versions and "2.3" not in ocio_versions:
        ocio_versions.insert(ocio_versions.index("2.1"), "2.3")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    do_enrich = not args.skip_enrich
    transforms_json = args.transforms.resolve() if args.transforms else None

    print(f"\n  OCIO versions : {ocio_versions}")
    print(f"  ACES versions : {aces_versions}")
    print(f"  Config types  : {config_types}")
    print(f"  Output        : {output}")
    print(f"  LUT size      : {args.lut_size}")
    print(f"  Enrich        : {'yes' if do_enrich else 'SKIP'}")
    if transforms_json:
        print(f"  Transforms    : {transforms_json}")

    all_configs, failures = build(
        ocio_versions=ocio_versions,
        aces_versions=aces_versions,
        config_types=config_types,
        output=output,
        v25_worktree=args.v25_worktree.resolve(),
        v23_worktree=args.v23_worktree.resolve(),
        lut_size=args.lut_size,
        do_enrich=do_enrich,
        transforms_json=transforms_json,
        requested_ocio_versions=requested_ocio,
    )

    # ── Summary ──────────────────────────────────────────────────────────
    _header("SUMMARY")
    print(f"  Generated configs : {len(all_configs)}")
    for cfg in sorted(all_configs, key=lambda p: p.name):
        size = cfg.stat().st_size
        try:
            rel = cfg.relative_to(output)
        except ValueError:
            rel = cfg
        print(f"    [{size:>8} bytes]  {rel}")

    if failures:
        print(f"\n  FAILURES ({len(failures)}):")
        for f in failures:
            print(f"    - {f}")
        sys.exit(1)

    print(f"\n  All configs written to: {output}")
    sys.exit(0)


if __name__ == "__main__":
    main()
