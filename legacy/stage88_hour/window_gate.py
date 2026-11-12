"""Validate the fixed 3600s observation and explicit right censoring, never a drain."""
from pathlib import Path
from collections import Counter
import hashlib,json,math,sys
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def executor_trace_checks(attempt,end):
    # Warmup may precede the main window; no executor may start at/after H.
    execution=failed_before=unexpected_errors=late_starts=0
    with(attempt/'EXECUTOR_EVENTS.jsonl').open()as stream:
        for line in stream:
            e=json.loads(line);execution+=1
            late_starts+=not(math.isfinite(e['start_monotonic'])and e['start_monotonic']<end)
            if e['error']:
                failed_before+=e['end_monotonic']<end
                unexpected_errors+=e['error']!='CancelledError'
    return {
        'executor_trace_complete_and_no_pre_cutoff_failure':execution==read(attempt/'EXECUTOR_OBSERVATION.json')['events']and failed_before==unexpected_errors==0,
        'executor_starts_strictly_before_cutoff':late_starts==0,
    }

def analyze(root,C,attempt_name):
    A=C/'attempts'/attempt_name;p=read(C/'PROTOCOL.json');work=read(C/'WORKLOAD.json');snapshot=read(A/'CLIENT_CUTOFF_SNAPSHOT.json')
    common=read(A/'common_audit_summary.json');control=read(A/'controller_receipt.json');server=read(A/'WINDOW_SERVER_CUTOFF.json')
    start=snapshot['origin_monotonic'];end=snapshot['cutoff_monotonic'];expected={(ph,j['collection_id'],sid,r['request_id']):(j,r)for ph in ['warmup','main']for j in work[ph]for sid,s in enumerate(j['stages'])for r in s}
    engine={r['request_uuid']:r for r in common['requests']};observed={};bad=[]
    from pure_metrics import expected_engine_sampling
    for uid,e in engine.items():
        key=(e['phase'],e['collection_id'],e['stage_id'],e['request_id']);assert key in expected and key not in observed
        observed[key]=e;j,r=expected[key]
        if e['prompt_sha256']!=r['prompt_sha256']or e['received_slo']!=j['received_slo']:bad.append('payload')
        if any(e['generation'].get(k)!=v for k,v in expected_engine_sampling(p['generation'],r['target_output_tokens']).items()):bad.append('sampling')
    raw={}
    for line in(A/'engine_token_ids.jsonl').open():
        e=json.loads(line);key=(e['phase'],e['collection_id'],e['stage_id'],e['request_id']);j,r=expected[key]
        assert key not in raw;raw[key]=e
        assert hashlib.sha256(json.dumps(e['prompt_token_ids']).encode()).hexdigest()==e['prompt_token_ids_sha256']==r['prompt_token_ids_sha256']
        assert hashlib.sha256(json.dumps(e['output_token_ids']).encode()).hexdigest()==e['output_token_ids_sha256']
        assert sum(map(len,e['output_token_ids']))==r['target_output_tokens']
    H=p["cutoff_seconds"];bin_seconds=H/12
    prefixes={};token_bins=[0]*12;raw_window_tokens=0
    for line in(A/'WINDOW_TOKEN_DELTAS.jsonl').open():
        e=json.loads(line);uid=e['request_uuid'];key=(e['phase'],e['collection_id'],e['stage_id'],e['request_id']);assert key in expected and uid in engine
        ids=prefixes.setdefault(uid,[]);assert e['previous_tokens']==len(ids);ids.extend(e['new_token_ids']);assert len(ids)==e['output_tokens']<=expected[key][1]['target_output_tokens']
        if e['phase']=='main':
            assert start<=e['monotonic']<end
            raw_window_tokens+=len(e['new_token_ids']);token_bins[min(11,int((e['monotonic']-start)/bin_seconds))]+=len(e['new_token_ids'])
    progress={r['request_uuid']:r for r in server['requests']}
    assert set(prefixes)<=set(progress)
    for uid,ids in prefixes.items():
        r=progress[uid];assert r['output_tokens']==len(ids)and r['output_prefix_sha256']==hashlib.sha256(json.dumps([ids]).encode()).hexdigest()
        key=(r['phase'],r['collection_id'],r['stage_id'],r['request_id'])
        assert r['prompt_token_ids_sha256']==expected[key][1]['prompt_token_ids_sha256']
        if r['finished']:assert key in raw and raw[key]['output_token_ids']==[ids]
    # Primary credit uses actual submitted/returned text, retaining the established metric.
    from transformers import AutoTokenizer
    tokenizer=AutoTokenizer.from_pretrained(p['model_path'],local_files_only=True,trust_remote_code=False)
    cache={}
    def count(text):
        h=hashlib.sha256(text.encode()).digest()
        if h not in cache:cache[h]=len(tokenizer(text,add_special_tokens=False).input_ids)
        return cache[h]
    text_counts={};arrival_errors=[];barriers=True;completed_ids=[]
    for c in snapshot['roots']:
        job=next(j for j in work['main']if j['collection_id']==c['collection_id']);arrival_errors.append(abs(c['arrival_offset_seconds']-job['arrival_offset_seconds']))
        for sid,stage in enumerate(c['stages']):
            wanted={r['request_id']:r for r in job['stages'][sid]}
            assert stage['stage_id']==sid and len({r['request_id']for r in stage['requests']})==len(stage['requests'])
            for r in stage['requests']:
                assert r['request_id']in wanted and r['input_prompt_sha256']==wanted[r['request_id']]['prompt_sha256']and r['target_output_tokens']==wanted[r['request_id']]['target_output_tokens']and r['received_slo']==job['received_slo']
        for left,right in zip(c['stages'],c['stages'][1:]):
            if right['requests']:barriers&=left['success']and all(r['client_request_end_monotonic']is not None for r in left['requests'])and max(r['client_request_end_monotonic']for r in left['requests'])<=min(r['client_request_start_monotonic']for r in right['requests'])
        if not(c['success']and c['client_chain_end_monotonic']is not None and c['client_chain_end_monotonic']<end):continue
        completed_ids.append(c['collection_id'])
        for sid,stage in enumerate(c['stages']):
            for r in stage['requests']:
                key=('main',c['collection_id'],sid,r['request_id']);job,frozen=expected[key]
                assert key in raw and observed[key]['finished']and observed[key]['finish_monotonic']<end
                text_counts[key[1:]]=(count(frozen['prompt']),count(r['generated_text']))
    from window_metrics import classify
    metrics=classify(snapshot,work,text_counts)
    metrics.update(main_root_jobs=len(work['main']),main_requests_observed=sum(e['phase']=='main'for e in engine.values()),
        actual_output_tokens_observed_in_window=raw_window_tokens,actual_output_tokens_per_second=raw_window_tokens/H,
        completed_chains_per_second=metrics['completed_chains_before_cutoff']/H,
        max_arrival_error=max(arrival_errors),post_window_credit_not_measured=True)
    for row,n in zip(metrics['equal_window_bins'],token_bins):row.update(actual_output_tokens=n,actual_output_tokens_per_second=n/bin_seconds)
    suite=read(A/'COMPARISON_SUITE_RUNTIME.json');runtime=read(A/'WINDOW_OBSERVATION_RUNTIME.json');done=read(A/'CLIENT_DONE.json')
    predictions=[json.loads(l)for l in(A/'SHARED_PREDICTION_EVENTS.jsonl').open()]if(A/'SHARED_PREDICTION_EVENTS.jsonl').exists()else[]
    checks={'CPU_qualification':read(C/'receipts/CPU_QUALIFICATION.json')['gate']=='PASS',
        'frozen_workload':sha(C/'WORKLOAD.json')==p['workload_sha256'],'frozen_arrivals':len(work['main'])==p['root_count'] and len(snapshot['roots'])==p['root_count'] and not snapshot['not_arrived_ids'],
        'actual_arrival_error_le0p5':max(arrival_errors)<=.5,'stage_dependencies':barriers,
        'fixed_rate_window_measurement':math.isclose(end-start,H,rel_tol=0,abs_tol=1e-7)and math.isclose(H,3600.,rel_tol=0,abs_tol=1e-7)and p['root_count']==int(3600*p['generation']['arrival_rate']),
        'no_drain_and_all_local_tasks_stopped':done['no_drain']and done['window_complete']and done['all_local_tasks_stopped'],
        'client_stopped_at_cutoff':0<=snapshot['stop_lag_seconds']<=.5,
        'server_stopped_new_GPU_execution_at_cutoff':runtime['closed']and runtime['cutoff_monotonic']==end and server['planned_cutoff_monotonic']==end and 0<=server['stop_lag_seconds']<=.5,
        'no_technical_errors_before_cutoff':not snapshot['technical_errors_before_cutoff']and not done['technical_errors_before_cutoff'],
        'actual_observed_payloads_and_sampling':not bad,'warmup_PASS':read(A/'WARMUP_NATIVE_TOT_GATE.json')['gate']=='PASS',
        'no_prediction_fallback_inside_window':not any(e['kind']=='prediction_fallback'and e['monotonic']<end for e in predictions),
        'actual_model_resources':all(common['resources'].get(k)==v for k,v in p['expected_resource_caps'].items()),
        'assigned_GPU1':common['device']['physical_gpu_index']==1 and common['device']['actual_uuid']==p['resources']['gpu_uuid'],
        'registered_cleanup':control['failure']is None and control['client_returncode']==0 and control['gpu_released']and not control['own_gpu_processes_remaining'],
        'model_assets_verified_before_GPU':control['model_asset_verification']['gate']=='PASS',
        'declared_runtime':suite['method']==p['candidate_version']and suite['release']==p['release_version']and suite['frozen_candidate_modules_exact'],
        'baseline_budget_adapter_presence':(A/'BASELINE_BUDGET_ADAPTER.json').exists()==(p['candidate_version']=='Astar'),
        'original_policy_type':(common['resources']['scheduler_type']=='vllm.core.scheduler.Scheduler'and common['resources']['policy_type'].endswith('.FCFSPolicy'))if p['candidate_version']=='native_vllm'else((common['resources']['scheduler_type']=='jitserve.scheduler.slo_scheduler.SLOScheduler'and common['resources']['policy_type']=='jitserve.scheduler.policy.SLOPolicy')if p['candidate_version']in ['A','Astar']else common['resources']['mechanism_version']==p['C_version']),
        'active_module_hashes':all(sha(Path(v['path']))==v['sha256']for v in suite['active_modules'].values()),
        'published28_files_unchanged':all(sha(C/'candidate_source'/n)==h for n,h in read(C/'SUITE_SPEC.json')['candidate_hashes'].items()),
        'oracle_disabled':not read(A/'INFORMATION_ADAPTER.json')['enabled']and not(A/'ORACLE_EVENTS.jsonl').exists(),
        'no_added_CUDA_sync':not runtime['CUDA_synchronization_added']}
    native=p['candidate_version']=='native_vllm'
    checks['automatic_KV_no_override']=p['resources']['num_gpu_blocks_override']is None and 'gpu_blocks'not in p['expected_resource_caps'] and common['resources']['gpu_blocks']>0
    checks['native_FCFS_prediction_disabled']=not native or(not suite['candidate_scheduler_installed']and not suite['candidate_modules_loaded']and not suite['prediction_enabled']and not suite['graph_matching_enabled']and not predictions and not(A/'SHARED_PREDICTION_RUNTIME.json').exists())
    checks['native_backend_unchanged']=all(sha(Path(n))==v for n,v in p['native_backend_sha256'].items())
    from resource_contract_validation import verify
    checks.update(verify(p,common,read(A/'processes.json'))['checks'])
    checks.update(executor_trace_checks(A,end))
    gpu=[json.loads(l)for l in(A/'WINDOW_GPU_CPU_SAMPLES.jsonl').open()];kv=[json.loads(l)for l in(A/'WINDOW_KV_SAMPLES.jsonl').open()]
    checks['GPU_and_KV_time_series_present']=any(start<=r['monotonic']<end and r['query_returncode']==0 and r['gpu'].startswith('1, '+p['resources']['gpu_uuid'])for r in gpu)and any(start<=r['monotonic']<end and'gpu_blocks_free'in r for r in kv)
    signatures={str(k):{n:e[n]for n in ['prompt_sha256','generation','received_slo']}for k,e in observed.items()}
    from cutoff_statistics import summarize
    metrics.update(summarize(A,snapshot,start,end,H))
    from rate_contract import verify as verify_rate
    checks.update(verify_rate(C))
    result={'gate':'PASS'if all(checks.values())else'FAIL','checks':checks,'metrics':metrics,'request_signatures':signatures,
        'resources':common['resources'],'GPU_UUID':common['device']['actual_uuid'],'completed_before_cutoff_ids':completed_ids,
        'prediction_counts':dict(Counter(e['kind']for e in predictions)),
        'scope':'Exactly N/rate seconds; no full replay/drain. Unfinished chains are censored; known-deadline misses distinguished from unresolved outcomes. Only completed SLO-attained chains settle actual-text credit before cutoff.'}
    (A/'CUTOFF_CREDIT_LEDGER.json').write_text(json.dumps(metrics['settlements'])+'\n')
    (C/'receipts'/('RUN_GATE_'+attempt_name+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    return result
if __name__=='__main__':
    r=analyze(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3]);print(json.dumps({'gate':r['gate'],'checks':r['checks'],'metrics':r['metrics']}));raise SystemExit(0 if r['gate']=='PASS'else 1)
