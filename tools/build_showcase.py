"""Refresh a selected static preview with tracked display assets and original evidence.

Input is an explicitly chosen prior public preview, not a private workspace/state.
Only fixed evidence routes and media are read; output must be fresh and owned.
"""
import argparse,json,re,shutil,tempfile,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from swe_workbench.handoff import verify,parse,require
from swe_workbench.handoff_view import build
from build_public import build_public
from build_ci_gallery import build as build_ci


def refresh(selected,output):
    selected=Path(selected).resolve();output=Path(output).absolute()
    require(output.parent.is_dir() and not output.exists() and not output.is_symlink(),'showcase.output: choose a fresh owned directory')
    require(not output.resolve().is_relative_to(selected) and not selected.is_relative_to(output.resolve()),'showcase: input/output overlap')
    require(not any(p.is_symlink() for p in selected.rglob('*')),'showcase: selected input contains a symlink')
    index=parse((selected/'attention.json').read_bytes());require(index['schema']=='swe-workbench-attention/v1','showcase: unsupported attention input')
    # Validate every selected leaf before publishing any output.
    for entry in index['changes']:
        path=entry['view'];require(isinstance(path,str) and re.fullmatch(r'change-[a-f0-9]{20}/',path),'showcase: unsupported selected path')
        source=selected/path/'handoff';require(verify(source)['ok'],'showcase: selected change failed verification')
        record=parse((source/'handoff.json').read_bytes())
        require(all(entry[k]==record['state'][k] for k in ('change_id','revision','material_digest','decision')),'showcase: overview identity differs')
    stage=Path(tempfile.mkdtemp(prefix='.showcase-',dir=output.parent))
    try:
        web=ROOT/'web'
        for name in ('attention.html','attention.js','handoff-verify.js','style.css'):shutil.copyfile(web/name,stage/('index.html' if name=='attention.html' else name))
        shutil.copyfile(selected/'attention.json',stage/'attention.json')
        for entry in index['changes']:build(selected/entry['view']/'handoff',stage/entry['view'])
        old=selected/'evaluation-demo';native=stage/'native-build';native.mkdir()
        build_public(web,old/'data',native/'dist',legacy_export=old/'synthetic/data',prior_upstream_export=old/'unicode-hyphen/data',prepared_export=old/'prepared/data',quality_record=old/'quality.json',evaluation_exports=[old/'evaluation/before',old/'evaluation/after'],handoff_export=old/'handoff')
        (native/'dist').rename(stage/'evaluation-demo');native.rmdir()
        for route in ('','synthetic','unicode-hyphen','prepared'):
            for name in ('recording.webm','captions.vtt'):
                source=old/route/name
                if source.is_file():shutil.copyfile(source,stage/'evaluation-demo'/route/name)
        # Preserve the original top-level aliases with refreshed renderers.
        for route in ('synthetic','unicode-hyphen','prepared'):
            for name in ('evidence.json','manifest.json','accepted.jsonl'):
                require((selected/route/'data'/name).read_bytes()==(old/route/'data'/name).read_bytes(),'showcase: historical alias data differs')
            shutil.copytree(stage/'evaluation-demo'/route,stage/route)
        build_ci(stage,selected/'ci/normal',selected/'ci/external',selected/'ci/intentional-failure')
        # CI exports are historical; their rendering uses this checkpoint's assets.
        for name in ('normal','external','intentional-failure'):
            view=stage/'ci'/name/'view';shutil.rmtree(view);build(stage/'ci'/name/'export',view)
        (stage/'.nojekyll').write_bytes(b'')
        from swe_workbench.bundle import _publish
        _publish(stage,output)
        return {'output':str(output),'changes':len(index['changes']),'selected_data_preserved':True,'source_tests_executed':0,'model_requests':0}
    finally:
        if stage.exists():shutil.rmtree(stage)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--selected',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(refresh(a.selected,a.output),indent=2))
