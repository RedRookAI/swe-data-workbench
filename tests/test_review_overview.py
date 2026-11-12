import functools,http.server,json,threading
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
from swe_workbench import project_context as project
from swe_workbench.junit_report import import_report
from swe_workbench.handoff_view import build_project

def make_review_fixture(output):
    from tests.test_daily_workflow import DailyTests
    fixture=DailyTests();fixture.setUp()
    try:
        context=fixture.context();raw='{"source":"'+fixture.candidate+'","check":{"metric":0.95000000000000001,"tiny":1e-400}}';fixture.proof.write_text(raw)
        selection=fixture.p/'exact-selection.json';project.collect(context,change_id='exact',title='Exact synthetic metric',goal='Retain authored numeric fixture values',output=selection)
        fields=dict(decision='handoff-ready',reason='Explicit scripted fixture judgment',findings=[],next_action='Inspect the retained source',reviewer_mode='scripted_adjudication')
        project.review_selection(context,selection,**fields)
        xml=fixture.p/'results.xml';xml.write_text('<testsuite tests="2" failures="1" skipped="1"><testcase name="failed"><failure message="Authored fixture failure"/></testcase><testcase name="skipped"><skipped/></testcase></testsuite>')
        run=fixture.p/'run.json';run.write_text(json.dumps({'source_revision':fixture.candidate,'source_state':'clean'}));import_report(xml,fixture.p/'import',run)
        profile=json.loads((fixture.p/'import/profile.json').read_text());profile['repository']='example-project';(fixture.p/'a-profile.json').write_text(json.dumps(profile))
        # Context retains the original selected profile path and exact project identity.
        cdata=json.loads(context.read_text());Path(cdata['profile']).write_text(json.dumps(profile));selection=fixture.p/'report-selection.json'
        project.collect(context,change_id='reported',title='Authored failing report',goal='Show failure separately from package decision',evidence_directory=fixture.p/'import',output=selection)
        project.review_selection(context,selection,**fields)
        build_project(context,output)
    finally:fixture.doCleanups()

def test_verified_overview_exact_values_and_failure_cases(tmp_path):
    view=tmp_path/'view';make_review_fixture(view)
    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self,*args):pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(view)));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];requests=[]
            page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:requests.append(r.url));origin='http://127.0.0.1:'+str(server.server_port)
            page.goto(origin);expect(page.locator('#attention-list section')).to_have_count(2);expect(page.locator('#attention-list')).to_contain_text('1 failed');expect(page.locator('#attention-list')).to_contain_text('check definition was not supplied')
            page.locator('#attention-filter').select_option('attention');expect(page.locator('#attention-list section')).to_have_count(1);page.locator('#attention-filter').select_option('all')
            page.get_by_role('link',name='Inspect source and results').first.click();expect(page.locator('#handoff-overview')).to_contain_text('Content matches the selected manifest');page.get_by_text('Reported evidence and scope (1)',exact=True).click();expect(page.locator('#handoff-content')).to_contain_text('0.95000000000000001');expect(page.locator('#handoff-content')).to_contain_text('1e-400')
            baseline=json.loads((view/'attention.json').read_text());altered=json.loads(json.dumps(baseline));altered['changes'][0].update(decision='needs-work',revision=999,material_digest='0'*64,needs_attention=False)
            page.route('**/attention.json',lambda route:route.fulfill(body=json.dumps(altered),content_type='application/json'));page.goto(origin);expect(page.locator('#attention-list')).to_contain_text('Overview differs from its verified package');page.locator('#attention-filter').select_option('attention');expect(page.locator('#attention-list section')).to_have_count(2)
            page.unroute('**/attention.json');leaf=baseline['changes'][0]['view'];page.route('**/'+leaf+'handoff/artifacts.json',lambda route:route.fulfill(status=404,body='missing'));page.goto(origin);expect(page.locator('#attention-list')).to_contain_text('Could not verify this selected change');expect(page.locator('#attention-list section').nth(1)).to_contain_text('Content matches the selected package')
            page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');assert not errors;assert not any('/api/' in x or '/data/' in x for x in requests);browser.close()
    finally:server.shutdown();server.server_close();thread.join()
