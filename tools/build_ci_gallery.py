"""Add explicitly selected public CI evidence to an existing owned static build."""
import argparse,html,json,shutil
from pathlib import Path
from swe_workbench.handoff import verify,parse,require
from swe_workbench.ci_evidence import validate

ALLOWED={'view','export','summary.json','original.xml','ci-receipt.json','run-context.json','check-definition.json','package-status.json','UPSTREAM-LICENSE.txt','UPSTREAM.json'}

def build(dist, normal, external, failure):
    dist=Path(dist).resolve();require((dist/'index.html').is_file() and not (dist/'ci').exists(),'gallery: select an existing static build without ci/')
    selected=[]
    for name,title,source in [('normal','Actual workbench CI checks',normal),('external','Historical itsdangerous change',external),('intentional-failure','Intentional failing-check qualification',failure)]:
        source=Path(source).resolve();require(set(p.name for p in source.iterdir())<=ALLOWED and not any(p.is_symlink() for p in source.rglob('*')),'gallery: unexpected or linked private inputs')
        require(verify(source/'export')['ok'] and verify(source/'view/handoff')['ok'],'gallery: selected package failed verification')
        ci=validate((source/'ci-receipt.json').read_bytes(),(source/'original.xml').read_bytes(),(source/'run-context.json').read_bytes(),(source/'check-definition.json').read_bytes())
        require(ci['product_repository']==('pallets/itsdangerous' if name=='external' else 'RedRookAI/swe-data-workbench') and ci['exit_code']==(1 if name=='intentional-failure' else 0),'gallery: selected case identity/outcome differs')
        record=parse((source/'export/handoff.json').read_bytes());require(record['material']['reported_checks'][0]['ci']==ci,'gallery: provenance differs from selected export')
        require(record['state']['decision']=='unreviewed','gallery: expected original unreviewed selection')
        selected.append((name,title,source,ci,record['material']['reported_checks'][0]['counts']))
    target=dist/'ci';target.mkdir()
    cards=[]
    for name,title,source,ci,counts in selected:
        shutil.copytree(source,target/name)
        counts_text=', '.join(str(value)+' '+key for key,value in counts.items() if value)
        cards.append('<section><h2><a href="./'+name+'/view/">'+html.escape(title)+'</a></h2><p>'+html.escape(counts_text+'; process '+str(ci['exit_code'])+' ('+ci['process_outcome']+'); review unreviewed.')+'</p><p>'+html.escape(ci['product_repository']+' @ '+ci['tested_revision'])+'</p></section>')
    page='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><title>Actual CI evidence · SWE Data Workbench</title><link rel="stylesheet" href="../style.css"></head><body><main class="main"><h1>Actual CI runs, retained with their changes</h1><p>Open a selected change to inspect its source, original pytest results, observed run context and explicit review status.</p><p>The external change is historical upstream work. The intentional failure is a real, opt-in pytest assertion used to check evidence delivery after failure. All three packages remain unreviewed.</p>'+''.join(cards)+'<p>Unsigned pre/post observations supply content consistency, not independent execution attestation. The source/check scope and original report are retained in each view.</p><p><a href="../">Return to recorded reviews</a></p></main></body></html>'
    (target/'index.html').write_text(page)
    index=dist/'index.html';index.write_text(index.read_text().replace('</header>','</header><p><a id="ci-evidence-link" href="./ci/">Inspect actual CI runs, the external change and failure delivery</a></p>',1))
    return {'selected_cases':3,'private_state_included':False,'output':str(target)}
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('dist','normal','external','failure'):p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();print(json.dumps(build(a.dist,a.normal,a.external,a.failure)))
