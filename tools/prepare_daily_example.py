"""Acquire two fixed public historical handoffs for the documented operator trial.

Reads original evidence; clones committed source into a fresh owned directory.
Executes no source checks, model requests, review decisions, server or upload.
"""
import argparse,json,subprocess
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import URLError
from swe_workbench.handoff import verify,parse,require
from swe_workbench.store import canonical,digest
from swe_workbench.bundle import _read
from swe_workbench.errors import WorkbenchError

ORIGIN='https://swe-data-workbench.flyswatterghost.chatgpt.site'
CASES=[
    {'id':'startup','view':'change-b39b3e0c4fb83f37c2b2','base':'5d5e70cc1c00e28b31c11112ad8e9c148222b52a','candidate':'2e7f1d4563cb9a70d77a60e5cc3323774b692d94','xml':'37485fd26d6e453d652764b797ab47c549fabb3ab83bed774d05071d5015fdfa','context':'4a435daf816dca0d73178cf010b93f41431c843e359529994bf63eed4bfc19a9'},
    {'id':'importer','view':'change-833fc94c43fa30e26989','base':'2e7f1d4563cb9a70d77a60e5cc3323774b692d94','candidate':'217064e5637e4fa493af23cef3dc2f95c9d19a7c','xml':'51d7ddb90a039abd80b55c56608989bcbfb7e8a3431fb0c32256c56c9fed6b8e','context':'fa48e88394bd6bd9fab886e07cc6ae2d034ae817ba37933dcbce1dc67c0a51b4'}]

def prepare(output):
    output=Path(output).absolute()
    require(output.parent.is_dir() and not output.exists() and not output.is_symlink(),'example.output: choose a fresh directory under an owned existing parent')
    output.mkdir();common=None
    for selected in CASES:
        folder=output/selected['id'];original=folder/'original';original.mkdir(parents=True)
        for name in ('handoff.json','artifacts.json','manifest.json'):
            request=Request(ORIGIN+'/'+selected['view']+'/handoff/'+name,headers={'User-Agent':'swe-workbench-example/0.1'})
            with urlopen(request,timeout=30) as response:
                raw=response.read(8*1024*1024+1)
            require(len(raw)<=8*1024*1024,'example.input: published file exceeds supported limit')
            (original/name).write_bytes(raw)
        require(verify(original)['ok'],'example.input: published handoff failed semantic verification')
        material=parse(_read(original/'handoff.json'))['material']
        require(material['base_revision']==selected['base'] and material['candidate_revision']==selected['candidate'],'example.source: original revisions differ')
        projection=next(parse(a['text']) for a in material['attachments'] if a['name']=='report.json')
        xml=next(a['text'].encode() for a in material['attachments'] if a['sha256']==selected['xml'])
        context=projection['context_text'].encode()
        require(digest(xml)==selected['xml'] and digest(context)==selected['context'],'example.evidence: original hashes differ')
        (folder/'original.xml').write_bytes(xml);(folder/'run-context.json').write_bytes(context)
        profile=material['profile']['definition']
        require(common is None or common==profile,'example.profile: the selected cases no longer share one profile')
        common=profile
    (output/'profile.json').write_bytes(canonical(common)+b'\n')
    subprocess.run(['git','-c','core.hooksPath=/dev/null','clone','--no-checkout','https://github.com/RedRookAI/swe-data-workbench.git',str(output/'source')],check=True)
    # Fetching is complete before ordinary capture. No lazy network access there.
    for selected in CASES:
        for ref in ('base','candidate'):
            subprocess.run(['git','-C',str(output/'source'),'cat-file','-e',selected[ref]+'^{commit}'],check=True)
    return {'output':str(output),'cases':[c['id'] for c in CASES],'source_tests_executed':0,'model_requests':0,'notice':'Original historical reports retained. New operator judgments must be explicitly attributed; no review or publication performed.'}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    try:result=prepare(a.output)
    except (WorkbenchError,URLError,OSError,subprocess.SubprocessError) as error:
        p.exit(1,'Example acquisition failed: '+str(error)+'. Partial inputs are preserved; inspect them and choose a fresh destination.\n')
    print(json.dumps(result,indent=2))
