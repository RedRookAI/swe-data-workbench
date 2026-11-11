"""Locate authored assets in a source checkout or an installed wheel."""
from pathlib import Path
import sys

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

