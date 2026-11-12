from pathlib import Path
from types import SimpleNamespace as NS
import copy
import hashlib
import sys
import unittest
from jitserve_mixed_goodput import compute

ROOT = Path(sys.argv[1])
sys.argv = sys.argv[:1]

class Tokenizer:
    def __call__(self, text, add_special_tokens=False):
        assert not add_special_tokens
        return NS(input_ids=text.split())

def fixture():
    jobs, calls = [], []
    for cid, kind, depth in [(0, 0, 1), (4, 1, 1), (8, 2, 2)]:
        job = {'collection_id': cid, 'request_type': kind, 'received_slo': [1., .1, 10.], 'stages': []}
        call = {**job, 'phase': 'main', 'success': True, 'client_chain_start_monotonic': 0.,
                'client_chain_end_monotonic': 15. if kind == 2 else 9., 'stages': []}
        for sid in range(depth):
            prompt = 'one two' if kind == 0 or sid == 0 else 'three'
            output = 'x y z' if kind == 0 else 'x y'
            job['stages'].append([{'request_id': 0, 'prompt': prompt}])
            request = {'request_id': 0, 'success': True, 'generated_text': output,
                       'input_prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
                       'client_request_start_monotonic': 0., 'client_request_end_monotonic': 9.,
                       'server_ttft': 1., 'server_tbt': [.1, .3] if kind == 0 else [.1]}
            call['stages'].append({'stage_id': sid, 'requests': [request]})
        jobs.append(job);calls.append(call)
    return {'main': jobs}, calls

class NativeMetric(unittest.TestCase):
    def test_all_three_classes_and_partial_latency_credit(self):
        w, c = fixture();r = compute(ROOT, w, c, 100., Tokenizer())
        self.assertEqual(r['credited_weighted_tokens_by_class'], [10, 18, 35])
        self.assertEqual(r['credited_weighted_tokens'], 63)
        self.assertEqual(r['compound_attained'], 1)

    def test_whole_chain_miss_zeros_every_chain_call(self):
        w, c = fixture();c[-1]['client_chain_end_monotonic'] = 21.
        r = compute(ROOT, w, c, 100., Tokenizer())
        self.assertEqual(r['credited_weighted_tokens_by_class'][2], 0)
        self.assertEqual(r['compound_attained'], 0)

    def test_deadline_singleton_miss_is_not_credited(self):
        w, c = fixture();c[1]['stages'][0]['requests'][0]['client_request_end_monotonic'] = 11.
        r = compute(ROOT, w, c, 100., Tokenizer())
        self.assertEqual(r['credited_weighted_tokens_by_class'][1], 0)

if __name__ == '__main__':unittest.main(verbosity=2)
