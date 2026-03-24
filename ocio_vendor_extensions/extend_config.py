"""Extend OCIO configs with vendor display views."""
import argparse
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import PyOpenColorIO as OCIO

from ocio_vendor_extensions.config_merger import (
    collect_all_file_refs_for_colorspace,
    copy_luts,
    merge_colorspaces,
)
from ocio_vendor_extensions.dependency_resolver import (
    expand_dependencies,
    resolve_processing_order,
)
from ocio_vendor_extensions.display_wiring import (
    reorder_views_for_display,
    wire_views_to_displays,
)
from ocio_vendor_extensions.family_loader import (
    discover_families,
    load_family,
    load_family_snippet,
    load_manifest,
)

FAMILIES_DIR = Path(__file__).parent / "families"


def _load_config_permissive(config_path: Path):
    """Load OCIO config, falling back to version-adjusted copy if needed.

    Downgrades the declared version to match the library's max supported
    minor version when the config declares a newer version.
    """
    try:
        return OCIO.Config.CreateFromFile(str(config_path))
    except OCIO.Exception:
        ver_parts = OCIO.GetVersion().split(".")
        lib_major = int(ver_parts[0])
        lib_minor = int(ver_parts[1]) if len(ver_parts) > 1 else 0
        target_ver = f"{lib_major}.{lib_minor}"
        txt = config_path.read_text(encoding="utf-8")
        txt = re.sub(
            r"^(ocio_profile_version:\s*)[\d.]+",
            rf"\g<1>{target_ver}",
            txt,
            count=1,
            flags=re.MULTILINE,
        )
        if lib_minor < 5:
            txt = re.sub(r"^\s*interchange:.*\n(?:\s+.*\n)*", "", txt, flags=re.MULTILINE)
        fd, tmp = tempfile.mkstemp(suffix=".ocio")
        try:
            os.write(fd, txt.encode("utf-8"))
            os.close(fd)
            return OCIO.Config.CreateFromFile(tmp)
        finally:
            os.unlink(tmp)


def _read_declared_version(config_path: Path) -> tuple[int, int]:
    """Read declared OCIO version from config header."""
    with open(config_path, encoding="utf-8") as f:
        header = f.read(512)
    m = re.search(r"ocio_profile_version:\s*([\d.]+)", header)
    if m:
        parts = m.group(1).split(".")
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    return 2, 4


def _list_families() -> None:
    """Print available families and exit."""
    available = discover_families(FAMILIES_DIR)
    if not available:
        print("No families found.")
        return
    print("Available vendor families:\n")
    for name, fam_dir in sorted(available.items()):
        try:
            m = load_manifest(fam_dir / "family.yaml")
            views = len(m.display_mappings)
            print(f"  {name:<16} {m.description}")
            print(f"  {'':<16} Views: {views}")
        except Exception as e:  # noqa: BLE001 — list command surfaces load errors
            print(f"  {name:<16} (error loading: {e})")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extend OCIO config with vendor display views",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        required=False,
        help="Input OCIO config file (.ocio)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output path (default: auto with timestamp)",
    )
    parser.add_argument(
        "--families",
        nargs="+",
        default=None,
        help="Family names to add, or 'all'",
    )
    parser.add_argument(
        "--list-families",
        action="store_true",
        help="List available families and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be added without writing",
    )

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
        for name in requested:
            if not re.match(r"^[a-z0-9_]+$", name):
                print(f"Error: Invalid family name: {name!r}", file=sys.stderr)
                return 1
            if name not in available:
                print(f"Error: Unknown family: {name}", file=sys.stderr)
                print(f"Available: {', '.join(sorted(available.keys()))}")
                return 1

    # Load manifests and resolve dependencies
    manifests: dict = {}
    snippet_paths: dict = {}
    luts_dirs: dict = {}
    depends_on_map: dict = {}

    for name in available:
        try:
            manifest, snippet_path, luts_dir = load_family(available[name])
            manifests[name] = manifest
            snippet_paths[name] = snippet_path
            luts_dirs[name] = luts_dir
            depends_on_map[name] = manifest.depends_on
        except Exception as e:  # noqa: BLE001
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

    print(f"\n{'=' * 70}")
    print("OCIO VENDOR DISPLAY EXTENSIONS")
    print(f"{'=' * 70}")
    print(f"Input:    {args.input}")
    if not args.dry_run:
        print(f"Output:   {args.output}")
    print(f"Families: {', '.join(order)}")
    print(f"OCIO:     {declared_major}.{declared_minor}")
    print(f"{'=' * 70}\n")

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
        for cs_n in added:
            print(f"    + CS: {cs_n}")

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
            if missing:
                for d in sorted(missing):
                    print(f"    ! Missing display: {d}")

    # Reorder views: vendor before shared ACES, after Raw
    # (wire_views_to_displays / reorder_views_for_display handle active_views)
    displays_with_vendor_views: dict[str, list[str]] = {}
    for display, view in all_wired_pairs:
        displays_with_vendor_views.setdefault(display, []).append(view)
    for display, vendor_views in displays_with_vendor_views.items():
        reorder_views_for_display(config, display, vendor_views)

    # Validate and serialize
    if not args.dry_run:
        try:
            config.validate()
        except OCIO.Exception as e:
            print(f"\nValidation warning: {e}", file=sys.stderr)

        serialized = config.serialize()
        if (config.getMajorVersion(), config.getMinorVersion()) != (
            declared_major,
            declared_minor,
        ):
            serialized = re.sub(
                r"^(ocio_profile_version:\s*)[\d.]+",
                rf"\g<1>{declared_major}.{declared_minor}",
                serialized,
                count=1,
                flags=re.MULTILINE,
            )

        args.output.parent.mkdir(parents=True, exist_ok=True)
        tmp_out = args.output.with_suffix(".tmp")
        tmp_out.write_text(serialized, encoding="utf-8")
        tmp_out.replace(args.output)

    # Report
    mode = "DRY RUN" if args.dry_run else "COMPLETE"
    print(f"\n{'=' * 70}")
    print(f"EXTENSION {mode}")
    print(f"{'=' * 70}")
    print(f"Families processed: {len(order)}")
    print(f"Color spaces added: {total_cs_added}")
    print(f"Views wired:        {total_views_wired}")
    print(f"LUTs copied:        {total_luts_copied}")
    if all_missing_displays:
        print(f"Missing displays:   {', '.join(sorted(all_missing_displays))}")
    if not args.dry_run:
        print(f"Output:             {args.output}")
    print(f"{'=' * 70}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
