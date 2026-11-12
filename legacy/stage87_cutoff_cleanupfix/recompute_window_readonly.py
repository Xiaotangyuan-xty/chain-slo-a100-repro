"""Independent actual-text fixed-window audit. Does not import the run's metric code."""
from pathlib import Path
from collections import Counter
from datetime import datetime,timezone
import hashlib,json,math,sys
from transformers import AutoTokenizer
packet=json.load(sys.stdin);rows=[]
for spec in packet['cases']:
    C=Path(spec['path']);A=C/'attempts'/spec['attempt'];work=json.loads((C/'WORKLOAD.json').read_text());p=json.loads((C/'PROTOCOL.json').read_text())
    snap=json.loads((A/'CLIENT_CUTOFF_SNAPSHOT.json').read_text());origin=snap['origin_monotonic'];end=snap['cutoff_monotonic'];H=p['cutoff_seconds'];assert math.isclose(end-origin,H,rel_tol=0,abs_tol=1e-7)
    gate=json.loads((C/'receipts'/('RUN_GATE_'+spec['attempt']+'.json')).read_text());assert gate['gate']=='PASS'
    # Tokenizer and text cache belong to this case, including mixed-model packets.
    tokenizer=AutoTokenizer.from_pretrained(p['model_path'],local_files_only=True,trust_remote_code=False)
    cache={}
    def count(text):
        h=hashlib.sha256(text.encode()).digest()
        if h not in cache:cache[h]=len(tokenizer(text,add_special_tokens=False).input_ids)
        return cache[h]
    jobs={j['collection_id']:j for j in work['main']};assert len(jobs)==len(snap['roots'])==200
    total=finished=attained=missed=unresolved=0;settlements=[]
    for c in snap['roots']:
        j=jobs[c['collection_id']];assert c['received_slo']==j['received_slo']
        start=c['client_chain_start_monotonic'];stop=c['client_chain_end_monotonic'];assert origin<=start<end
        complete=c['success']and stop is not None and stop<end
        if complete:
            finished+=1;reward=0;assert len(c['stages'])==len(j['stages'])
            for sid,(stage,wanted)in enumerate(zip(c['stages'],j['stages'])):
                assert stage['success']and stage['stage_id']==sid
                frozen={r['request_id']:r for r in wanted};assert set(frozen)=={r['request_id']for r in stage['requests']}
                for r in stage['requests']:
                    assert r['success']and r['input_prompt_sha256']==frozen[r['request_id']]['prompt_sha256']and r['client_request_end_monotonic']<end
                    reward+=count(frozen[r['request_id']]['prompt'])+8*count(r['generated_text'])
            for left,right in zip(c['stages'],c['stages'][1:]):assert max(r['client_request_end_monotonic']for r in left['requests'])<=min(r['client_request_start_monotonic']for r in right['requests'])
            if stop-start<=c['received_slo'][2]*len(j['stages']):total+=reward;attained+=1;settlements.append((stop-origin,reward))
            else:missed+=1
        elif start+c['received_slo'][2]*len(j['stages'])<=end:missed+=1
        else:unresolved+=1
    prefix_counts={};prefixes={};raw_tokens=0;digests={};counts={};late_model_calls=0
    for name in ['WINDOW_TOKEN_DELTAS.jsonl','EXECUTOR_EVENTS.jsonl','WINDOW_KV_SAMPLES.jsonl','WINDOW_GPU_CPU_SAMPLES.jsonl','SHARED_PREDICTION_EVENTS.jsonl','NATIVE_GRAPH_EVENTS.jsonl','V47PRO_DECISIONS.jsonl','SCHEDULER_CPU_EVENTS.jsonl','LIFETIME_TIMINGS.jsonl','common_events.jsonl']:
        path=A/name
        if not path.exists():continue
        h=hashlib.sha256();n=0
        with path.open('rb')as stream:
            for line in stream:
                h.update(line);e=json.loads(line);n+=1
                if name=='WINDOW_TOKEN_DELTAS.jsonl':
                    uid=e['request_uuid'];assert e['previous_tokens']==prefix_counts.get(uid,0)
                    prefix_counts[uid]=e['output_tokens'];prefixes.setdefault(uid,[]).extend(e['new_token_ids'])
                    if e['phase']=='main':assert origin<=e['monotonic']<end;raw_tokens+=len(e['new_token_ids'])
                elif name=='EXECUTOR_EVENTS.jsonl':
                    assert math.isfinite(e['start_monotonic'])
                    late_model_calls+=e['start_monotonic']>=end
                    assert e['error']is None or(e['error']=='CancelledError'and e['end_monotonic']>=end)
                elif name=='SHARED_PREDICTION_EVENTS.jsonl':assert not(e['kind']=='prediction_fallback'and e['monotonic']<end)
        digests[name]=h.hexdigest();counts[name]=n
    assert late_model_calls==0,'Model execution started after fixed cutoff'
    server=json.loads((A/'WINDOW_SERVER_CUTOFF.json').read_text());progress={r['request_uuid']:r for r in server['requests']}
    for uid,ids in prefixes.items():assert progress[uid]['output_prefix_sha256']==hashlib.sha256(json.dumps([ids]).encode()).hexdigest()
    with(A/'SCHEDULER_CPU_EVENTS.jsonl').open()as stream:cpu=[json.loads(l)for l in stream]
    runtime=json.loads((A/'SCHEDULER_CPU_RUNTIME.json').read_text());assert len(cpu)==runtime['calls']and runtime['failed_calls']==0
    cpu_main=sorted(e['thread_cpu_ns']/1e6 for e in cpu if origin<=e['start_monotonic']<end);assert cpu_main
    def percentile(v,q):
        x=(len(v)-1)*q;i=int(x);return v[i]+(v[min(i+1,len(v)-1)]-v[i])*(x-i)
    cpu_values={'schedule_calls_main':len(cpu_main),'scheduler_CPU_P50_ms':percentile(cpu_main,.5),'scheduler_CPU_P95_ms':percentile(cpu_main,.95),'scheduler_CPU_total_seconds':sum(cpu_main)/1000}
    assert all(math.isclose(v,gate['metrics'][k],rel_tol=1e-9,abs_tol=1e-7)for k,v in cpu_values.items())
    values={'fixed_window_settled_credit':total,'fixed_window_credit_per_second':total/H,'arrived_roots':200,
        'completed_chains_before_cutoff':finished,'SLO_attained_chains_before_cutoff':attained,
        'definite_SLO_misses_by_cutoff':missed,'SLO_outcome_right_censored':unresolved,
        'unfinished_chains_at_cutoff':200-finished,'actual_output_tokens_observed_in_window':raw_tokens}
    checks={k:math.isclose(v,gate['metrics'][k],rel_tol=1e-10,abs_tol=1e-7)for k,v in values.items()};assert all(checks.values())
    for i,row in enumerate(gate['metrics']['equal_window_bins']):assert sum(reward for stamp,reward in settlements if i*H/12<=stamp<(i+1)*H/12)==row['settled_credit']
    rows.append({'name':spec['name'],'gate':'PASS','checks':checks,'independent_metrics':values,'full_trace_sha256':digests,
        'full_trace_record_counts':counts,'post_cutoff_model_calls':late_model_calls,'no_drain_or_future_credit':True})
import torch
assert not torch.cuda.is_initialized()
print(json.dumps({'utc':datetime.now(timezone.utc).isoformat(),'gate':'PASS','GPU_used':False,'cases':rows}))
