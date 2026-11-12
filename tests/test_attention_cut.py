import unittest,json,time
from unittest.mock import patch
from pathlib import Path
from tests.test_daily_workflow import DailyTests
from swe_workbench import project_context as project,handoff
from swe_workbench.attention import list_changes,detail
from swe_workbench.store import Store

class CutTests(unittest.TestCase):
    setUp=DailyTests.setUp;git=DailyTests.git;write_proof=DailyTests.write_proof;context=DailyTests.context
    def test_one_cut_matches_individual_reads_and_releases_lock(self):
        c=self.context()
        for i in range(10):project.collect(c,change_id='change-'+str(i),title='Owned fixture',goal='Use2')
        expected=[detail(self.root,'change-'+str(i)) for i in range(10)];calls=[];original=Store.events;start=time.monotonic()
        def counted(*a,**kw):calls.append(1);return original(*a,**kw)
        import swe_workbench.attention as attention
        projection=attention.project_record
        def unlocked(*args):
            with Store(self.root).transaction() as con:con.execute("UPDATE meta SET value=value WHERE key='project-association/v1'")
            return projection(*args)
        with patch.object(Store,'events',staticmethod(counted)),patch.object(attention,'project_record',unlocked):rows=list_changes(c)['changes']
        elapsed=time.monotonic()-start;self.assertEqual(rows,expected);self.assertEqual(len(calls),1)
        # New operation observes new committed source evidence; no persistent validation cache.
        self.data['check']=True;self.write_proof();project.collect(c,change_id='change-0',title='Owned fixture',goal='Use2');self.assertGreater(list_changes(c)['changes'][0]['revision'],rows[0]['revision'])
        target=Path('coordination/review-corrections')
        if target.is_dir():(target/'read-after.json').write_text(json.dumps({'changes':10,'full_event_loads':len(calls),'elapsed_seconds':elapsed,'writer_lock_released_before_projection':True,'scope':'One owned10-change fixture; not a production latency benchmark.'},indent=2)+'\n')
del DailyTests
