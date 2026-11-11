"""Locate authored assets in a source checkout or an installed wheel."""
from pathlib import Path
import sys
from .errors import WorkbenchError

def bundled_directory(name: str) -> Path:
    if name not in {"fixtures", "web"}:
        raise ValueError("Unknown bundled asset directory")
    marker = "catalog.json" if name == "fixtures" else "index.html"
    source = Path(__file__).resolve().parent.parent / name
    installed = Path(sys.prefix) / "share" / "swe-data-workbench" / name
    for candidate in (source, installed):
        if (candidate / marker).is_file():
            return candidate
    raise FileNotFoundError("Bundled workbench assets are missing: " + name)


def resolve_bundle(value) -> Path:
    """Resolve an owner-selected local catalog; never fetch remote content."""
    if value is None:
        return bundled_directory('fixtures')
    if str(value) == 'unicode-hyphen':
        candidates = (Path(__file__).resolve().parent.parent / 'bundles' / 'unicode-hyphen',
                      Path(sys.prefix) / 'share' / 'swe-data-workbench' / 'bundles' / 'unicode-hyphen')
    else:
        candidates = (Path(value).expanduser(),)
    for candidate in candidates:
        if (candidate / 'catalog.json').is_file():
            return candidate.resolve()
    raise WorkbenchError('bundle-unavailable', 'Selected local task bundle is unavailable.', 404)

