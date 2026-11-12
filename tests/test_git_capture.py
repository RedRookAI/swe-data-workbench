import os,sys,tempfile,unittest
from pathlib import Path
from swe_workbench.git_capture import capture,DIAGNOSTIC_BYTES,READ_BYTES
from swe_workbench.errors import WorkbenchError

class GitCaptureTests(unittest.TestCase):
    def test_exact_boundary_and_refusals(self):
        metrics={};code,out,err=capture([sys.executable,'-c','import os;os.write(1,b"a"*32768);os.write(2,b"b"*32768)'],os.environ,stdout_limit=32768,metrics=metrics)
        self.assertEqual((code,len(out),len(err)),(0,32768,32768));self.assertLessEqual(metrics['max_read'],READ_BYTES)
        for script,limit,stream in [('import os;os.write(1,b"x"*32769)',32768,'stdout'),('import os;os.write(2,b"x"*65537)',32768,'stderr')]:
            with self.subTest(stream=stream),self.assertRaisesRegex(WorkbenchError,'Git '+stream):capture([sys.executable,'-c',script],os.environ,stdout_limit=limit)
    def test_concurrent_pipes_and_failure(self):
        script='import os,threading; t=threading.Thread(target=lambda:os.write(2,b"e"*65536));t.start();os.write(1,b"x"*65536);t.join();raise SystemExit(23)'
        m={};code,out,err=capture([sys.executable,'-c',script],os.environ,stdout_limit=65536,metrics=m)
        self.assertEqual(code,23);self.assertEqual(len(out),65536);self.assertEqual(len(err),65536);self.assertLessEqual(m['stdout'],65536)
    def test_owned_child_reaped_on_overrun(self):
        with tempfile.TemporaryDirectory() as t:
            pid=Path(t)/'pid';script='import os,time;open('+repr(str(pid))+',"w").write(str(os.getpid()));os.write(1,b"x"*10000);time.sleep(60)'
            with self.assertRaises(WorkbenchError):capture([sys.executable,'-c',script],os.environ,stdout_limit=10)
            with self.assertRaises(ProcessLookupError):os.kill(int(pid.read_text()),0)
