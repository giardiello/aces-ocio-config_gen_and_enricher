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
