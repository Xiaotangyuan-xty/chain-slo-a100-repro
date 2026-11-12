import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch

from frozen_v47 import chain_admission as admission
from frozen_v47 import native_chain as nc
from vllm.sequence import SequenceStatus

CASE = Path(__file__).resolve().parents[2]
ABLATION = json.loads((CASE / 'CASE_SPEC.json').read_text())['ablation']


def make_policy(cid='c1', deadline=100.):
    policy = nc.ChainCompletionPolicy()
    policy.chains[cid] = {
        'stages': 4, 'widths': [1, 1, 1, 1], 'deadline': deadline,
        'observed': {}, 'neighbor_cache': {}, 'finished': False,
        'aborted': False, 'deadline_version': 0,
    }
    policy._get_interval_time = lambda: 0.1
    return policy


def fake_group(cid='c1', deadline=100., request_id='r1', max_tokens=50, generated=10, prefill=40):
    info = SimpleNamespace(stage_id=0, input_len=100, request_id=request_id,
                           chain_deadline=deadline, chain_stage_count=4,
                           chain_stage_widths=[1, 1, 1, 1],
                           chain_reward_input_tokens=100)
    seq = SimpleNamespace(status=SequenceStatus.RUNNING,
                          get_prompt_len=lambda: 100,
                          get_output_len=lambda: generated)
    return SimpleNamespace(collection_id=cid, request_info=info, first_seq=seq,
                           arrival_time=0., request_id=request_id,
                           sampling_params=SimpleNamespace(max_tokens=max_tokens),
                           get_num_uncomputed_tokens=lambda: prefill,
                           is_prefill=lambda: prefill > 0)


class AblationTests(TestCase):
    def test_no_credit_uses_only_current_stage_and_never_calls_forecast(self):
        if ABLATION != 'no_credit':
            self.skipTest('not no_credit')
        policy = make_policy()
        group = fake_group()
        policy.chains['c1']['observed'] = {1: {'old': {
            'declared_input': 999999, 'output': 999999,
            'reward_input': 999999, 'reward_output': 999999}}}
        with patch.object(nc.MODEL, 'estimate', side_effect=AssertionError('whole-chain forecast called')):
            goals = policy.goals([group], 0.)
        goal = goals[0]
        work = 40 + 40 / nc.MODEL.prefill_unit
        self.assertAlmostEqual(goal['remaining_work'], work)
        self.assertAlmostEqual(goal['critical_mean_seconds'], work * 0.1)
        self.assertEqual(goal['expected_credited_tokens'], 500)
        self.assertEqual(goal['donors'], 0)
        self.assertAlmostEqual(goal['score'], 500 / work * 1.2)
        self.assertEqual(goal['probability'], 1.)
        self.assertEqual(goal['current_remaining_tokens'], 40)

    def test_no_kv_removes_capacity_and_both_residency_holds(self):
        if ABLATION != 'no_KV':
            self.skipTest('not no_KV')
        schedule = inspect.getsource(nc.NativeChainScheduler._schedule)
        drain = inspect.getsource(nc.NativeChainScheduler._expired_drain)
        self.assertIn("capacity=float('inf')", schedule)
        self.assertIn("capacity=float('inf')", drain)
        self.assertIn('protected=set()', schedule)
        self.assertNotIn('selected.add(g.request_id);holds.append', schedule)
        self.assertIn('estimate=MODEL.estimate', inspect.getsource(nc.ChainCompletionPolicy.goals))
        goals = [{'chain': 'c1', 'stage': 0, 'deadline': 100., 'probability': 1.,
                  'remaining_work': 1., 'critical_mean_seconds': 1., 'score': 1., 'arrival': 0.,
                  'members': [{'request': 'r1', 'prompt': 100, 'generated': 10,
                               'max_tokens': 50, 'arrival': 0.}]}]
        selected, _ = admission.select(goals, float('inf'), 1, 16, protected=set())
        self.assertEqual(selected, {'r1'})

    def test_no_event_restores_periodic_replan_only(self):
        if ABLATION != 'no_event':
            self.skipTest('not no_event')
        schedule = inspect.getsource(nc.NativeChainScheduler._schedule)
        self.assertNotIn('or sibling or arrival', schedule)
        self.assertIn('tick-self.last_plan>=50', schedule)
        self.assertIn('not self.last_members and bool(live)', schedule)
        self.assertIn('protected={g.request_id', schedule)
        self.assertIn('estimate=MODEL.estimate', inspect.getsource(nc.ChainCompletionPolicy.goals))

    def test_chain_edf_orders_only_by_deadline_without_forecast_or_protection(self):
        if ABLATION != 'chain_EDF':
            self.skipTest('not chain_EDF')
        policy = make_policy(cid='late', deadline=200.)
        early_group = fake_group(cid='early', deadline=100., request_id='early')
        late_group = fake_group(cid='late', deadline=200., request_id='late')
        policy.chains['early'] = {
            'stages': 4, 'widths': [1, 1, 1, 1], 'deadline': 100.,
            'observed': {}, 'neighbor_cache': {}, 'finished': False,
            'aborted': False, 'deadline_version': 0,
        }
        with patch.object(nc.MODEL, 'estimate', side_effect=AssertionError('forecast called')):
            goals = policy.goals([late_group, early_group], 0.)
        self.assertEqual({g['score'] for g in goals}, {0.})
        selected, _ = admission.select(goals, float('inf'), 1, 16, protected=set())
        self.assertEqual(selected, {'early'})
        schedule = inspect.getsource(nc.NativeChainScheduler._schedule)
        self.assertIn('protected=set()', schedule)
        self.assertNotIn('selected.add(g.request_id);holds.append', schedule)
        self.assertIn('capacity=self.block_manager.num_total_gpu_blocks-self.block_manager.watermark_blocks', schedule)


class RealSchedulerBehavior(TestCase):
    def setUp(self):
        self.wall=patch('time.time',return_value=100.);self.clock=patch('time.perf_counter',return_value=1000.)
        self.wall.start();self.clock.start();self.addCleanup(self.wall.stop);self.addCleanup(self.clock.stop)

    def scheduler(self,blocks=128,slots=4):
        from vllm.config import CacheConfig,SchedulerConfig
        sc=SchedulerConfig('generate',64,slots,512,enable_chunked_prefill=True,policy='jitserve',top_k_selection=3,max_swaps_per_iter=3)
        cache=CacheConfig(16,.9,1,'auto');cache.num_gpu_blocks=blocks;cache.num_cpu_blocks=128
        s=nc.NativeChainScheduler(sc,cache,None)
        self.addCleanup(self.cleanup,s)
        return s

    def cleanup(self,s):
        s.abort_seq_group([g.request_id for q in [s.running,s.waiting,s.swapped]for g in q])
        self.assertEqual(s.block_manager.get_num_free_gpu_blocks(),s.block_manager.num_total_gpu_blocks)
        self.assertEqual(s.block_manager.get_num_free_cpu_blocks(),128)

    def group(self,rid,*,cid=None,stage=0,widths=None,prompt=32,deadline=2000.):
        from jitserve.request_info import RequestInfo,RequestType
        from vllm.sequence import Sequence,SequenceGroup
        from vllm import SamplingParams
        widths=widths or [1];cid=rid if cid is None else cid
        info=RequestInfo(RequestType.COLLECTIVE,(2.,.1,20.),0,cid,20,prompt,100,stage_id=stage,request_id=0)
        info.chain_deadline=deadline;info.chain_stage_count=len(widths);info.chain_stage_widths=widths
        seq=Sequence(rid,inputs={'prompt_token_ids':list(range(prompt)),'prompt':'CPU'},block_size=16)
        return SequenceGroup(str(rid),[seq],100.,info,SamplingParams(temperature=0,max_tokens=100,ignore_eos=True))

    def step(self,s):
        from vllm.sequence import Logprob
        _,out,_=s.schedule()
        for item in out.scheduled_seq_groups:
            g=item.seq_group;g.update_num_computed_tokens(item.token_chunk_size)
            if not g.is_prefill():g.first_seq.append_token_id(1,{1:Logprob(0.)})
        return out

    def test_actual_new_root_trigger_and_fifty_tick_fallback(self):
        s=self.scheduler();s.add_seq_group(self.group(1));self.step(s);before=s.last_plan
        s.add_seq_group(self.group(2));self.step(s)
        if ABLATION=='no_event':
            self.assertEqual(s.last_plan,before)
            for _ in range(50):self.step(s)
            self.assertGreaterEqual(s.last_plan-before,50)
            self.assertIn('2',s.selected)
        else:self.assertGreater(s.last_plan,before)

    def test_actual_stage_arrival_while_other_selected_survives(self):
        s=self.scheduler();a=self.group(1,cid=1,widths=[1,1]);s.add_seq_group(a)
        s.add_seq_group(self.group(2));self.step(s);before=s.last_plan
        a.first_seq.status=SequenceStatus.FINISHED_LENGTH_CAPPED;s.free_finished_seq_groups()
        s.add_seq_group(self.group(3,cid=1,stage=1,widths=[1,1]));self.step(s)
        if ABLATION=='no_event':self.assertEqual(s.last_plan,before)
        else:self.assertGreater(s.last_plan,before)

    def test_actual_admission_capacity_and_protection_arguments(self):
        s=self.scheduler();s.add_seq_group(self.group(1))
        with patch.object(nc,'select',wraps=admission.select)as called:self.step(s)
        self.assertEqual(called.call_count,1)
        args=called.call_args.args
        self.assertEqual(args[1],float('inf')if ABLATION=='no_KV'else s.block_manager.num_total_gpu_blocks-s.block_manager.watermark_blocks)
        if ABLATION in ['no_KV','chain_EDF']:self.assertEqual(set(args[4]),set())

    def test_actual_unselected_resident_is_held_only_in_declared_variants(self):
        s=self.scheduler();s.add_seq_group(self.group(1));self.step(s)
        s.add_seq_group(self.group(2));s.selected={'2'};s.last_members={'1','2'}
        s.last_plan=s.policy.num_schedule_count;s.policy.draining=False
        s._schedule()
        self.assertEqual('1'in s.last_recorded_selected,ABLATION not in ['no_KV','chain_EDF'])

    def test_actual_expired_drain_capacity_switch_and_physical_caps_preserved(self):
        s=self.scheduler()
        for i in range(8):s.add_seq_group(self.group(i+1,prompt=480,deadline=900.))
        original=s.block_manager.num_total_gpu_blocks
        with patch.object(s,'_schedule_chunked_prefill',return_value=SimpleNamespace()):s._schedule()
        self.assertEqual(s.scheduler_config.max_num_seqs,8 if ABLATION=='no_KV'else 4)
        self.assertEqual(s.block_manager.num_total_gpu_blocks,original)


if __name__ == '__main__':
    main(verbosity=2)

