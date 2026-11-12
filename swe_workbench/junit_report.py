"""Import a bounded local pytest/JUnit report. Reports never execute commands."""
import math,re,tempfile,shutil,json
from pathlib import Path
from xml.etree.ElementTree import XMLPullParser,ParseError
from .bundle import _read,_text,_publish,_fsync_directory
from .handoff import parse,require
from .store import canonical,digest
from .intake import MAX_RECORDS
from . import handoff_validation as v

SCHEMA='swe-workbench-junit-report/v1'
ASSURANCE='Parsed external test report; supplied execution context is not authenticated.'

def project(raw,context_raw=None):
    _text(raw,'JUnit XML')
    require(not re.search(br'<!\s*(?:DOCTYPE|ENTITY)',raw,re.I),'junit.xml: DTD/entities are unsupported')
    parser=XMLPullParser(events=('start','end'));root=None;depth=0;nodes=0
    try:
        for at in range(0,len(raw),16384):
            parser.feed(raw[at:at+16384])
            for event,element in parser.read_events():
                if event=='start':
                    root=element if root is None else root;depth+=1;nodes+=1
                    require(depth<=128 and nodes<=MAX_RECORDS,'junit.xml: nesting/node limit exceeded')
                else:depth-=1
        parser.close()
    except ParseError as exc:raise ValueError('junit.xml: malformed XML: '+str(exc)) from exc
    require(root is not None and root.tag in ('testsuites','testsuite'),'junit.xml: expected pytest testsuites/testsuite')
    context=parse(context_raw) if context_raw is not None else {}
    v.obj(context,'junit.context',(),('schema','source_revision','source_state','definition_sha256','inputs','assurance'))
    if 'schema' in context:require(context['schema']=='swe-workbench-run-context/v1','junit.context.schema: unsupported')
    revision=context.get('source_revision');state=context.get('source_state','unknown');definition=context.get('definition_sha256')
    if revision is not None:v.sha(revision,'junit.context.source_revision',git=True)
    require(state in ('clean','dirty','unknown'),'junit.context.source_state: expected clean/dirty/unknown')
    if definition is not None:v.sha(definition,'junit.context.definition_sha256')
    inputs=context.get('inputs',{});require(isinstance(inputs,dict),'junit.context.inputs: expected named digests')
    for key,value in inputs.items():v.text(key,'junit.context.inputs.key');v.sha(value,'junit.context.inputs.'+key)
    cases=[];occurrences={};counts={k:0 for k in ('passed','failed','error','skipped')}
    for case in root.iter('testcase'):
        name=case.get('name');require(bool(name),'junit.testcase.name: required')
        classname=case.get('classname','');identity=classname+'::'+name;number=occurrences.get(identity,0);occurrences[identity]=number+1
        flags=[tag for tag in ('failure','error','skipped') if case.find(tag) is not None]
        require(len(flags)<=1,'junit.testcase: ambiguous outcomes')
        outcome={'failure':'failed','error':'error','skipped':'skipped'}.get(flags[0] if flags else None,'passed');duration=case.get('time')
        if duration is not None:
            try:numeric=float(duration)
            except ValueError:raise ValueError('junit.testcase.time: expected finite nonnegative seconds')
            require(math.isfinite(numeric) and numeric>=0,'junit.testcase.time: expected finite nonnegative seconds')
        else:numeric=None
        detail=case.find(flags[0]) if flags else None
        cases.append({'id':digest((identity+'\0'+str(number)).encode()),'name':name,'classname':classname,'occurrence':number,'outcome':outcome,'duration_seconds':numeric,'duration_text':duration,'detail':None if detail is None else {'message':detail.get('message',''),'text':detail.text or ''}});counts[outcome]+=1
    warnings=[]
    for suite in root.iter('testsuite'):
        children=list(suite.iter('testcase'));observed={'tests':len(children),'failures':sum(c.find('failure') is not None for c in children),'errors':sum(c.find('error') is not None for c in children),'skipped':sum(c.find('skipped') is not None for c in children)}
        for key,actual in observed.items():
            if key in suite.attrib:
                try:declared=int(suite.attrib[key]);require(declared>=0,'junit.suite.'+key+': expected nonnegative count')
                except ValueError:raise ValueError('junit.suite.'+key+': expected integer')
                if declared!=actual:warnings.append({'suite':suite.get('name',''),'field':key,'declared':declared,'observed':actual})
    return {'schema':SCHEMA,'report_sha256':digest(raw),'context_sha256':None if context_raw is None else digest(context_raw),'context_text':None if context_raw is None else _text(context_raw,'Run context'),'execution_revision':revision if state=='clean' else None,'source_state':state,'definition_sha256':definition,'inputs':inputs,'cases':cases,'counts':counts,'executed':counts['passed']+counts['failed']+counts['error'],'aggregate_warnings':warnings,'assurance':ASSURANCE}

def import_report(path,output,context=None,ci_receipt=None,check_definition=None):
    raw=_read(path);context_raw=_read(context) if context else None
    try:report=project(raw,context_raw)
    except (ValueError,TypeError) as exc:
        from .errors import WorkbenchError
        raise WorkbenchError('junit-report',str(exc)) from exc
    extras={};ci=None
    if ci_receipt is not None or check_definition is not None:
        require(ci_receipt is not None and check_definition is not None and context_raw is not None,'junit.ci: supply receipt, definition and run context together')
        from .ci_evidence import validate
        ci_raw=_read(ci_receipt);definition_raw=_read(check_definition);ci=validate(ci_raw,raw,context_raw,definition_raw)
        report['ci_receipt_sha256']=digest(ci_raw);extras={'ci-receipt.json':ci_raw,'check-definition.json':definition_raw}
    target=Path(output).absolute();require(target.parent.is_dir() and not target.exists() and not target.is_symlink(),'junit.output: choose a fresh directory')
    profile={'schema':'swe-workbench-handoff-profile/v1','id':'pytest-results','version':'1','repository':'owner-selected-project','attachments':['report.json','original.xml'],'observations':[{'label':'Reported '+name,'attachment':'report.json','field_path':['counts',name],'context_path':['execution_revision'],'required':True,'scope':'Count of '+name+' cases in the selected external pytest report.'} for name in ('passed','failed','error','skipped')]}
    profile['attachments'].extend(extras)
    if ci is not None:
        profile['id']='pytest-ci-results'
        profile['repository']=ci['product_repository']
    stage=Path(tempfile.mkdtemp(prefix='.junit-',dir=target.parent))
    try:
        (stage/'original.xml').write_bytes(raw);(stage/'report.json').write_bytes(canonical(report)+b'\n');(stage/'profile.json').write_bytes(canonical(profile)+b'\n')
        for name,content in extras.items():(stage/name).write_bytes(content)
        for f in stage.iterdir():
            with f.open('rb') as stream:__import__('os').fsync(stream.fileno())
        _fsync_directory(stage);_publish(stage,target);_fsync_directory(target.parent)
        return {'output':str(target),'report_sha256':report['report_sha256'],'counts':report['counts'],'execution_revision':report['execution_revision'],'warnings':report['aggregate_warnings'],'assurance':ASSURANCE}
    finally:
        if stage.exists():shutil.rmtree(stage)
