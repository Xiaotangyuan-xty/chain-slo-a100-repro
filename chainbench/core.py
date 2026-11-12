"""Portable experiment contracts. No inference, device selection or training."""
from __future__ import annotations
import copy
import gzip
import hashlib
import json
import math
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[1]
METHODS = ('v47pro3', 'A', 'vllm-FCFS', 'sarathi-serve')
MODELS = {
    'llama8': 'meta-llama/Meta-Llama-3.1-8B-Instruct',
    'qwen14': 'Qwen/Qwen2.5-14B-Instruct',
    'qwen30': 'Qwen/Qwen3-30B-A3B-Instruct-2507',
    'llama70': 'meta-llama/Meta-Llama-3.1-70B-Instruct',
}
EXPECTED_COUNTS = {1: 80, 2: 20, 3: 6, 4: 8, 5: 8, 6: 12}
SEED = 2026111082

def sha(path):
    with Path(path).open('rb') as stream:
        digest=hashlib.sha256()
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):
            digest.update(chunk)
        return digest.hexdigest()

def read(path):
    return json.loads(Path(path).read_text())

def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')

def matrix():
    cases = []
    def add(suite, method, model='llama8', rate=.2, roots=200,
            arrival='poisson', kv_fraction=None, slo_factor=1.):
        n = sum(c['suite'] == suite for c in cases) + 1
        cases.append(dict(id=f's{suite}-{n:03d}', suite=suite, method=method,
            model=model, model_repository=MODELS[model], dtype='bfloat16',
            roots=roots, rate_chains_s=rate, window_seconds=roots/rate,
            arrival=arrival, arrival_seed=SEED,
            kv_mode='backend_auto' if kv_fraction is None else 'backend_relative_blocks',
            kv_fraction=kv_fraction, slo_factor=slo_factor,
            no_drain=True, metrics_scope='window_only',
            full_replay_metrics=None, tensor_parallel_proposal=4 if model=='llama70' else 1,
            a100_qualified=False))
    for model in MODELS:
        for rate in (.2, .4, .6, .8, 1.):
            for method in METHODS: add(1, method, model, rate)
    for fraction in (.2, .4, .6, .8, 1.):
        for method in METHODS: add(2, method, kv_fraction=fraction)
    for method in ('v47pro3', 'Oracle', 'no_credit', 'no_kv', 'no_event', 'chain_EDF'):
        add(3, method)
    for arrival in ('poisson', 'azure'):
        for method in METHODS: add(4, method, arrival=arrival)
    for model in ('llama8', 'qwen14'):
        for method in METHODS: add(5, method, model, roots=720)
    for factor in (.5, 1., 1.5):
        for method in METHODS: add(6, method, slo_factor=factor)
    assert {s:sum(c['suite']==s for c in cases) for s in EXPECTED_COUNTS} == EXPECTED_COUNTS
    return cases

def kv_blocks(default_blocks, fraction):
    if type(default_blocks) is not int or default_blocks < 1:
        raise ValueError('B must be the measured positive integer for this backend/profile')
    if not isinstance(fraction, (int,float)) or not math.isfinite(fraction) or not 0 < fraction <= 1:
        raise ValueError('KV fraction must be in (0,1]')
    return max(1, math.floor(default_blocks*fraction))

def offsets(case):
    n, horizon = case['roots'], case['window_seconds']
    if case['arrival']=='azure':
        data=read(ROOT/'data/azure200.json')
        if n != 200 or horizon != data['window_seconds']:
            raise ValueError('Azure mapping is frozen only for N=200,H=1000')
        return data['offsets_seconds']
    if case['arrival']!='poisson': raise ValueError('Unknown arrival process')
    # Conditional Poisson N(H)=N: order statistics of N Uniform(0,H).
    # Fix N and H together; do not silently replace by an unconditioned stream.
    rng=random.Random(case['arrival_seed'])
    return sorted(rng.random()*horizon for _ in range(n))

def workload(case):
    model=case['model'] if case['model'] in ('llama8','qwen14') else 'llama8'
    with gzip.open(ROOT/f'data/dr200_{model}.json.gz','rt') as stream:
        original=json.load(stream)
    jobs=[]; rng=random.Random(SEED+5)
    while len(jobs)<case['roots']:
        order=list(range(200))
        if case['roots']>200: rng.shuffle(order)
        for template_index in order:
            if len(jobs)==case['roots']: break
            row=copy.deepcopy(original['main'][template_index])
            cid=(len(jobs)*4+int(row['collection_id'])%4
                 if case['roots']>200 else row['collection_id'])
            # Residue controls public SLO class. Retain it when repeating templates.
            row['template_collection_id']=row['collection_id'];row['collection_id']=cid
            jobs.append(row)
    for row,arrival in zip(jobs,offsets(case)):
        row['arrival_offset_seconds']=arrival
        row['received_slo'][2]*=case['slo_factor']
    warmup=copy.deepcopy(original['warmup'])
    for row in warmup: row['received_slo'][2]*=case['slo_factor']
    return dict(schema='chainbench-fixed-replay/v1', main=jobs, warmup=warmup,
        case=case, tokenizer_metadata_model=model,
        target_tokenizer_verification_required=case['model'] not in ('llama8','qwen14'),
        policy='Frozen prompts, output targets, stage barriers; whole-chain SLO=received_slo[2]*stage_count',
        source_workload_sha256=sha(ROOT/f'data/dr200_{model}.json.gz'))

def source_check():
    manifest=read(ROOT/'provenance/SOURCE_SHA256.json')
    bad=[name for name,value in manifest['files'].items()
         if not (ROOT/name).is_file() or sha(ROOT/name)!=value]
    frozen=read(ROOT/'provenance/a40_SUITE_SPEC.json')['candidate_hashes']
    bad += ['frozen:'+name for name,value in frozen.items()
            if sha(ROOT/'vendor/v47pro3'/name)!=value]
    return {'gate':'FAIL' if bad else 'PASS', 'files_checked':len(manifest['files']),
            'frozen_candidate_files_checked':len(frozen), 'bad':bad, 'GPU_used':False}

def assess_profile(case, profile):
    """Report missing qualification evidence, without claiming a portable GPU runner."""
    errors=[]
    for k in ('model','method','dtype'):
        if profile.get(k)!=case[k]: errors.append(f'{k} mismatch')
    for k in ('model_revision','backend_source_sha256','environment_lock_sha256',
              'tokenizer_receipt_sha256','deployment_receipt_sha256',
              'cutoff_gate_sha256','cleanup_gate_sha256','raw_audit_gate_sha256'):
        if not profile.get(k): errors.append(f'missing {k}')
    if profile.get('a100_qualification')!='PASS': errors.append('A100 qualification is not PASS')
    cap=profile.get('default_kv',{})
    for k in ('blocks','block_tokens','bytes_per_block','physical_bytes','tp_interpretation'):
        if not cap.get(k):errors.append(f'missing default_kv.{k}')
    if case['model'] in ('qwen30','llama70') and not profile.get('predictor_policy'):
        errors.append('30B/70B predictor transfer policy is not frozen')
    return dict(gate='BLOCKED' if errors else 'PASS',errors=errors,
                explicit_blocks=kv_blocks(cap['blocks'],case['kv_fraction'])
                if not errors and case['kv_fraction'] else None)

def classify_window(arrival, deadline, finish, horizon):
    """All timestamps relative to common main origin; observations at H excluded."""
    if arrival>=horizon:return 'NOT_ARRIVED'
    if finish is not None and finish<horizon:
        return 'ATTAINED' if finish<=deadline else 'DEFINITE_MISS'
    return 'DEFINITE_MISS' if deadline<=horizon else 'RIGHT_CENSORED'
