"""Human-authorized second continuation; fix native parser/prediction ordering only."""
from pathlib import Path
import ast, copy, hashlib, importlib.util, json, os, shutil, socket, subprocess, sys

os.sched_setaffinity(0,{28,30,84,86})
assert os.environ.get('CUDA_VISIBLE_DEVICES','')==''
packet=json.load(sys.stdin)
R=Path('/mnt/sda1/xuetianyou-a40/agent-dispatch-experiments/idea1_continuity/idea3_full_jitserve_compare_20261027T121314Z_v1')
ORIGINAL=R/'stage82_llama8_v47pro3_lengthOracle_pure200_r0p4_r0p8_gpu1_after_stage79_20261110_v1'
OLD=R/'stage82_lengthOracle_ABI1_failedOnly_gpu1_after_stage82_20261111_v1'
S=R/'stage82_lengthOracle_orderFix2_failedOnly_gpu1_20261111_v1'
sys.path.insert(0,str(OLD/'common/programs'))
from bundle_runtime import L,read,dump,sha,prepare_case,freeze_case

assert packet['human_authorization']['authorized_repair_generation']==2
assert not S.exists(),'Existing continuation must be inspected, never overwritten'
oldq=read(OLD/'CPU_QUALIFICATION.json');assert oldq['gate']=='PASS'
assert all(sha(OLD/n)==h for n,h in oldq['workflow_files'].items())
old_matrix=read(OLD/'MATRIX.json')['cases'];assert len(old_matrix)==2
previous_repair=read(OLD/'ADAPTER_ABI_REPAIR.json')
source=(OLD/'common/programs/oracle_length_adapter.py').read_text()
assert source==packet['ABI1_ADAPTER.py']
for spec in old_matrix:
    C=Path(spec['stage']);A=C/'attempts'/spec['attempt'];control=read(A/'controller_receipt.json')
    assert read(C/'CASE_STATUS.json')['state']=='FAILED_PRESERVED' and not(A/'MAIN_START.json').exists()
    assert control['gpu_released']and not control['own_gpu_processes_remaining']
    gate=read(A/'WARMUP_NATIVE_TOT_GATE.json')
    assert {k for k,v in gate['checks'].items()if not v}=={'no_prediction_fallback','prediction_success_covers_requests'}
    assert '_oracle_root_key'in(A/'SHARED_PREDICTION_EVENTS.jsonl').read_text()
assert read(OLD/'STUDY_STATUS.json')['state']=='COMPLETED_WITH_FAILURES'
original_source=(ORIGINAL/'common/programs/oracle_length_adapter.py').read_text()
original_validator=(ORIGINAL/'common/programs/followup_checks.py').read_text()
ns={};exec(packet['adapter_order_contract.py'],ns)
source_proof=ns['verify_source_delta'](original_source,packet['oracle_length_adapter.py'])
ns['verify_validator_delta'](original_validator,packet['followup_checks.py'])

S.mkdir();(S/'common').mkdir();(S/'cases').mkdir()
shutil.copytree(OLD/'common/programs',S/'common/programs',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
for name in ['ASSET_VERIFICATION.json','PARENT_WORKLOAD.json']:
    shutil.copy2(OLD/'common'/name,S/'common'/name)
shutil.copy2(OLD/'PILOT_FORMAL_SPLIT.json',S/'PILOT_FORMAL_SPLIT.json')
for name in ['followup_checks.py','adapter_order_contract.py','test_native_request_order.py']:
    (S/'common/programs'/name).write_text(packet[name])
auth=read(OLD/'AUTHORIZATION.json');auth.update(user_latest_authorization=packet['human_authorization'],
    recovery_scope='Second continuation explicitly requested by human; external parse-before-prediction binding and offline lifecycle validation only; two failed Oracle cases, preserve passed predicted cases and GPU0 queue.')
dump(S/'AUTHORIZATION.json',auth)
plan=read(OLD/'PLAN.json');plan.update(after_study=str(OLD),recovery_generation=2,maximum_repair_generations=2,
    exclude_completed_predicted_cases=True,only_pre_main_failed_oracle_cases=True)
dump(S/'PLAN.json',plan);dump(S/'HUMAN_RECOVERY_AUTHORIZATION.json',packet['human_authorization'])
prep=read(R/'PREPARE.json');tests=[];specs=[];mapping=[]
logs=S/'common/CPU_QUALIFICATION';logs.mkdir()

def env(C):
    e=L.env();e.update(CUDA_VISIBLE_DEVICES='',PYTHONDONTWRITEBYTECODE='1',TOKENIZERS_PARALLELISM='false')
    e['PYTHONPATH']=os.pathsep.join([str(C/'programs'),str(C/'candidate_source/programs'),str(C/'common_runtime'),
        str(C/'runtime_repo'),str(S/'common/programs'),prep['repo'],str(Path(prep['repo'])/'third_party/vllm'),prep['sklearn_deps'],prep['support_deps']])
    return e

def record(name,result):
    assert result['gate']=='PASS'
    row={'name':name,'GPU_used':False,**result};tests.append(row);dump(logs/(name+'.json'),row)
    print(json.dumps({'name':name,'gate':'PASS'}),flush=True)

def run(C,name,script,args):
    prefix=logs/(C.name+'_'+name)
    with prefix.with_suffix('.stdout').open('x')as out,prefix.with_suffix('.stderr').open('x')as err:
        p=subprocess.run([L.PYTHON,'-c',script,*args],env=env(C),cwd=R/'runtime',stdout=out,stderr=err,timeout=480)
    assert p.returncode==0,(name,prefix.with_suffix('.stderr').read_text()[-8000:])
    objects=[json.loads(line)for line in prefix.with_suffix('.stdout').read_text().splitlines()if line.startswith('{')]
    assert objects and objects[-1]['gate']=='PASS'
    record(C.name+'_'+name,{'gate':'PASS','result':objects[-1],
        'script_sha256':hashlib.sha256(script.encode()).hexdigest(),
        'stdout_sha256':sha(prefix.with_suffix('.stdout')),'stderr_sha256':sha(prefix.with_suffix('.stderr'))})

def lifecycle_postcheck(C,mode):
    import importlib.util
    sp=importlib.util.spec_from_file_location('offline_lifecycle_CPU_'+C.name+'_'+mode,C/'programs/followup_checks.py')
    module=importlib.util.module_from_spec(sp);sp.loader.exec_module(module)
    out=C/'cpu_attempts'/('REAL_NATIVE_ORDER_'+mode)
    receipt=read(out/'INFORMATION_ADAPTER.json');events=[json.loads(l)for l in(out/'ORACLE_EVENTS.jsonl').read_text().splitlines()]
    arrivals=read(out/'CPU_RECEIVED_REQUESTS.json')
    calls=[{'phase':key.split(':')[0],'collection_id':int(key.split(':')[1]),
        'client_chain_start_monotonic':stamp}for key,stamp in arrivals.items()]
    work=read(C/'WORKLOAD.json');checks=module.lifecycle_checks(receipt,events,work,calls)
    assert all(checks.values()),checks
    record(C.name+'_LIFECYCLE_'+mode,{'gate':'PASS','checks':checks,
        'CPU_received_JSON_time_used_as_tighter_arrival_lower_bound':True})
    return module,receipt,events,work,calls

original_evidence={}
for index,oldspec in enumerate(old_matrix):
    oldC=Path(oldspec['stage']);A=oldC/'attempts'/oldspec['attempt']
    original_evidence.update({str(f):sha(f)for f in A.iterdir()if f.is_file()})
    name=('02_r0p4_v47pro3_Oracle_ORDER2'if oldspec['rate']==.4 else'03_r0p8_v47pro3_Oracle_ORDER2')
    spec=prepare_case(S,name,read(oldC/'WORKLOAD.json'),method='v47pro',gpu=1,rate=oldspec['rate'],
        horizon=oldspec['horizon_seconds'],purpose='oracle_pair',information='oracle')
    C=Path(spec['stage'])
    assert sha(C/'WORKLOAD.json')==sha(oldC/'WORKLOAD.json')
    assert sha(C/'MODEL_PROFILE.json')==sha(oldC/'MODEL_PROFILE.json')
    assert sha(C/'ORACLE_LENGTHS.json')==sha(oldC/'ORACLE_LENGTHS.json')
    assert read(C/'SUITE_SPEC.json')==read(oldC/'SUITE_SPEC.json')
    if index==0:
        run(C,'ORIGINAL_NATIVE_EARLY_FAILURE',packet['test_native_request_order.py'],[str(C),'original_early_failure'])
    (C/'common_runtime/oracle_length_adapter.py').write_text(packet['oracle_length_adapter.py'])
    protocol=read(C/'PROTOCOL.json');protocol['common_runtime_hashes']['common_runtime/oracle_length_adapter.py']=sha(C/'common_runtime/oracle_length_adapter.py')
    dump(C/'PROTOCOL.json',protocol)
    for mode in ['early','late','overlap']:
        run(C,'REAL_NATIVE_'+mode,packet['test_native_request_order.py'],[str(C),mode])
        result=lifecycle_postcheck(C,mode)
        if index==0 and mode=='early':
            module,receipt,events,work,calls=result
            def reject(name,mutator):
                rr=copy.deepcopy(receipt);ee=copy.deepcopy(events);cc=copy.deepcopy(calls)
                mutator(rr,ee,cc);assert not all(module.lifecycle_checks(rr,ee,work,cc).values()),name
                record(name,{'gate':'PASS','invalid_lifecycle_rejected':True})
            reject('PREDICTION_BEFORE_BINDING_REJECTED',lambda r,e,c:next(x for x in e if x['kind']=='request_bound').__setitem__('monotonic',1e30))
            reject('MISSING_REQUEST_BINDING_REJECTED',lambda r,e,c:e.remove(next(x for x in e if x['kind']=='request_bound')))
            reject('DUPLICATE_BINDING_REJECTED',lambda r,e,c:e.append(copy.deepcopy(next(x for x in e if x['kind']=='request_bound'))))
            reject('ACTIVATION_BEFORE_ACTUAL_ARRIVAL_REJECTED',lambda r,e,c:next(x for x in e if x['kind']=='root_activated').__setitem__('monotonic',0.))
            reject('UNARRIVED_ROOT_REJECTED',lambda r,e,c:next(x for x in e if x['kind']=='request_prediction').__setitem__('root','main:UNARRIVED'))
            reject('MISSING_CLIENT_ARRIVAL_REJECTED',lambda r,e,c:c.pop())
            reject('WRONG_BINDING_COUNT_REJECTED',lambda r,e,c:r['counts'].__setitem__('request_bindings',0))
    run(C,'NATIVE_POLICY_AND_FORECASTER',packet['test_followup_contracts.py'],[str(C),'ORDER2_install'])
    run(C,'EXACT_LENGTH_BOUNDARIES_AND_ZERO_REMAINDER',packet['test_followup_contracts.py'],[str(C),'unit'])
    for port in [protocol['http_ports']['C'],protocol['prediction_ports']['C']]:
        with socket.socket()as sock:sock.bind(('127.0.0.1',port))
    prior=next(v for v in previous_repair['cases']if v['continuation_case']==oldspec['stage'])
    mapping.append({'failed_source_case':oldspec['stage'],'failed_attempt':oldspec['attempt'],
        'original_failed_source_case':prior['failed_source_case'],'ordinary_counterpart':prior['ordinary_counterpart'],
        'continuation_case':str(C),'continuation_attempt':spec['attempt'],
        'workload_sha256':sha(C/'WORKLOAD.json'),'original_failure_retained':True,
        'main_never_started_in_failed_attempt':True})
    specs.append(spec)

# Disabled branch remains byte-for-byte unchanged and must leave parser/provider untouched.
disabled=prepare_case(S,'90_CPU_ORDINARY_DISABLED_ONLY',read(Path(mapping[0]['ordinary_counterpart'])/'WORKLOAD.json'),
    method='v47pro',gpu=1,rate=.4,horizon=500.,purpose='CPU_ONLY_NEVER_LAUNCH',information='predicted')
ordinary=Path(disabled['stage']);(ordinary/'common_runtime/oracle_length_adapter.py').write_text(packet['oracle_length_adapter.py'])
op=read(ordinary/'PROTOCOL.json');op['common_runtime_hashes']['common_runtime/oracle_length_adapter.py']=sha(ordinary/'common_runtime/oracle_length_adapter.py');dump(ordinary/'PROTOCOL.json',op)
ordinary_test=packet['test_followup_contracts.py'].replace('    from install_suite_runtime import install',
    '    original_native_parser=server._build_request_info\n    from install_suite_runtime import install',1).replace("        assert not receipt['information_adapter']['enabled']and not hasattr(server,'_length_oracle_predictor')",
    "        assert not receipt['information_adapter']['enabled']and not hasattr(server,'_length_oracle_predictor')\n        assert server._build_request_info is original_native_parser",1)
run(ordinary,'ORDINARY_PARSER_AND_PURE_PATH_UNCHANGED',ordinary_test,[str(ordinary),'ORDER2_disabled'])
assert all(sha(Path(path))==h for path,h in original_evidence.items()),'Original failed evidence changed'
(S/'common/programs/oracle_length_adapter.py').write_text(packet['oracle_length_adapter.py'])
repair={'schema':'oracle-native-request-order-repair/v1','gate':'PASS','utc':L.utc(),'repair_generation':2,
    **source_proof,'previous_ABI1_adapter_sha256':hashlib.sha256(source.encode()).hexdigest(),
    'human_authorization':packet['human_authorization'],'candidate_28_files_unchanged':True,
    'length_information_scope_unchanged':True,'ordinary_disabled_path_unchanged':True,
    'metric_implementations_unchanged':True,'runtime_delta':'Retain prior seq_group ABI fix; bind only received collective requests at native _build_request_info before prediction starts; record binding order.',
    'offline_validator_delta':'Strengthen binding and actual-client-arrival boundary checks; no metric or SLO gate threshold change.',
    'cases':mapping,'CPU_tests':tests,'original_failed_evidence_hashes':original_evidence,
    'no_GPU_started':True,'on_failure_after_second_repair':'Preserve and notify; no blind third generation'}
dump(S/'ADAPTER_ORDER_REPAIR.json',repair)
for spec in specs+[disabled]:freeze_case(S,spec,tests)
dump(S/'MATRIX.json',{'cases':specs});dump(S/'CPU_ORDINARY_SPECIMEN.json',disabled)
files={str(f.relative_to(S)):sha(f)for f in(S/'common/programs').glob('*.py')}
files.update({n:sha(S/n)for n in ['PLAN.json','MATRIX.json','AUTHORIZATION.json','PILOT_FORMAL_SPLIT.json',
    'common/PARENT_WORKLOAD.json','common/ASSET_VERIFICATION.json','ADAPTER_ORDER_REPAIR.json','HUMAN_RECOVERY_AUTHORIZATION.json']})
q={'gate':'PASS','utc':L.utc(),'GPU_used':False,'GPU_allowed':[1],'tests':tests,'workflow_files':files,
    'case_qualifications':{v['name']:v['qualification_sha256']for v in specs},
    'actual_controller_entry_checked_cases':3,'GPU_execution_cases':2,'CPU_only_disabled_specimen':disabled['name'],
    'all_candidate_files_exact':True,'repair_generation':2,'unchanged_original_scientific_tests':oldq.get('original_tests_reused_unchanged',[])}
dump(S/'CPU_QUALIFICATION.json',q);dump(S/'STUDY_STATUS.json',{'state':'PREPARED','phase':'CPU_QUALIFIED_WAIT_DEPENDENCY',
    'active_case':None,'pending':[v['name']for v in specs]})
dump(S/'QUEUE_ARMED.json',{'utc':L.utc(),'after_study':str(OLD),'CPU_qualification_sha256':sha(S/'CPU_QUALIFICATION.json'),
    'only_failed_Oracle_cases':True,'no_predicted_GPU_repeats':True,'repair_generation':2,'no_GPU_started':True})
print(json.dumps({'gate':'PASS','study':str(S),'qualification_sha256':sha(S/'CPU_QUALIFICATION.json'),
    'CPU_test_groups':len(tests),'actual_controller_entry_cases':3,'GPU_cases':specs,'repair':repair,'GPU_started':False}),flush=True)
