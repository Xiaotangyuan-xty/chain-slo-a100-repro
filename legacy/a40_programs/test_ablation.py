import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, main
from unittest.mock import patch

from frozen_v47 import chain_admission as admission
from frozen_v47 import native_chain as nc
from vllm.sequence import SequenceStatus

CASE = Path(__file__).resolve().parents[1]
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
        self.assertIn('estimate=MODEL.estimate', schedule)
        goals = [{'chain': 'c1', 'stage': 0, 'deadline': 100., 'probability': 1.,
                  'remaining_work': 1., 'critical_mean_seconds': 1., 'score': 1.,
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
        self.assertIn('estimate=MODEL.estimate', schedule)

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


if __name__ == '__main__':
    main()
