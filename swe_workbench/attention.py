"""Current owner-scoped attention and deterministic shareable summaries."""
from .project_context import load
from .handoff import read,parse,require
from .store import Store
from .reported_checks import extract

def _detail(root,change_id):
    return project_record(Store(root),read(root,change_id))

def project_record(store,record):
    state=record['state'];change_id=state['change_id'];reports=extract(record['material'])
    current=[r for r in reports if r.get('binding')!='declared-base-source']
    bad=any(r['status']!='reported' or r.get('binding')!='declared-same-source' or r.get('warnings') or r.get('ci',{}).get('problems') or sum(r.get('counts',{}).get(k,0) for k in ('passed','failed','error'))==0 or any(r.get('counts',{}).get(k,0) for k in ('failed','error','unavailable')) for r in current)
    if reports and not current:bad=True
    unknowns=[o['label']+': missing or unbound candidate evidence' for o in record['material']['observations'] if o['required'] and (o['value'] is None or o.get('candidate_applicability', 'declared' if o['binding']=='declared-same-source' else 'unknown')!='declared')]
    for report in reports:
        original=next((a for a in record['material']['attachments'] if a['name']==report['attachment']),None)
        if report['status']=='reported' and report.get('definition_sha256') is None and original and parse(original['text']).get('schema')=='swe-workbench-junit-report/v1':unknowns.append(report['attachment']+': check definition was not supplied')
    prior=[]
    for event in reversed(record['events'][:-1]):
        if event['kind']=='handoff-reviewed':
            previous=parse(store.artifact_bytes(event['payload']['state_digest']));prior=previous['findings'];break
    return {'change_id':change_id,'title':record['material']['title'],'goal':record['material']['goal'],'revision':state['revision'],'material_digest':state['material_digest'],'decision':state['decision'],'needs_attention':state['decision']!='handoff-ready' or bool(state['findings']) or bad or bool(unknowns),'responsible_party':state.get('responsible_party'),'next_action':state['next_action'],'findings':state['findings'],'prior_findings_for_reassessment':prior,'reports':reports,'unknowns':unknowns,'source_scope':{'files':len(record['material']['files']),'text':len(record['material'].get('coverage',{}).get('text_paths',record['material']['files'])),'metadata_only':len(record['material'].get('coverage',{}).get('metadata_only_paths',[]))},'candidate_revision':record['material']['candidate_revision'],'assurance':'Reported checks and explicit package decision; no merge/execution authorization.'}


def problem(change_id,error):
    message=error.message
    return {'change_id':change_id,'title':change_id,'goal':'','revision':None,'material_digest':None,'decision':'unavailable','needs_attention':True,'responsible_party':None,'next_action':'Inspect the named evidence problem; preserve the original state.','findings':[message],'prior_findings_for_reassessment':[],'reports':[],'candidate_revision':None,'problem':{'code':error.code,'message':message},'assurance':'This change could not be verified; no ready state is asserted.'}

def detail(root,change_id):
    from .errors import WorkbenchError
    try:return _detail(root,change_id)
    except WorkbenchError as error:
        if error.code in ('audit-integrity','database-integrity','database-mode','schema-version'):raise
        return problem(change_id,error)

def list_changes(path,only_attention=False):
    from .project_scope import check
    from .handoff import _load
    from .errors import WorkbenchError
    import sqlite3
    context=load(path);store=Store(context['state'])
    if not store.db.exists():return {'changes':[],'runtime_writes':0}
    selected=[]
    try:
        with store.transaction(write=False) as con:
            events=store.validated_events(con);check(context,con=con,store=store)
            grouped={}
            for event in events:
                if event['kind'].startswith('handoff-'):grouped.setdefault(event['payload'].get('change_id'),[]).append(event)
            ids=[row[0][len('handoff:'):] for row in con.execute("SELECT key FROM meta WHERE key LIKE 'handoff:%' ORDER BY key")]
            for key in ids:
                try:
                    state,material,history=_load(store,con,key,grouped.get(key,[]))
                    selected.append({'state':state,'material':material,'events':history})
                except WorkbenchError as error:selected.append(problem(key,error))
    except (sqlite3.DatabaseError,ValueError,TypeError,KeyError) as error:
        raise WorkbenchError('database-integrity','Cannot verify the global database/audit cut.',409) from error
    # Database read lock is released before report projection, source serving or HTML generation.
    rows=[]
    for record in selected:
        if record.get('problem'):rows.append(record);continue
        try:rows.append(project_record(store,record))
        except WorkbenchError as error:rows.append(problem(record['state']['change_id'],error))
    if only_attention:rows=[row for row in rows if row['needs_attention']]
    return {'changes':rows,'scope':'One validated project state cut; immutable evidence verified by hash. No publisher identity or urgency is inferred.'}

def summary(path,change_id):
    context=load(path)
    from .project_scope import check
    check(context)
    d=detail(context['state'],change_id)
    def line(text):return str(text).replace('\r',' ').replace('\n',' ')
    parts=['# '+line(d['title']),'',line(d['goal']),'','Package decision: '+d['decision'],'Source: '+(d['candidate_revision'] or 'Unavailable'),'Material: '+(d['material_digest'] or 'Unavailable'),'Review revision: '+str(d['revision']),'Responsible party: '+line(d['responsible_party'] or 'Unassigned'),'Next action: '+line(d['next_action']),'','Reported results:']
    for report in d['reports']:
        if report['status']!='reported':parts.append('- Invalid supported report; inspect retained evidence.');continue
        parts.append('- '+report['binding']+': '+', '.join(str(v)+' '+k for k,v in report['counts'].items()))
        if report.get('ci'):
            ci=report['ci'];parts.extend(['  Process: '+str(ci['exit_code'])+' ('+ci['process_outcome']+'); report: '+ci['report_status'], '  Tested product: '+ci['product_repository']+' @ '+str(ci['tested_revision']), '  Observed source: '+ci['source_state']])
            if ci['provider']:
                p=ci['provider'];parts.extend(['  Workflow: '+p['repository']+' @ '+p['workflow_revision']+'; job '+p['job']+'; attempt '+p['attempt'],ci['run_url']])
            else:parts.append('  Local run; no CI provider identity.')
            parts.extend('  Evidence issue: '+line(x) for x in ci['problems'])
    if not d['reports']:parts.append('- No supported check report; generic observations remain available in the handoff.')
    parts.extend(['','Unresolved findings:',*[('- '+line(f)) for f in d['findings']]])
    if not d['findings']:parts.append('- No current findings recorded; evidence completeness is separate.')
    if d['prior_findings_for_reassessment']:parts.extend(['','Prior findings for reassessment:',*[('- '+line(f)) for f in d['prior_findings_for_reassessment']]])
    parts.extend(['',d['assurance']]);return {'summary':'\n'.join(parts)+'\n','revision':d['revision'],'material_digest':d['material_digest']}
