"""Exact source scope for authorized second Oracle lifecycle recovery."""
import hashlib
TRANSFORMS = [("    def add(self, group):\n        result = original_add(self, group)\n        self.chains[group.collection_id]['_oracle_root_key'] = group.request_info._oracle_root_key\n        return result\n", "    def add(self, seq_group):\n        result = original_add(self, seq_group)\n        self.chains[seq_group.collection_id]['_oracle_root_key'] = seq_group.request_info._oracle_root_key\n        return result\n"), ('    truth = LengthTruth(json.loads(data), log)\n    original_collective = server._handle_collective_request', "    truth = LengthTruth(json.loads(data), log)\n    original_build_request_info = server._build_request_info\n\n    def build_request_info(request_dict, client_id):\n        # The native HTTP handler calls this after receiving/parsing the request\n        # and before it starts the asynchronous prediction thread.\n        info, prompt = original_build_request_info(request_dict, client_id)\n        if info.request_type == server.RequestType.COLLECTIVE:\n            phase = 'warmup' if client_id == 900000 else 'main'\n            key = phase + ':' + str(info.collection_id)\n            truth.activate(key)\n            info._oracle_root_key = key\n            truth.stats['request_bindings'] += 1\n            log('request_bound', root=key, stage_id=info.stage_id,\n                request_id=info.request_id)\n        return info, prompt\n\n    original_collective = server._handle_collective_request"), ('    server._handle_collective_request = collective\n    server._length_oracle_predictor = predictor', "    server._build_request_info = build_request_info\n    server._handle_collective_request = collective\n    server._length_oracle_predictor = predictor\n    receipt['request_root_binding'] = {\n        'hook': '_build_request_info',\n        'timing': 'after_received_request_parse_before_prediction_thread',\n    }")]
LIFECYCLE_HELPER = '"""Offline-only checks; client arrival times are never provided to the Oracle."""\ndef lifecycle_checks(receipt, events, work, calls):\n    expected={(phase+\':\'+str(job[\'collection_id\']),sid,r[\'request_id\'])\n        for phase in [\'warmup\',\'main\']for job in work[phase]\n        for sid,stage in enumerate(job[\'stages\'])for r in stage}\n    roots={key for key,_,_ in expected}\n    arrivals={c[\'phase\']+\':\'+str(c[\'collection_id\']):c[\'client_chain_start_monotonic\']for c in calls}\n    activated={};bound={};predicted=set();bad=[]\n    for e in events:\n        key=e.get(\'root\');stamp=e.get(\'monotonic\')\n        if key not in roots or stamp is None:\n            bad.append(\'unknown_root_or_timestamp\');continue\n        if e[\'kind\']==\'root_activated\':\n            if key in activated or key not in arrivals or stamp<arrivals[key]:\n                bad.append(\'activation_before_actual_client_arrival_or_duplicate\')\n            activated[key]=stamp\n            continue\n        if key not in activated or stamp<activated[key]:\n            bad.append(\'event_before_root_activation\')\n        if e[\'kind\'] in [\'request_bound\',\'request_prediction\']:\n            identity=(key,e[\'stage_id\'],e[\'request_id\'])\n            if identity not in expected:bad.append(\'unknown_request_identity\')\n            if e[\'kind\']==\'request_bound\':\n                if identity in bound:bad.append(\'duplicate_binding\')\n                bound[identity]=stamp\n            else:\n                if identity not in bound or bound[identity]>stamp:bad.append(\'prediction_before_binding\')\n                if identity in predicted:bad.append(\'duplicate_prediction\')\n                predicted.add(identity)\n    return {\n        \'oracle_root_binding_hook_declared\':receipt.get(\'request_root_binding\')=={\n            \'hook\':\'_build_request_info\',\'timing\':\'after_received_request_parse_before_prediction_thread\'},\n        \'oracle_each_request_bound_before_prediction\':not bad and set(bound)==predicted==expected,\n        \'oracle_root_activation_after_actual_client_arrival\':not bad and set(activated)==roots and set(arrivals)==roots,\n        \'oracle_exact_request_binding_count\':receipt.get(\'counts\',{}).get(\'request_bindings\')==len(expected),\n    }\n'
LIFECYCLE_RETURN = "    if mode == 'oracle':\n        calls=json.loads((attempt/'client_calls.json').read_text())\n        events=[json.loads(line)for line in(attempt/'ORACLE_EVENTS.jsonl').open()]\n        checks.update(lifecycle_checks(receipt,events,work,calls))\n    return checks\n"
def verify_source_delta(original,repaired):
    expected=original
    for before,after in TRANSFORMS:
        assert expected.count(before)==1,'Unexpected adapter source'
        expected=expected.replace(before,after)
    assert expected==repaired,'Undeclared adapter change'
    return {'old_adapter_sha256':hashlib.sha256(original.encode()).hexdigest(),
            'new_adapter_sha256':hashlib.sha256(repaired.encode()).hexdigest()}
def verify_validator_delta(original,repaired):
    assert original.count('    return checks\n')==1
    assert repaired==LIFECYCLE_HELPER+'\n'+original.replace('    return checks\n',LIFECYCLE_RETURN),'Undeclared acceptance change'
    return True
def normalize_runtime_hashes(old_hashes,new_hashes,proof):
    key='common_runtime/oracle_length_adapter.py'
    assert set(old_hashes)==set(new_hashes)
    assert old_hashes[key]==proof['old_adapter_sha256']and new_hashes[key]==proof['new_adapter_sha256']
    assert all(old_hashes[k]==new_hashes[k]for k in old_hashes if k!=key),'Other shared runtime changed'
    return {**new_hashes,key:old_hashes[key]}

"""Read-only comparison for a completed hour trio or predicted/Oracle pair."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,sys

def read(p):return json.loads(p.read_text())
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True).encode()).hexdigest()
rows=[]
case_paths=[]
order_compatibility=[]
for item in json.load(sys.stdin)['cases']:
    C=Path(item['path']);case_paths.append(C);spec=read(C/'CASE_SPEC.json');A=C/'attempts'/spec['attempt']
    g=read(C/'receipts'/('RUN_GATE_'+spec['attempt']+'.json'));assert g['gate']=='PASS'and all(g['checks'].values())
    p=read(C/'PROTOCOL.json');suite=read(C/'SUITE_SPEC.json');common=read(A/'common_audit_summary.json');profile=read(C/'MODEL_PROFILE.json')
    resources={k:common['resources'][k]for k in ['model_path','tokenizer_path','dtype','gpu_blocks','cpu_blocks','block_size','swap_space_bytes','max_num_seqs','max_num_batched_tokens','max_model_len','enforce_eager','single_engine','enable_chunked_prefill','enable_prefix_caching']}
    rows.append({'case':C.name,'method':spec['display_method'],'information_mode':spec['information_mode'],
       'workload_sha256':hashlib.sha256((C/'WORKLOAD.json').read_bytes()).hexdigest(),
       'request_signatures_sha256':digest(g['request_signatures']),'model_profile_sha256':hashlib.sha256((C/'MODEL_PROFILE.json').read_bytes()).hexdigest(),
       'published_candidate_hashes':suite['candidate_hashes'],'resources':resources,'GPU_UUID':common['device']['actual_uuid'],
       'predictor_asset_hashes':{k:profile['external_files'][profile[k]]['sha256']for k in ['qrf_model','qrf_vectorizer']},
       'common_runtime_hashes':p['common_runtime_hashes'],'horizon_seconds':p['observation_horizon_seconds'],'metrics':g['metrics']})
if len(rows)==2 and rows[0]['common_runtime_hashes']!=rows[1]['common_runtime_hashes']:
    pi=next(i for i,r in enumerate(rows)if r['information_mode']=='predicted')
    oi=next(i for i,r in enumerate(rows)if r['information_mode']=='oracle')
    P=case_paths[pi];O=case_paths[oi];repair=read(O.parents[1]/'ADAPTER_ORDER_REPAIR.json')
    assert repair['gate']=='PASS'and repair['repair_generation']==2
    assert repair['candidate_28_files_unchanged']and repair['length_information_scope_unchanged']and repair['ordinary_disabled_path_unchanged']
    assert any(m['continuation_case']==str(O)and m['ordinary_counterpart']==str(P)for m in repair['cases'])
    key='common_runtime/oracle_length_adapter.py';proof=verify_source_delta((P/key).read_text(),(O/key).read_text())
    assert all(proof[k]==repair[k]for k in proof)
    verify_validator_delta((P/'programs/followup_checks.py').read_text(),(O/'programs/followup_checks.py').read_text())
    for name in ['client.py','pure_metrics.py','offline_compare.py']:
        assert hashlib.sha256((P/'programs'/name).read_bytes()).hexdigest()==hashlib.sha256((O/'programs'/name).read_bytes()).hexdigest(),'Metric/client implementation changed'
    rows[oi]['actual_common_runtime_hashes']=dict(rows[oi]['common_runtime_hashes'])
    rows[oi]['common_runtime_hashes']=normalize_runtime_hashes(rows[pi]['common_runtime_hashes'],rows[oi]['common_runtime_hashes'],proof)
    order_compatibility.append({'gate':'PASS','repair_generation':2,'proof':proof,
        'source_delta_exactly_declared':True,'ordinary_disabled_path_unchanged':True,
        'offline_lifecycle_validator_only_strengthened':True,'metric_client_programs_identical':True})
names={r['method']for r in rows}
checks={'declared_comparison':(len(rows)==3 and names=={'v47pro3','A','Astar'}and all(r['information_mode']=='predicted'for r in rows))or(len(rows)==2 and names=={'v47pro3','v47pro3-Oracle'}and{r['information_mode']for r in rows}=={'predicted','oracle'})}
for key in ['workload_sha256','request_signatures_sha256','model_profile_sha256','published_candidate_hashes','resources','GPU_UUID','predictor_asset_hashes','common_runtime_hashes','horizon_seconds']:
    checks[('same_common_runtime_after_declared_order_repair'if key=='common_runtime_hashes'and order_compatibility else'same_'+key)]=all(r[key]==rows[0][key]for r in rows)
result={'utc':datetime.now(timezone.utc).isoformat(),'gate':'PASS'if all(checks.values())else'FAIL','GPU_used':False,'checks':checks,'cases':rows,'single_run_not_statistical_significance':True,'declared_order_repair':order_compatibility}
print(json.dumps(result,ensure_ascii=False));raise SystemExit(0 if result['gate']=='PASS'else 1)
