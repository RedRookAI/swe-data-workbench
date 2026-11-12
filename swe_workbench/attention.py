"""Current owner-scoped attention and deterministic shareable summaries."""
from .project_context import load
from .handoff import read,parse,require
from .store import Store
from .reported_checks import extract

def detail(root,change_id):
    record=read(root,change_id);state=record['state'];reports=extract(record['material'])
    current=[r for r in reports if r.get('binding')!='declared-base-source']
    bad=any(r['status']!='reported' or r.get('binding')!='declared-same-source' or r.get('warnings') or sum(r.get('counts',{}).get(k,0) for k in ('passed','failed','error'))==0 or any(r.get('counts',{}).get(k,0) for k in ('failed','error','unavailable')) for r in current)
    if reports and not current:bad=True
    prior=[];store=Store(root)
    for event in reversed(record['events'][:-1]):
        if event['kind']=='handoff-reviewed':
            previous=parse(store.artifact_bytes(event['payload']['state_digest']));prior=previous['findings'];break
    return {'change_id':change_id,'title':record['material']['title'],'goal':record['material']['goal'],'revision':state['revision'],'material_digest':state['material_digest'],'decision':state['decision'],'needs_attention':state['decision']!='handoff-ready' or bool(state['findings']) or bad,'responsible_party':state.get('responsible_party'),'next_action':state['next_action'],'findings':state['findings'],'prior_findings_for_reassessment':prior,'reports':reports,'candidate_revision':record['material']['candidate_revision'],'assurance':'Reported checks and explicit package decision; no merge/execution authorization.'}

def list_changes(path,only_attention=False):
    context=load(path);store=Store(context['state'])
    if not store.db.exists():return {'changes':[],'runtime_writes':0}
    store.initialize()
    with store.transaction(write=False) as con:ids=[row[0][len('handoff:'):] for row in con.execute("SELECT key FROM meta WHERE key LIKE 'handoff:%' ORDER BY key")]
    rows=[detail(context['state'],key) for key in ids]
    if only_attention:rows=[row for row in rows if row['needs_attention']]
    return {'changes':rows,'scope':'Selected owned state only; urgency and identity are not inferred.'}

def summary(path,change_id):
    context=load(path);d=detail(context['state'],change_id)
    def line(text):return str(text).replace('\r',' ').replace('\n',' ')
    parts=['# '+line(d['title']),'',line(d['goal']),'','Package decision: '+d['decision'],'Source: '+d['candidate_revision'],'Material: '+d['material_digest'],'Review revision: '+str(d['revision']),'Responsible party: '+line(d['responsible_party'] or 'Unassigned'),'Next action: '+line(d['next_action']),'','Reported results:']
    for report in d['reports']:
        if report['status']!='reported':parts.append('- Invalid supported report; inspect retained evidence.');continue
        parts.append('- '+report['binding']+': '+', '.join(str(v)+' '+k for k,v in report['counts'].items()))
    if not d['reports']:parts.append('- No supported check report; generic observations remain available in the handoff.')
    parts.extend(['','Unresolved findings:',*[('- '+line(f)) for f in d['findings']]])
    if not d['findings']:parts.append('- No current findings recorded; evidence completeness is separate.')
    if d['prior_findings_for_reassessment']:parts.extend(['','Prior findings for reassessment:',*[('- '+line(f)) for f in d['prior_findings_for_reassessment']]])
    parts.extend(['',d['assurance']]);return {'summary':'\n'.join(parts)+'\n','revision':d['revision'],'material_digest':d['material_digest']}
