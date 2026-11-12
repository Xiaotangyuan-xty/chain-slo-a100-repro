"""Length-only oracle outside the frozen 28-file candidate tree.

The donor/input/service models and final score formula are retained. Only output
length reads, including missing/current/future stages, receive exact targets.
The lookup has no arrival arrays, true service times, future input text or tokens.
"""
import ast
import atexit
from collections import Counter
from contextvars import ContextVar
import hashlib
import inspect
import json
from pathlib import Path
import textwrap
import time
import types

VERSION = 'v47pro3_length_only_oracle_v1'


class LengthTruth:
    def __init__(self, data, log=None):
        if set(data) != {'schema', 'roots'} or data['schema'] != 'length-only-oracle/v1':
            raise ValueError('Oracle accepts lengths only; no arrival, runtime or input fields')
        self.roots = {}
        for key, stages in data['roots'].items():
            if not isinstance(key, str) or not stages or not all(isinstance(s, list) and s for s in stages):
                raise ValueError('Invalid root/stage table')
            if not all(type(n) is int and 1 <= n <= 1024 for s in stages for n in s):
                raise ValueError('Invalid frozen output length')
            self.roots[key] = stages
        self.active = set()
        self.stats = Counter()
        self.context = ContextVar('active_oracle_root', default=None)
        self.log = log or (lambda *a, **k: None)

    def activate(self, key):
        if key not in self.roots:
            raise KeyError('Unknown oracle root')
        if key not in self.active:
            self.active.add(key)
            self.stats['activated_roots'] += 1
            self.log('root_activated', root=key)

    def target(self, key, stage, member, cap=1024):
        if key not in self.active:
            self.stats['unarrived_root_access_rejected'] += 1
            raise PermissionError('Future root has not actually arrived')
        n = self.roots[key][stage][member]
        if n > cap:
            raise ValueError('Frozen target exceeds the actual sampling cap')
        self.stats['length_reads'] += 1
        return n

    def current_target(self, stage, member, cap=1024):
        key = self.context.get()
        if key is None:
            raise RuntimeError('Oracle estimate has no arrived-root context')
        return self.target(key, stage, member, cap)


def bind_forecaster(model, truth):
    """Replace prediction reads, retaining all score, input and service arithmetic."""
    if getattr(model, '_length_oracle_bound', False):
        raise RuntimeError('Fresh forecaster required')
    original_estimate = model.estimate
    original_future = model.future_components
    source = textwrap.dedent(inspect.getsource(type(model)._estimate))
    tree = ast.parse(source)
    changed = Counter()

    class Reads(ast.NodeTransformer):
        def visit_Assign(self, node):
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'n':
                # This is the output prediction for an unsubmitted member of the
                # current stage. Keep the original donor/input index unchanged.
                if ast.unparse(node.value) == "min(cap, z['outputs'][index])":
                    node.value = ast.parse('self._oracle_target(stage, member, cap)', mode='eval').body
                    changed['missing_member_length_read'] += 1
            return self.generic_visit(node)

        def visit_If(self, node):
            if (ast.unparse(node.test) == 'not survivors' and len(node.body) == 1
                    and isinstance(node.body[0], ast.Assign)
                    and ast.unparse(node.body[0].targets[0]) == 'remaining'):
                # The statistical 50-token survival backoff must not turn an
                # exactly known zero remainder into a guessed positive length.
                node.body = [ast.Pass()]
                changed['statistical_length_backoff_removed'] += 1
                return node
            return self.generic_visit(node)

    tree = Reads().visit(tree)
    if dict(changed) != {'missing_member_length_read': 1, 'statistical_length_backoff_removed': 1}:
        raise RuntimeError('Unexpected frozen estimator ABI; refuse partial oracle')
    namespace = dict(type(model)._estimate.__globals__)
    exec(compile(ast.fix_missing_locations(tree), '<declared-length-oracle-estimator>', 'exec'), namespace)
    model._estimate = types.MethodType(namespace['_estimate'], model)
    model._oracle_target = truth.current_target
    model.member_target = lambda row, stage, member, width, cap: truth.current_target(stage, member, cap)

    def future(row, stage, widths, cap):
        work, critical, reward = original_future(row, stage, widths, cap)
        for sid in range(stage + 1, len(widths)):
            previous = [min(cap, x) for x in row['stages'][sid]['outputs']]
            ratio = widths[sid] / max(1, len(previous))
            actual = [truth.current_target(sid, i, cap) for i in range(widths[sid])]
            truth.stats['future_stage_length_reads'] += len(actual)
            difference = sum(actual) - sum(previous) * ratio
            work += difference
            critical += max(actual) - max(previous)
            reward += 8 * difference
        return work, critical, reward

    def estimate(meta, stage, views, slack, token_seconds):
        key = meta['_oracle_root_key']
        if key not in truth.active:
            raise PermissionError('Estimator accessed an unarrived root')
        if list(map(len, truth.roots[key])) != list(meta['widths']):
            raise ValueError('Oracle and publicly declared structure disagree')
        token = truth.context.set(key)
        try:
            truth.stats['forecast_calls'] += 1
            truth.stats['remaining_length_checks'] += len(views)
            for v in views:
                total = truth.current_target(stage, v['member'], v['max_tokens'])
                if v['generated'] > total:
                    raise ValueError('Generated prefix exceeds frozen target')
                sample_key = 'remaining_samples_' + key.split(':', 1)[0]
                if truth.stats[sample_key] < 64:
                    truth.stats[sample_key] += 1
                    truth.log('remaining_sample', root=key, stage_id=stage,
                              request_id=v['member'], generated=v['generated'],
                              true_total=total, remaining=total-v['generated'])
            return original_estimate(meta, stage, views, slack, token_seconds)
        finally:
            truth.context.reset(token)

    model.future_components = future
    model.estimate = estimate
    model._length_oracle_bound = True
    return {'estimator_original_source_sha256': hashlib.sha256(source.encode()).hexdigest(),
            'runtime_prediction_read_changes': dict(changed),
            'score_formula_changed': False, 'input_forecast_changed': False,
            'service_time_model_changed': False, 'donor_neighbor_selection_changed': False,
            'future_cache_contains_only_original_donor_predictions': True}


def prepare(server, output):
    output = Path(output)
    stage = output.parents[1]
    suite = json.loads((stage / 'SUITE_SPEC.json').read_text())
    enabled = suite.get('information_mode', 'predicted') == 'oracle'
    receipt = {'version': VERSION, 'enabled': enabled, 'future_arrivals_accessed': False,
               'true_execution_times_accessed': False, 'future_input_tokens_accessed': False,
               'future_output_lengths_accessed': enabled, 'score_formula_changed': False,
               'frozen_candidate_files_modified': False}
    if not enabled:
        (output / 'INFORMATION_ADAPTER.json').write_text(json.dumps(receipt, indent=2) + '\n')
        return receipt, None
    datafile = stage / 'ORACLE_LENGTHS.json'
    data = datafile.read_bytes()
    if hashlib.sha256(data).hexdigest() != suite['oracle_lengths_sha256']:
        raise ValueError('Oracle length table is not frozen')
    stream = (output / 'ORACLE_EVENTS.jsonl').open('x')

    def log(kind, **fields):
        stream.write(json.dumps({'kind': kind, 'monotonic': time.perf_counter(), **fields}) + '\n')
        stream.flush()

    truth = LengthTruth(json.loads(data), log)
    original_collective = server._handle_collective_request

    def collective(info, request_dict, prompt):
        phase = 'warmup' if request_dict.get('client_id') == 900000 else 'main'
        key = phase + ':' + str(info.collection_id)
        truth.activate(key)
        info._oracle_root_key = key
        return original_collective(info, request_dict, prompt)

    def predictor(info):
        value = truth.target(info._oracle_root_key, info.stage_id, info.request_id)
        truth.stats['request_predictions'] += 1
        log('request_prediction', root=info._oracle_root_key, stage_id=info.stage_id,
            request_id=info.request_id, prediction=value)
        return value

    server._handle_collective_request = collective
    server._length_oracle_predictor = predictor
    receipt['oracle_lengths_sha256'] = suite['oracle_lengths_sha256']
    receipt['truth_file_fields'] = ['schema', 'roots:phase/cid->stages->output_lengths']

    def finish():
        receipt['counts'] = dict(truth.stats)
        (output / 'INFORMATION_ADAPTER.json').write_text(json.dumps(receipt, indent=2) + '\n')
        stream.close()

    atexit.register(finish)
    return receipt, truth


def install_forecaster(truth, receipt, candidate, output):
    if truth is None:
        return
    from frozen_v47 import native_chain
    import pure_core_v47
    if pure_core_v47.MODEL is not native_chain.MODEL:
        raise RuntimeError('Frozen pure forecaster identity changed')
    policy = native_chain.ChainCompletionPolicy
    original_add = policy.add_seq_group

    def add(self, group):
        result = original_add(self, group)
        self.chains[group.collection_id]['_oracle_root_key'] = group.request_info._oracle_root_key
        return result

    policy.add_seq_group = add
    receipt.update(bind_forecaster(native_chain.MODEL, truth))
    # The original installer's receipt is a mutable object captured by its
    # final writer. Declare the external oracle there as well as in this file.
    candidate.update(future_truth_access=True, future_truth_scope='output_lengths_only',
                     external_information_adapter=VERSION)
    for name in ['V47PRO_RUNTIME.json', 'MIXED_RUNTIME.json']:
        path = Path(output) / name
        if path.exists():
            row = json.loads(path.read_text())
            row.update(future_truth_access=True, future_truth_scope='output_lengths_only',
                       external_information_adapter=VERSION)
            path.write_text(json.dumps(row, indent=2) + '\n')
    Path(output, 'INFORMATION_ADAPTER.json').write_text(json.dumps(receipt, indent=2) + '\n')
