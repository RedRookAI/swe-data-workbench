"""Changed current-content checks against frozen public bytes, served locally."""
import functools,http.server,json,os,threading
from pathlib import Path
from swe_workbench.store import digest
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]

def test_manifest_and_current_content_gate():
    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self,*args):pass
        def translate_path(self,path):
            if path.split('?')[0] in ['/app.js','/handoff-verify.js','/style.css','/index.html','/']:
                return str(ROOT/'web'/('index.html' if path=='/' else path.split('?')[0].lstrip('/')))
            return super().translate_path(path)
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(ROOT/'dist')))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True);page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            origin='http://127.0.0.1:'+str(server.server_port)
            for example in ['keep-handoff','everyday-handoff']:
                folder=ROOT/'docs/examples'/example/'export';files={f.name:f.read_bytes() for f in folder.iterdir()}
                def route(r):
                    name=r.request.url.rsplit('/',1)[-1];r.fulfill(body=files[name],content_type='application/json')
                page.route('**/handoff/*',route);page.goto(origin)
                expect(page.locator('#handoff-overview')).to_contain_text('Content matches the selected manifest')
                for failure in ['changed-bytes','current-association','missing-history','duplicate-key']:
                    baseline={f.name:f.read_bytes() for f in folder.iterdir()};files.clear();files.update(baseline)
                    if failure=='changed-bytes':files['handoff.json']+=b' '
                    if failure=='current-association':
                        handoff=json.loads(files['handoff.json']);handoff['material']['goal']='Changed outside retained material';files['handoff.json']=json.dumps(handoff).encode()
                        manifest=json.loads(files['manifest.json']);manifest['files']['handoff.json']={'bytes':len(files['handoff.json']),'sha256':digest(files['handoff.json'])};files['manifest.json']=json.dumps(manifest).encode()
                    if failure=='missing-history':files['artifacts.json']=b'{}'
                    if failure=='duplicate-key':files['manifest.json']=b'{"files":{},"files":{}}'
                    page.reload();expect(page.get_by_role('alert')).to_contain_text('could not be verified');expect(page.locator('#handoff-overview')).to_have_count(0)
                page.unroute('**/handoff/*')
            result=page.evaluate('''async()=>{const {strictJSON}=await import('./handoff-verify.js');return ['{"x":1,"x":2}','9007199254740993','1.0'].map(s=>{try{strictJSON(s);return false}catch{return true}})}''')
            assert all(result);assert not errors;browser.close()
    finally:server.shutdown();server.server_close();thread.join()
