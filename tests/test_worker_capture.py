"""Bounded pipe capture checks; no RSS benchmark or untrusted bundle execution."""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from swe_workbench import worker


class WorkerCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.children = []
        original = subprocess.Popen
        def tracked(*args, **kwargs):
            child = original(*args, **kwargs)
            self.children.append(child)
            return child
        self.popen_patch = patch.object(worker.subprocess, 'Popen', side_effect=tracked)
        self.popen_patch.start()
        self.addCleanup(self.popen_patch.stop)

    def invoke(self, script, timeout=3):
        result = worker._invoke('capture-test', ['{python}', '-c', script], self.root, timeout, self.root)
        self.assertTrue(self.children[-1].stdout.closed)
        self.assertTrue(self.children[-1].stderr.closed)
        self.assertIsNotNone(self.children[-1].poll())
        with self.assertRaises(ChildProcessError):
            os.waitpid(self.children[-1].pid, os.WNOHANG)
        return result

    def test_high_output_both_streams_stay_bounded_and_preserve_actual_failure(self):
        observations = []
        original = worker._StreamCapture
        class Instrumented(original):
            def __init__(self):
                super().__init__()
                self.seen = self.maximum_retained = self.maximum_chunk = 0
                observations.append(self)
            def append(self, data):
                self.seen += len(data)
                self.maximum_chunk = max(self.maximum_chunk, len(data))
                super().append(data)
                self.maximum_retained = max(self.maximum_retained, len(self.prefix))
        with patch.object(worker, '_StreamCapture', Instrumented):
            result = self.invoke("import os;\nfor _ in range(128):\n os.write(1,b'A'*16384); os.write(2,b'B'*16384)\nraise SystemExit(23)")
        self.assertEqual(result['exit_code'], 23)
        self.assertEqual(result['outcome'], 'failed')
        self.assertEqual(result['stdout'], 'A' * worker.OUTPUT_LIMIT)
        self.assertEqual(result['stderr'], 'B' * worker.OUTPUT_LIMIT)
        self.assertTrue(result['output_truncated'])
        self.assertEqual([value.seen for value in observations], [2097152, 2097152])
        for value in observations:
            self.assertEqual(value.maximum_retained, worker.OUTPUT_LIMIT)
            self.assertLessEqual(value.maximum_chunk, worker.READ_CHUNK)

    def test_empty_exact_cap_and_cap_plus_one_do_not_change_success(self):
        for count in (0, worker.OUTPUT_LIMIT, worker.OUTPUT_LIMIT + 1):
            with self.subTest(count=count):
                result = self.invoke(f"import os;os.write(1,b'A'*{count});os.write(2,b'B'*{count})")
                self.assertEqual(result['exit_code'], 0)
                self.assertEqual(result['outcome'], 'passed')
                self.assertEqual(len(result['stdout']), min(count, worker.OUTPUT_LIMIT))
                self.assertEqual(len(result['stderr']), min(count, worker.OUTPUT_LIMIT))
                self.assertEqual(result['output_truncated'], count > worker.OUTPUT_LIMIT)

    def test_utf8_across_reads_invalid_bytes_and_attempt_redaction(self):
        result = self.invoke("import os,time;os.write(1,b'x'*16383+b'\\xe2');time.sleep(.01);os.write(1,b'\\x82\\xac\\xff');os.write(2,os.getcwd().encode())")
        self.assertEqual(result['stdout'], 'x' * 16383 + '\u20ac\ufffd')
        self.assertEqual(result['stderr'], '<attempt>')
        self.assertFalse(result['output_truncated'])
        capped = self.invoke("import os;os.write(1,b'x'*65535+b'\\xe2\\x82\\xac')")
        self.assertEqual(capped['stdout'], 'x' * 65535 + '\ufffd')
        self.assertTrue(capped['output_truncated'])

    def test_continuous_both_streams_respect_deadline_and_reap_direct_child(self):
        started = time.monotonic()
        result = self.invoke("import os;\nwhile True:\n os.write(1,b'A'*4096);os.write(2,b'B'*4096)", timeout=.15)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(result['outcome'], 'timeout')
        self.assertLess(result['exit_code'], 0)
        self.assertTrue(result['output_truncated'])
        self.assertEqual(len(result['stdout']), worker.OUTPUT_LIMIT)
        self.assertEqual(len(result['stderr']), worker.OUTPUT_LIMIT)

    def test_closed_pipes_do_not_bypass_command_deadline(self):
        result = self.invoke("import os,time;os.close(1);os.close(2);time.sleep(10)", timeout=.1)
        self.assertEqual(result['outcome'], 'timeout')
        self.assertEqual(result['stdout'], '')
        self.assertEqual(result['stderr'], '')
        self.assertFalse(result['output_truncated'])

    def test_held_pipe_writers_cannot_extend_deadline_after_direct_exit(self):
        # Explicit FD double: models inherited writers after the direct child
        # exited, without launching a descendant or signaling any group.
        readers, writers = [], []
        for _ in range(2):
            read_fd, write_fd = os.pipe()
            readers.append(os.fdopen(read_fd, 'rb'))
            writers.append(write_fd)
        class ExitedChild:
            stdout, stderr = readers
            returncode = 0
            def poll(self): return 0
            def wait(self, timeout=None): return 0
            def kill(self): raise AssertionError('Already-exited direct child must not be signaled')
        try:
            started = time.monotonic()
            _, timed_out = worker._bounded_capture(ExitedChild(), started + .05)
            self.assertTrue(timed_out)
            self.assertLess(time.monotonic() - started, 1)
            self.assertTrue(all(stream.closed for stream in readers))
        finally:
            for write_fd in writers:
                os.close(write_fd)
