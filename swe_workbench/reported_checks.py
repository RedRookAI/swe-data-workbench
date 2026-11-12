"""Read explicit supported report types; generic values never become check passes."""
from .handoff import parse
from .store import canonical,digest
from .errors import WorkbenchError

def extract(material):
    from .junit_report import project,SCHEMA as JUNIT
    from .check_receipt import validate,SCHEMA as RECEIPT
    reports=[];attachments=material['attachments']
    for attachment in attachments:
        try:data=parse(attachment['text'])
        except WorkbenchError:continue
        if not isinstance(data,dict) or data.get('schema') not in (JUNIT,RECEIPT):continue
        try:
            if data['schema']==JUNIT:
                original=next((a for a in attachments if a['sha256']==data.get('report_sha256')),None)
                if original is None:raise ValueError('Original XML attachment missing')
                context=data.get('context_text')
                if context is not None and not isinstance(context,str):raise ValueError('report.context_text: expected text or null')
                expected=project(original['text'].encode(),None if context is None else context.encode())
                if canonical(expected)!=canonical(data):raise ValueError('Projection differs from original XML/context')
                cases=data['cases'];warnings=data['aggregate_warnings'];definition=data['definition_sha256']
            else:
                validate(data);cases=[{'id':name,'name':name,'outcome':check['outcome'],'duration_seconds':None} for name,check in data['checks'].items()];warnings=[];definition=None
            revision=data['execution_revision'];binding='unbound' if revision is None else ('declared-same-source' if revision==material['candidate_revision'] else ('declared-base-source' if revision==material.get('base_revision') else 'declared-other-source'))
            counts={name:sum(c['outcome']==name for c in cases) for name in ('passed','failed','error','skipped','unavailable')}
            reports.append({'attachment':attachment['name'],'status':'reported','binding':binding,'revision':revision,'counts':counts,'cases':cases,'warnings':warnings,'definition_sha256':definition,'assurance':'Externally reported outcomes; package readiness is separate from code acceptance.'})
        except (WorkbenchError,ValueError,KeyError,TypeError) as exc:
            reports.append({'attachment':attachment['name'],'status':'invalid-supported-report','error':str(exc)})
    return reports
