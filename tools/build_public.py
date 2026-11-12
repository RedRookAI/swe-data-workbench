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

TOP_LEVEL = {"index.html", "app.js", "handoff-verify.js", "styles.css", "style.css"}
ASSET_SUFFIXES = {".css", ".js", ".png", ".jpg", ".jpeg", ".webp", ".svg", ".ico", ".woff2"}


def build_public(web_dir, export_path, output_dir=None, legacy_export=None, prior_upstream_export=None,
                 prepared_export=None, quality_record=None, evaluation_exports=None, handoff_export=None):
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
        if handoff_export is not None:
            from swe_workbench.handoff import verify as verify_handoff, FILES as HANDOFF_FILES
            if not verify_handoff(handoff_export)['ok']:
                raise ExportError('Change handoff failed verification.')
            target = stage / 'handoff'; target.mkdir()
            for name in HANDOFF_FILES:
                shutil.copyfile(Path(handoff_export) / name, target / name)
            if not verify_handoff(target)['ok']:
                raise ExportError('Copied change handoff failed verification.')
        if quality_record is not None:
            from swe_workbench.evaluation_export import verify_evaluation, FILES as EVALUATION_FILES
            quality = json.loads(Path(quality_record).read_text())
            if quality.get('schema') != 'swe-workbench-quality-demo/v1' or len(quality.get('versions', [])) != 2 or not evaluation_exports or len(evaluation_exports) != 2:
                raise ExportError('Quality publication requires two verified evaluation snapshots.')
            for index, folder in enumerate(evaluation_exports):
                folder = Path(folder)
                if not verify_evaluation(folder)['ok']:
                    raise ExportError('Evaluation export failed verification.')
                evidence = json.loads((folder / 'evidence.json').read_text())
                if evidence['scores'] != quality['versions'][index]:
                    raise ExportError('Quality display differs from its evaluation evidence.')
                target = stage / 'evaluation' / ('before' if index == 0 else 'after')
                target.mkdir(parents=True)
                for name in EVALUATION_FILES:
                    shutil.copyfile(folder / name, target / name)
                if not verify_evaluation(target)['ok']:
                    raise ExportError('Copied evaluation evidence failed verification.')
            shutil.copyfile(quality_record, stage / 'quality.json')
        for view, previous_export in [('synthetic', legacy_export), ('unicode-hyphen', prior_upstream_export), ('prepared', prepared_export)]:
            if previous_export is None:
                continue
            # A separate frozen cut keeps the original authored example inspectable.
            # Use current safe assets, preserve the old three export files verbatim.
            legacy = Path(previous_export).resolve()
            check_legacy = verify_export(legacy)
            if not check_legacy['ok']:
                raise ExportError('Preserved export failed verification: ' + view)
            for source, relative in sources:
                target = stage / view / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                if relative == Path('index.html'):
                    # Preserved views live one directory below the public root.
                    # Their fixed history links must still reach sibling views.
                    target.write_text(target.read_text().replace('href="./synthetic/"', 'href="../synthetic/"')
                                      .replace('href="./unicode-hyphen/"', 'href="../unicode-hyphen/"'))
            (stage / view / 'data').mkdir()
            for name in FILES:
                shutil.copyfile(legacy / name, stage / view / 'data' / name)
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
    parser.add_argument('--legacy-export', type=Path, help='Preserved original synthetic frozen export')
    parser.add_argument('--prior-upstream-export', type=Path, help='Preserved first upstream frozen export')
    parser.add_argument('--prepared-export', type=Path, help='Preserved prepared repository frozen export')
    parser.add_argument('--quality-record', type=Path, help='Actual paired quality record, matched against both exports')
    parser.add_argument('--handoff-export', type=Path, help='Verified read-only real-change handoff')
    parser.add_argument('--evaluation-before', type=Path)
    parser.add_argument('--evaluation-after', type=Path)
    args = parser.parse_args()
    paired = [args.evaluation_before, args.evaluation_after] if args.evaluation_before and args.evaluation_after else None
    print(json.dumps(build_public(args.web, args.export, args.output, args.legacy_export, args.prior_upstream_export,
                                  args.prepared_export, args.quality_record, paired, args.handoff_export), indent=2))


if __name__ == "__main__":
    main()
