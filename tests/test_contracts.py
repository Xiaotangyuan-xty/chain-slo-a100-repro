import asyncio
import gzip
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from chainbench.core import ROOT,matrix,workload,offsets,kv_blocks,classify_window,assess_profile

class DesignTests(unittest.TestCase):
    def test_matrix_counts_and_actual_windows(self):
        rows=matrix();self.assertEqual(len(rows),134)
        self.assertEqual(len({r['id']for r in rows}),134)
        self.assertTrue(all(r['no_drain']and r['full_replay_metrics']is None for r in rows))
        self.assertAlmostEqual(sum(r['window_seconds']for r in rows)/3600,30.925925925925927)
        self.assertEqual({r['window_seconds']for r in rows if r['suite']==5},{3600})

    def test_relative_capacity_uses_each_measured_integer_B(self):
        self.assertEqual(kv_blocks(101, .2),20)
        self.assertEqual(kv_blocks(207, .2),41)
        self.assertEqual(kv_blocks(1,.2),1)
        for value in [0,-1,2.5,True]:
            with self.assertRaises(ValueError):kv_blocks(value,.2)

    def test_arrivals_shared_across_methods_and_models(self):
        cases=[r for r in matrix()if r['suite']==1 and r['rate_chains_s']==.4]
        arrays=[offsets(c)for c in cases]
        self.assertTrue(all(a==arrays[0]for a in arrays))
        self.assertTrue(all(0<=t<500 for t in arrays[0]))
        azure=next(c for c in matrix()if c['arrival']=='azure')
        self.assertEqual(len(offsets(azure)),200)
        self.assertNotEqual(offsets(azure),offsets({**azure,'arrival':'poisson'}))

    def test_slo_sensitivity_changes_only_completion_slot(self):
        a=next(r for r in matrix()if r['suite']==6 and r['slo_factor']==1)
        b={**a,'slo_factor':.5}
        base=workload(a);scaled=workload(b)
        targets=0;slo=[]
        for x,y in zip(base['main'],scaled['main']):
            self.assertEqual(x['stages'],y['stages'])
            self.assertEqual(x['received_slo'][:2],y['received_slo'][:2])
            self.assertEqual(x['received_slo'][2]/2,y['received_slo'][2])
            self.assertEqual(x['collection_id'],y['collection_id'])
            targets+=sum(z['target_output_tokens']for s in x['stages']for z in s)
            slo.append(x['received_slo'][2]*len(x['stages']))
        self.assertEqual(targets,504695);self.assertEqual((min(slo),max(slo)),(80,480))

    def test_hour_stream_is_continuous_and_unique_with_slo_class_preserved(self):
        case=next(r for r in matrix()if r['suite']==5);data=workload(case);rows=data['main']
        self.assertEqual(len(rows),720);self.assertEqual(len({r['collection_id']for r in rows}),720)
        self.assertTrue(all(r['collection_id']%4==r['template_collection_id']%4 for r in rows))
        self.assertTrue(all(x<y for x,y in zip(offsets(case),offsets(case)[1:])))

    def test_unvalidated_profile_cannot_pass(self):
        result=assess_profile(matrix()[0],{'model':'llama8','method':'v47pro3','dtype':'bfloat16'})
        self.assertEqual(result['gate'],'BLOCKED')

    def test_window_censoring_does_not_credit_late_completion(self):
        self.assertEqual(classify_window(1,80,81,100),'DEFINITE_MISS')
        self.assertEqual(classify_window(1,120,101,100),'RIGHT_CENSORED')
        self.assertEqual(classify_window(1,80,None,100),'DEFINITE_MISS')
        self.assertEqual(classify_window(1,120,99,100),'ATTAINED')
        self.assertEqual(classify_window(100,120,None,100),'NOT_ARRIVED')

class RealWindowBarrierTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_wrapper_blocks_new_executor_and_discards_late_output(self):
        path=ROOT/'legacy/stage87_cutoff_cleanupfix/cutoff_observation.py'
        spec=importlib.util.spec_from_file_location('frozen_window',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory()as directory:
            now=[99.];window=module.Window(directory,100,clock=lambda:now[0])
            window.origin=0.;window.deadline=100.;called=[]
            async def executor():called.append(True);return 'executed'
            guarded=window.guard(executor)
            self.assertEqual(await guarded(),'executed')
            now[0]=100.
            task=asyncio.create_task(guarded());await asyncio.sleep(0)
            self.assertFalse(task.done());self.assertEqual(len(called),1)
            self.assertTrue(window.closed);self.assertEqual(window.blocked,1)
            self.assertFalse(window.record_output({'phase':'main'},None))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
            receipt=json.loads((Path(directory)/'WINDOW_SERVER_CUTOFF.json').read_text())
            self.assertTrue(receipt['no_drain']);window.finish()

class OracleVisibilityTests(unittest.TestCase):
    def test_repaired_oracle_rejects_future_root_and_forbidden_information(self):
        path=ROOT/'legacy/oracle_order2/common_runtime/oracle_length_adapter.py'
        spec=importlib.util.spec_from_file_location('corrected_oracle',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        truth=module.LengthTruth({'schema':'length-only-oracle/v1','roots':{'main:1':[[7],[11,13]]}})
        with self.assertRaises(PermissionError):truth.target('main:1',1,0)
        truth.activate('main:1');self.assertEqual(truth.target('main:1',1,0),11)
        with self.assertRaises(ValueError):
            module.LengthTruth({'schema':'length-only-oracle/v1','roots':{},'future_arrivals':[1.]})

if __name__=='__main__':unittest.main()
