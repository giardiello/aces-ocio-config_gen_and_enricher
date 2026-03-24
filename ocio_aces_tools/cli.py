#!/usr/bin/env python3
"""
Unified CLI for OCIO/ACES tools.

Run as: python -m ocio_aces_tools <subcommand> [args...]
Or: ocio_aces_tool <subcommand> [args...]  (if entry point is installed)
"""
import argparse
import sys
from pathlib import Path

# Ensure project root is on path when running as python -m ocio_aces_tools
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def main():
    parser = argparse.ArgumentParser(
        prog="ocio_aces_tool",
        description="Unified OCIO/ACES tools: upgrade, map, validate, split, enrich, LUT build/verify, repo utilities.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Subcommands:
  upgrade       Upgrade OCIO v2.4 config to v2.5
  map           Correlate ACES transform IDs with OCIO color space names
  validate-amf  Validate AMF output transform URN → Display+View mappings
  split         Split one OCIO config into ACES 1.x and 2.0 configs
  enrich        Enrich OCIO config with ACES IDs and missing color spaces
  lut-build     Generate CLF-based OCIO 2.1 config from ACES 2.0
  lut-verify    Verify LUT-based config against BuiltIn reference
  repo          Repository utilities: extract | compare
  extend        Extend OCIO config with vendor display views

Examples:
  python -m ocio_aces_tools upgrade input.ocio -o output.ocio
  python -m ocio_aces_tools map transforms.json config.ocio -o out/
  python -m ocio_aces_tools validate-amf config.ocio -o reports/
  python -m ocio_aces_tools split merged.ocio v1.ocio v2.ocio
  python -m ocio_aces_tools enrich -i studio.ocio -o out.ocio --aces-version 2.0 --config-type studio
  python -m ocio_aces_tools lut-build reference.ocio -o out/
  python -m ocio_aces_tools lut-verify reference.ocio lut_config.ocio
  python -m ocio_aces_tools repo extract -i config.ocio -o repo/ --aces-version aces_2.0 --config-type reference
  python -m ocio_aces_tools repo compare --source a.ocio --reference b.ocio
        """,
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Subcommand to run")

    # ---- upgrade ----
    subparsers.add_parser("upgrade", help="Upgrade OCIO v2.4 config to v2.5 format")

    # ---- map ----
    subparsers.add_parser("map", help="Correlate ACES transform IDs with OCIO names; generate reports")

    # ---- validate-amf ----
    subparsers.add_parser("validate-amf", help="Validate AMF output transform URN → Display+View mappings")

    # ---- split ----
    p_split = subparsers.add_parser("split", help="Split OCIO config into ACES 1.x and 2.0 configs")
    p_split.add_argument("input_config", type=Path, help="Input OCIO config")
    p_split.add_argument("output_v1", type=Path, help="Output path for ACES 1.x config")
    p_split.add_argument("output_v2", type=Path, help="Output path for ACES 2.0 config")

    # ---- enrich ----
    subparsers.add_parser("enrich", help="Enrich OCIO config with ACES IDs and missing color spaces")

    # ---- lut-build ----
    subparsers.add_parser("lut-build", help="Generate CLF-based OCIO 2.1 config from ACES 2.0")

    # ---- lut-verify ----
    subparsers.add_parser("lut-verify", help="Verify LUT-based config against BuiltIn reference")

    # ---- repo (nested) ----
    p_repo = subparsers.add_parser("repo", help="Repository utilities: extract color spaces or compare configs")
    repo_sub = p_repo.add_subparsers(dest="repo_cmd")
    repo_sub.add_parser("extract", help="Extract color spaces from config into repository")
    repo_sub.add_parser("compare", help="Compare two configs to find missing color spaces")

    # ---- extend ----
    subparsers.add_parser("extend", help="Extend OCIO config with vendor display views")

    # Parse only the subcommand (and split's positionals); rest goes to the underlying script
    args, remainder = parser.parse_known_args()

    if not args.subcommand:
        parser.print_help()
        return 1

    if args.subcommand == "split":
        return _run_split(args)
    if args.subcommand == "upgrade":
        return _run_via_argv("upgrade_ocio_v24_to_v25.py", remainder, "upgrade_ocio_v24_to_v25")
    if args.subcommand == "map":
        return _run_via_argv("ACES_json_to_OCIOmapping.py", remainder, "ACES_json_to_OCIOmapping")
    if args.subcommand == "validate-amf":
        return _run_via_argv("validate_amf_output_transforms.py", remainder, "validate_amf_output_transforms")
    if args.subcommand == "enrich":
        return _run_via_argv("enrich_ocio_config.py", remainder, "ocio_aces_enricher.scripts.enrich_ocio_config")
    if args.subcommand == "lut-build":
        return _run_via_argv("generate_lut_based_config.py", remainder, "generate_lut_based_config")
    if args.subcommand == "lut-verify":
        return _run_via_argv("verify_lut_vs_builtin.py", remainder, "verify_lut_vs_builtin")
    if args.subcommand == "repo":
        if not getattr(args, "repo_cmd", None):
            p_repo.print_help()
            return 1
        if args.repo_cmd == "extract":
            return _run_via_argv("extract_colorspaces.py", remainder, "ocio_aces_enricher.scripts.extract_colorspaces")
        if args.repo_cmd == "compare":
            return _run_via_argv("compare_configs.py", remainder, "ocio_aces_enricher.scripts.compare_configs")

    if args.subcommand == "extend":
        return _run_via_argv(
            "extend_ocio_config.py", remainder, "ocio_vendor_extensions.extend_config"
        )

    return 1


def _run_split(args):
    """Call split_config_by_aces_version with parsed args."""
    try:
        import split_config_by_aces_version as split_mod
    except ImportError:
        # Run from repo root so project root is on path
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import split_config_by_aces_version as split_mod
    if not args.input_config.exists():
        print(f"Error: Input config not found: {args.input_config}")
        return 1
    split_mod.split_config_by_aces_version(
        args.input_config,
        args.output_v1,
        args.output_v2,
    )
    return 0


def _run_via_argv(prog_name, remainder, module_path):
    """Set sys.argv to [prog_name] + remainder and call module's main()."""
    old_argv = sys.argv
    try:
        sys.argv = [prog_name] + remainder
        if module_path == "upgrade_ocio_v24_to_v25":
            import upgrade_ocio_v24_to_v25 as mod
        elif module_path == "ACES_json_to_OCIOmapping":
            import ACES_json_to_OCIOmapping as mod  # noqa: N811
        elif module_path == "validate_amf_output_transforms":
            import validate_amf_output_transforms as mod
        elif module_path == "ocio_aces_enricher.scripts.enrich_ocio_config":
            from ocio_aces_enricher.scripts import enrich_ocio_config as mod
        elif module_path == "generate_lut_based_config":
            import generate_lut_based_config as mod
        elif module_path == "verify_lut_vs_builtin":
            import verify_lut_vs_builtin as mod
        elif module_path == "ocio_aces_enricher.scripts.extract_colorspaces":
            from ocio_aces_enricher.scripts import extract_colorspaces as mod
        elif module_path == "ocio_aces_enricher.scripts.compare_configs":
            from ocio_aces_enricher.scripts import compare_configs as mod
        elif module_path == "ocio_vendor_extensions.extend_config":
            from ocio_vendor_extensions import extend_config as mod
        else:
            raise ValueError(f"Unknown module: {module_path}")
        exit_code = mod.main()
        return int(exit_code) if exit_code is not None else 0
    except SystemExit as e:
        return e.code if e.code is not None else 0
    finally:
        sys.argv = old_argv


if __name__ == "__main__":
    sys.exit(main())
