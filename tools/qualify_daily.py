"""Installed-only daily path. Uses authored reports, not claimed test executions."""
import argparse,functools,http.server,json,os,socket,subprocess,sys,threading,time
from pathlib import Path


def run(output):
    import swe_workbench
    from swe_workbench.handoff import verify
    from swe_workbench.store import canonical
    from swe_workbench.api import create_app
    import uvicorn
    from playwright.sync_api import sync_playwright,expect
    source=Path(__file__).resolve().parents[1]
    assert not Path(swe_workbench.__file__).resolve().is_relative_to(source),'Qualification imported checkout instead of installed package.'
    output=Path(output).absolute();output.mkdir(mode=0o700);repo=output/'source';repo.mkdir()
    record={'version':swe_workbench.__version__,'installed_only':True,'report_scope':'Authored qualification reports and scripted review decisions; no claimed source test execution.','application_model_calls':0,'ok':False}
    def git(*args):return subprocess.check_output(['git','-c','core.hooksPath=/dev/null','-C',str(repo),*args],text=True).strip()
    def cli(*args):
        result=subprocess.run([sys.executable,'-I','-m','swe_workbench.cli',*map(str,args)],cwd=output,capture_output=True,text=True)
        if result.returncode:raise RuntimeError(result.stdout+result.stderr)
        return json.loads(result.stdout)
    try:
        git('init','-q');git('config','user.email','qualification@invalid.local');git('config','user.name','Authored qualification fixture')
        (repo/'value.py').write_text('value = 1\n');git('add','.');git('commit','-qm','Base authored fixture');base=git('rev-parse','HEAD')
        (repo/'value.py').write_text('value = 2\n');git('commit','-qam','First authored change');first=git('rev-parse','HEAD')
        (repo/'value.py').write_text('value = 3\n');git('commit','-qam','Second authored change');second=git('rev-parse','HEAD')
        xml=output/'authored.xml';xml.write_text('<testsuite tests="1"><testcase name="Authored report case" time="0.95000000000000001"/></testsuite>')
        context=output/'context.json';state=output/'state'
        for number,prior,candidate in [(1,base,first),(2,first,second)]:
            raw=output/('run'+str(number)+'.json');raw.write_text(json.dumps({'source_revision':candidate,'source_state':'clean','definition_sha256':'1'*64}))
            if number==1:
                cli('import-junit',xml,'--context',raw,'--output',output/'seed')
                cli('configure-project','--repo',repo,'--profile',output/'seed/profile.json','--evidence-directory',output/'seed','--state',state,'--base-ref',base,'--candidate-ref',first,'--output',context)
            package=output/('package'+str(number));cli('prepare-review',context,'--change-id','change-'+str(number),'--title','Authored qualification change'+str(number),'--goal','Inspect retained report and exact source','--report',xml,'--run-context',raw,'--base',prior,'--candidate',candidate,'--output',package)
            cli('prepare-review',context,'--output',package,'--resume')
            cli('review-selection',context,package/'selection.json','--decision','handoff-ready','--reason','Explicit scripted qualification judgment','--next-action','Inspect the retained example','--reviewer-mode','scripted_adjudication')
        cli('build-project-view',context,'--output',output/'view');cli('--root',state,'backup-state','--output',output/'backup');cli('restore-state',output/'backup','--output',output/'restored')
        cli('--root',output/'restored','export-handoff','change-1','--output',output/'restored-export');assert verify(output/'restored-export')['ok']
        app=create_app(output/'private-ui',owner_token='a'*40);sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen();port=sock.getsockname()[1]
        gateway=uvicorn.Server(uvicorn.Config(app,log_level='error'));worker=threading.Thread(target=lambda:gateway.run(sockets=[sock]),daemon=True);worker.start()
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self,*args):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(output/'view')));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            deadline=time.monotonic()+10
            while not gateway.started and worker.is_alive() and time.monotonic()<deadline:time.sleep(.01)
            assert gateway.started
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True);page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto('http://127.0.0.1:'+str(port)+'/?mode=live');expect(page.locator('#connection')).to_be_visible();page.locator('#token').fill('a'*40);page.locator('#connect-form button[type=submit]').click();expect(page.locator('#import')).to_be_enabled()
                page.goto('http://127.0.0.1:'+str(server.server_port));expect(page.locator('#attention-list section')).to_have_count(2);expect(page.locator('#attention-list')).to_contain_text('Content matches the selected package');page.get_by_role('link',name='Inspect source and results').first.click();expect(page.locator('#handoff-overview')).to_contain_text('Content matches the selected manifest');expect(page.locator('#reported-checks')).to_contain_text('1 passed');page.get_by_text('Actual reported cases and scope',exact=True).click();expect(page.locator('#reported-checks')).to_contain_text('0.95000000000000001 seconds');assert not errors;browser.close()
            record['browser']={'actual_private_module_delivery':True,'owner_connection':True,'verified_overview_to_detail':True,'original_duration_text':True,'errors':errors}
        finally:server.shutdown();server.server_close();thread.join();gateway.should_exit=True;worker.join(timeout=10);sock.close();assert not worker.is_alive()
        record.update(ok=True,composed_packages=2,explicit_scripted_reviews=2,private_restore=True)
    except Exception as error:record['error']=repr(error);raise
    finally:(output/'qualification.json').write_text(json.dumps(record,indent=2)+'\n')
    return record

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();print(json.dumps(run(args.output),indent=2))
