#!/usr/bin/env python3
"""Build a static evidence explorer from approved web assets and a verified export."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from swe_workbench.exporter import FILES, ExportError, verify_export

TOP_LEVEL = {"index.html", "app.js", "styles.css", "style.css"}
ASSET_SUFFIXES = {".css", ".js", ".png", ".jpg", ".jpeg", ".webp", ".svg", ".ico", ".woff2"}


def build_public(web_dir, export_path, output_dir=None):
    web, exported = Path(web_dir).resolve(), Path(export_path).resolve()
    output = Path(output_dir or REPO / "dist").absolute()
    if output.name != "dist" or output.is_symlink():
        raise ExportError("Public output must be a non-symlink directory named dist.")
    if output.resolve() in (web, exported) or output.resolve() in web.parents or output.resolve() in exported.parents:
        raise ExportError("Public output cannot contain input directories.")
    check = verify_export(exported)
    if not check["ok"]:
        raise ExportError("Public build requires a verified frozen export: " + "; ".join(check["errors"]))
    sources = []
    for source in sorted(web.rglob("*")):
        relative = source.relative_to(web)
        if source.is_symlink():
            raise ExportError("Symlinks are not public assets.")
        if not source.is_file():
            continue
        if ((len(relative.parts) == 1 and relative.name in TOP_LEVEL)
                or (relative.parts[0] == "assets" and source.suffix.lower() in ASSET_SUFFIXES)):
            sources.append((source, relative))
    if not any(str(relative) == "index.html" for _, relative in sources):
        raise ExportError("Missing web/index.html.")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".public-build-", dir=output.parent))
    try:
        for source, relative in sources:
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        data = stage / "data"
        data.mkdir()
        for name in FILES:
            shutil.copyfile(exported / name, data / name)
        (stage / ".nojekyll").write_bytes(b"")
        if not verify_export(exported)["ok"]:
            raise ExportError("Export changed while building public assets.")
        copied = verify_export(data)
        if not copied["ok"]:
            raise ExportError("Copied public evidence failed verification.")
        if output.exists():
            # Only replace a prior generated build, never recursively erase an arbitrary directory.
            marker = output / ".swe-public-build"
            if not marker.is_file() or marker.read_text() != "swe-workbench-public-v1\n":
                raise ExportError("Refusing to replace a directory without the public-build marker.")
            shutil.rmtree(output)
        (stage / ".swe-public-build").write_text("swe-workbench-public-v1\n")
        stage.rename(output)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return {"output": str(output), "export_id": check["export_id"], "manifest_digest": check["manifest_digest"],
            "files": sorted(str(path.relative_to(output)) for path in output.rglob("*") if path.is_file())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path, help="Verified content-addressed export directory")
    parser.add_argument("--web", type=Path, default=REPO / "web")
    parser.add_argument("--output", type=Path, default=REPO / "dist")
    args = parser.parse_args()
    print(json.dumps(build_public(args.web, args.export, args.output), indent=2))


if __name__ == "__main__":
    main()
