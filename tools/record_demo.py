#!/usr/bin/env python3
"""Record one real owner UI journey. Inputs and all adjudications are scripted fixtures."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.request

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
from swe_workbench.core import Workbench,CRITERIA
from swe_workbench.exporter import export_batch,verify_export

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=REPO/".state/recorded-demo")
    parser.add_argument("--output",type=Path,default=REPO/"recordings")
    args=parser.parse_args();root=args.root.resolve();out=args.output.resolve()
    if (root/"state.sqlite").exists() or (root/"workbench.sqlite").exists():
        parser.error("Use a fresh owned root for a new recording; existing run evidence is preserved.")
    root.mkdir(parents=True,exist_ok=True);out.mkdir(parents=True,exist_ok=True)
    token=secrets.token_urlsafe(40)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
    origin="http://127.0.0.1:"+str(port)
    env=os.environ.copy();env["SWE_WORKBENCH_OWNER_TOKEN"]=token
    serverlog=(out/"server.log").open("wb")
    server=subprocess.Popen([sys.executable,"-m","swe_workbench.server","--root",str(root),"--port",str(port)],cwd=REPO,env=env,stdout=serverlog,stderr=subprocess.STDOUT)
    def api(path,body=None):
        headers={"Authorization":"Bearer "+token,"Origin":origin}
        if body is not None:headers["Content-Type"]="application/json"
        request=urllib.request.Request(origin+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        with urllib.request.urlopen(request,timeout=20) as response:return json.load(response)
    video=None;browser=None;events=[];started=None
    def mark(text):
        events.append({"seconds":round(time.monotonic()-started,3),"caption":text})
    try:
        for _ in range(100):
            if server.poll() is not None:raise RuntimeError("Owned server failed to start; inspect recording server log.")
            try:
                with urllib.request.urlopen(origin+"/api/health",timeout=1) as response:
                    if json.load(response).get("ok"):break
            except OSError:time.sleep(.1)
        else:raise RuntimeError("Owned server readiness timed out.")
        from playwright.sync_api import sync_playwright
        if (REPO/".browsers").exists():os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",str(REPO/".browsers"))
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            context=browser.new_context(viewport={"width":1440,"height":1000},record_video_dir=str(out/"raw"),record_video_size={"width":1440,"height":1000})
            page=context.new_page();page.set_default_timeout(10000)
            errors=[];page.on("pageerror",lambda error:errors.append(str(error)))
            started=time.monotonic();mark("Synthetic inputs. Real application, patches and executable checks. No model calls.")
            page.goto(origin+"/?mode=live")
            page.get_by_label("Owner token",exact=True).fill(token)
            page.get_by_role("button",name="Connect",exact=True).click()
            page.get_by_role("button",name="Import trusted sample").wait_for(state="visible")
            page.wait_for_timeout(1600)
            mark("Import eight authored records: six unique submissions, one duplicate and one invalid line.")
            page.get_by_role("button",name="Import trusted sample").click()
            page.locator("#item-list button").nth(5).wait_for()
            page.wait_for_timeout(2200)
            batches=api("/api/batches");batch_id=batches[0]["id"]
            mark("A real controller stops after one committed result. Existing work remains durable.")
            command=[sys.executable,"-m","swe_workbench.cli","--root",str(root),"process",batch_id,"--workers","1","--stop-after","1"]
            stopped=subprocess.run(command,cwd=REPO,capture_output=True,text=True,check=True)
            stop=json.loads(stopped.stdout);assert stop["interrupted"] and stop["processed"]==1
            before={i["id"]:i["result"]["evidence_digest"] for i in api("/api/batches/"+batch_id+"/submissions") if i.get("result")}
            page.get_by_role("button",name="Refresh",exact=True).click();page.wait_for_timeout(1800)
            mark("Resume through the owner UI. Completed evidence is retained; only unfinished work executes.")
            page.get_by_role("button",name="Run checks · 1 worker",exact=True).click()
            page.wait_for_function("document.querySelector('#process').textContent === 'Run checks · 1 worker' && !document.querySelector('#process').disabled")
            items=api("/api/batches/"+batch_id+"/submissions")
            assert len([i for i in items if i["execution_status"]=="completed"])==4
            assert all(next(i for i in items if i["id"]==key)["result"]["evidence_digest"]==value for key,value in before.items())
            page.wait_for_timeout(2200)
            def select(label):
                current=api("/api/batches/"+batch_id+"/submissions")
                index=next(n for n,item in enumerate(current) if item.get("fixture_label")==label)
                page.locator("#filter").select_option("all")
                page.locator("#item-list button").nth(index).click()
                page.locator("#inspector h2").wait_for()
                return current[index]
            wrong=select("weak-check-wrong");assert wrong["result"]["overall"]=="passed"
            mark("The sorting patch passes weak visible checks. It violates the required first-seen order.")
            page.get_by_role("tab",name="Task & patch",exact=True).click()
            page.locator("#inspector").scroll_into_view_if_needed();page.wait_for_timeout(3000)
            page.get_by_role("tab",name="Machine evidence",exact=True).click();page.wait_for_timeout(3000)
            mark("Scripted developer adjudication through real controls rejects the semantic defect.")
            def decide(label,decision,reason,failures=()):
                item=select(label)
                page.get_by_role("tab",name="Adjudication",exact=True).click()
                for criterion in CRITERIA:
                    page.locator("#criterion-"+criterion).select_option("fail" if criterion in failures else "pass")
                page.locator("#decision").select_option(decision)
                page.get_by_label("Reason and evidence",exact=True).fill(reason)
                page.get_by_role("button",name="Save exact-version adjudication",exact=True).click()
                page.get_by_text("Developer adjudication saved",exact=False).wait_for()
                updated=api("/api/submissions/"+item["id"])
                assert updated["disposition"]==decision
            decide("weak-check-wrong","rejected",'Scripted fixture adjudication: ["b","a","b"] must become ["b","a"]. sorted(set(items)) returns ["a","b"], despite passing the ascending-input checks.',("requested_behavior","preserved_behavior","evidence_adequacy"))
            page.wait_for_timeout(2000)
            mark("The order-preserving fix is accepted against its exact check evidence and rubric.")
            decide("good","accepted","Scripted fixture adjudication: dict.fromkeys preserves first-seen order and the recorded checks pass.")
            page.wait_for_timeout(2000)
            mark("Separate task contexts stay distinct. A failing candidate is rejected; missing evidence remains pending.")
            decide("same-patch-different-context","accepted","Scripted fixture adjudication: this separate Unicode task context uses the order-preserving fix with its own recorded evidence.")
            decide("failing","rejected","Scripted fixture adjudication: the actual candidate check fails because the patch drops distinct values.",("requested_behavior","preserved_behavior"))
            page.wait_for_timeout(2000)
            mark("Freeze accepted data with a content-bound manifest and traceable evidence.")
            page.locator("#export-section").scroll_into_view_if_needed()
            page.get_by_role("button",name="Freeze accepted export",exact=True).click()
            page.locator("#export-receipt").wait_for(state="visible");page.wait_for_timeout(2600)
            w=Workbench(root);w.initialize()
            exported=export_batch(w,batch_id,root/"exports","recording-public-export-v1")
            repeated=export_batch(w,batch_id,root/"exports","recording-public-export-repeat-v1")
            assert exported["manifest_digest"]==repeated["manifest_digest"]
            verification=verify_export(exported["path"]);assert verification["ok"] and verification["accepted_count"]==2
            summary=w.batch(batch_id);assert summary["counts"]["rejected"]==2 and summary["counts"]["pending-evidence"]==2
            mark("Final recorded batch: two accepted, two rejected, two pending. Synthetic outcomes are not model accuracy.")
            page.locator("#main").scroll_into_view_if_needed();page.wait_for_timeout(2400)
            page.screenshot(path=str(out/"workbench.png"),full_page=True)
            final=api("/api/batches/"+batch_id+"/submissions")
            assert all(i["result"]["source_unchanged"] for i in final if i.get("result"))
            assert not errors,errors
            video=page.video;page.close();context.close()
            raw=Path(video.path());browser.close();browser=None
            receipt={"schema":"swe-workbench-browser-recording/v1","recorded_at":__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),"source_commit":subprocess.check_output(["git","rev-parse","HEAD"],cwd=REPO,text=True).strip(),"fixture_origin":"synthetic authored fixtures","decision_origin":"scripted developer adjudication through actual browser controls","model_calls":0,"keep_dependency":False,"viewport":{"width":1440,"height":1000},"cooperative_stop":stop,"preserved_completed_evidence":before,"batch":summary,"export_id":exported["export_id"],"export_path":str(exported["path"]),"manifest_digest":exported["manifest_digest"],"verification":verification,"browser_errors":errors,"raw_video":str(raw),"raw_video_sha256":hashlib.sha256(raw.read_bytes()).hexdigest(),"events":events,"duration_seconds":round(time.monotonic()-started,3),"integrity":w.verify()}
            (out/"receipt.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
            def stamp(seconds):
                n=round(seconds*1000);return f"{n//3600000:02}:{n//60000%60:02}:{n//1000%60:02},{n%1000:03}"
            srt=[]
            for n,event in enumerate(events):
                end=events[n+1]["seconds"] if n+1<len(events) else receipt["duration_seconds"]
                srt.append(str(n+1)+"\n"+stamp(event["seconds"])+" --> "+stamp(end)+"\n"+event["caption"]+"\n")
            (out/"captions.srt").write_text("\n".join(srt))
            print(json.dumps({"recording_receipt":str(out/"receipt.json"),"raw_video":str(raw),"export_path":str(exported["path"]),"accepted":2,"rejected":2,"pending":2,"browser_errors":0}))
    finally:
        if browser:browser.close()
        server.terminate()
        try:server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill();server.wait()
        serverlog.close()

if __name__=="__main__":
    main()

