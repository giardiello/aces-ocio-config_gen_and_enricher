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
