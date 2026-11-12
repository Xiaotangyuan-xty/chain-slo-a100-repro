"""Frozen case builder shared by the prepared hour and oracle workflows."""
from pathlib import Path
import ast, copy, hashlib, json, os, shutil, sys

R=Path('/mnt/sda1/xuetianyou-a40/agent-dispatch-experiments/idea1_continuity/idea3_full_jitserve_compare_20261027T121314Z_v1')
sys.path.insert(0,str(R/'stage29_llama_Astar_v46_normalKV_20261106_v1/common/programs'))
import study_runner as L
PARENT=R/'stage79_v47pro3_A_Astar_llama8_pure200_poisson_azure_KV22p1816_gpu1_20261110_v1/cases/01_poisson_r0p2_v47pro3_gpu1'
COMMIT='f8c5d84048536861a017adaa53648b6b753487e6'


def read(p):return json.loads(Path(p).read_text())
def dump(p,v):L.dump(Path(p),v)
def sha(p):return L.sha(Path(p))


def prepare_case(S,name,work,*,method,gpu,rate,horizon,purpose,information='predicted'):
    from workload_design import oracle_table
    C=S/'cases'/name
    if C.exists():raise FileExistsError('Fresh case required: '+str(C))
    C.mkdir(parents=True)
    parentq=read(PARENT/'receipts/CPU_QUALIFICATION.json')
    assert all(sha(PARENT/n)==h for n,h in parentq['stage_files'].items())
    for folder in ['programs','candidate_source','common_runtime','runtime_repo']:
        shutil.copytree(PARENT/folder,C/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for folder in ['attempts','receipts','cpu_attempts']:(C/folder).mkdir()
    patches=S/'common/programs'
    for n in ['controller.py','offline_compare.py','pure_metrics.py','install_suite_runtime.py','followup_checks.py','resource_contract_validation.py','native_graph_observation.py']:
        shutil.copy2(patches/n,C/'programs'/n)
    for n in ['shared_prediction.py','oracle_length_adapter.py']:
        shutil.copy2(patches/n,C/'common_runtime'/n)
    arm='C'if method=='v47pro'else'A';release='v47pro3'if arm=='C'else method;attempt=name.upper()+'_01'
    m=read(PARENT/'MODEL_PROFILE.json');m.setdefault('resource_binding',{})['GPU']=gpu
    dump(C/'MODEL_PROFILE.json',m);dump(C/'WORKLOAD.json',work)
    for n in ['RELEASE_BINDING.json']:shutil.copy2(PARENT/n,C/n)
    release_binding=read(C/'RELEASE_BINDING.json');release_binding.update(release=release,release_commit=COMMIT if arm=='C'else None);dump(C/'RELEASE_BINDING.json',release_binding)
    suite=read(PARENT/'SUITE_SPEC.json');suite.update(method=method,release=release,candidate_commit=COMMIT if arm=='C'else None,information_mode=information)
    if information=='oracle':
        dump(C/'ORACLE_LENGTHS.json',oracle_table(work));suite['oracle_lengths_sha256']=sha(C/'ORACLE_LENGTHS.json')
    dump(C/'SUITE_SPEC.json',suite)
    assert len(suite['candidate_hashes'])==28 and all(sha(C/'candidate_source'/n)==h for n,h in suite['candidate_hashes'].items())
    requests={f'{ph}:{j["collection_id"]}:{sid}:{r["request_id"]}':{k:r[k]for k in ['prompt_sha256','prompt_token_ids_sha256','prompt_tokens','target_output_tokens']}for ph in ['warmup','main']for j in work[ph]for sid,st in enumerate(j['stages'])for r in st}
    dump(C/'TRACE_MANIFEST.json',{'schema':'followup-frozen-pure/v1','requests':requests,'workload_sha256':sha(C/'WORKLOAD.json')})
    auth={'physical_gpu_index':gpu,'gpu_uuid':L.UUIDS[gpu],'allowed_physical_gpu_indices':[gpu],
          'max_attempt_wall_seconds':28800,'http_request_timeout_seconds':28200,
          'only_registered_processes_may_be_signaled':True,'external_coexistence_allowed':False,
          'user_instruction':read(S/'AUTHORIZATION.json')['user_instruction']}
    dump(C/'DEVICE_AUTHORIZATION.json',auth)
    approval={'authorized':True,'long_experiment_authorized':True,'utc':L.utc(),
              'user_instruction':auth['user_instruction'],'scope':name,'workload_sha256':sha(C/'WORKLOAD.json'),
              'devices':[{'physical_gpu_index':gpu,'gpu_uuid':L.UUIDS[gpu]}]}
    dump(C/'LONG_EXECUTION_APPROVAL.json',approval)
    p=read(PARENT/'PROTOCOL.json');serial=int(name.split('_',1)[0]);port=(27000 if gpu==0 else 28000)+serial*2
    p.update(schema='followup-pure-chain/v1',study_mode='followup_pure_chain_v1',study_scope=purpose,
      role='followup_pure_chain',case=name,case_index=serial,information_mode=information,workload_kind='pure',
      candidate_version=method,release_version=release,release_commit=COMMIT if arm=='C'else None,
      C_version='v47pro_event_wave_service_v1'if arm=='C'else'official',
      mixed_variant='v47pro_v47_reward_event_wave_v1'if arm=='C'else None,
      candidate_source_commit=COMMIT if arm=='C'else None,runtime_arm=arm,
      allowed_arms=[arm],planned_arms=[arm],attempts={arm:attempt},attempt_variants={attempt:'native'},
      arm_devices={arm:{'physical_gpu_index':gpu,'gpu_uuid':L.UUIDS[gpu],'authorization_file':'DEVICE_AUTHORIZATION.json'}},
      forbidden_gpu_indices=[g for g in [0,1,2]if g!=gpu],http_ports={arm:port},prediction_ports={arm:port+1},
      cpu_affinity={arm:L.CPUS[gpu]},parallel=False,external_coexistence_allowed=False,
      observation_horizon_seconds=horizon,expected_arrival_window_seconds=work['main'][-1]['arrival_offset_seconds'],
      target_arrivals=[j['arrival_offset_seconds']for j in work['main']],workload_sha256=sha(C/'WORKLOAD.json'),
      model_profile_sha256=sha(C/'MODEL_PROFILE.json'),expected_resource_caps=m['expected_resource_caps'],
      stage_counts={str(j['collection_id']):len(j['stages'])for ph in ['warmup','main']for j in work[ph]},
      requests_per_stage={str(j['collection_id']):list(map(len,j['stages']))for ph in ['warmup','main']for j in work[ph]},
      long_approval_sha256=sha(C/'LONG_EXECUTION_APPROVAL.json'),
      asset_receipt=str(S/'common/ASSET_VERIFICATION.json'),asset_receipt_sha256=sha(S/'common/ASSET_VERIFICATION.json'),
      full_trace_authorization=auth['user_instruction'],arrival_plan='Frozen conditional Poisson arrivals; no arrivals at or beyond the horizon.',
      comparability='Same per-condition frozen pure-chain payload, SLO, targets, arrivals, model, fixedKV, predictor and original candidate; information mode differs only in the Oracle pair.')
    p['resources'].update(physical_gpu_index=gpu,gpu_uuid=L.UUIDS[gpu]);p['generation'].update(arrival_rate=rate,target_main_arrival_offsets_seconds=p['target_arrivals'])
    p['arrival_condition']={'law':'conditional_Poisson','rate_chains_per_second':rate}
    p['common_runtime_hashes']={str(f.relative_to(C)):sha(f)for f in(C/'common_runtime').glob('*.py')}
    p['lifetime_observation_sha256']=sha(C/'programs/lifetime_observation.py')
    p['baseline_budget_adapter_sha256']=sha(C/'common_runtime/baseline_budget.py')if method=='Astar'else None
    dump(C/'PROTOCOL.json',p)
    spec={'name':name,'stage':str(C),'GPU':gpu,'arm':arm,'attempt':attempt,'version':method,'release':release,
          'display_method':release+'-Oracle'if information=='oracle'else release,'information_mode':information,
          'rate':rate,'horizon_seconds':horizon,'purpose':purpose,'gpu_blocks':11357,'KV_GiB':22.181640625,
          'root_counts':{'dr':len(work['main'])},'main_requests':sum(len(s)for j in work['main']for s in j['stages']),
          'workload_sha256':p['workload_sha256'],'qualification_sha256':'PENDING_CPU_QUALIFICATION'}
    dump(C/'CASE_SPEC.json',spec);dump(C/'CASE_STATUS.json',{'state':'PREPARED_CPU_PENDING','case':spec})
    for folder in ['programs','candidate_source','common_runtime','runtime_repo']:
        for f in(C/folder).rglob('*.py'):ast.parse(f.read_text(),filename=str(f))
    return spec


def freeze_case(S,spec,tests):
    C=Path(spec['stage']);parent=read(PARENT/'receipts/CPU_QUALIFICATION.json')
    files={str(f.relative_to(C)):sha(f)for d in ['programs','candidate_source','common_runtime','runtime_repo']for f in(C/d).rglob('*')if f.is_file()and'__pycache__'not in f.parts}
    files.update({n:sha(C/n)for n in ['PROTOCOL.json','WORKLOAD.json','TRACE_MANIFEST.json','MODEL_PROFILE.json','SUITE_SPEC.json','RELEASE_BINDING.json','DEVICE_AUTHORIZATION.json','LONG_EXECUTION_APPROVAL.json']})
    if(C/'ORACLE_LENGTHS.json').exists():files['ORACLE_LENGTHS.json']=sha(C/'ORACLE_LENGTHS.json')
    base=copy.deepcopy(parent['base_files'])
    base.update({str(f.relative_to(R)):sha(f)for f in(S/'common/programs').glob('*.py')})
    base[str((S/'common/ASSET_VERIFICATION.json').relative_to(R))]=sha(S/'common/ASSET_VERIFICATION.json')
    q={'gate':'PASS','utc':L.utc(),'GPU_used':False,'base_files':base,'stage_files':files,
       'tests':tests,'published_v47pro3_source_exact':True,'actual_controller_entry_check':'PENDING_BEFORE_STUDY_LAUNCH'}
    dump(C/'receipts/CPU_QUALIFICATION.json',q)
    source=(C/'programs/controller.py').read_text();tree=ast.parse(source);main=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='main')
    cut=next(i for i,n in enumerate(main.body)if isinstance(n,ast.Expr)and isinstance(n.value,ast.Call)and isinstance(n.value.func,ast.Attribute)and n.value.func.attr=='mkdir')
    main.body=main.body[:cut]+ast.parse('return (physical, prepare, resources)').body
    ns={'__name__':'actual_controller_entry_CPU_fixture'};exec(compile(ast.fix_missing_locations(tree),str(C/'programs/controller.py'),'exec'),ns)
    argv=sys.argv[:];sys.path.insert(0,str(C/'programs'))
    try:
        sys.argv=['controller.py',str(R),str(C),spec['arm'],spec['attempt'],'full'];physical,bound,res=ns['main']()
        assert physical==spec['GPU']and bound['model']==read(C/'MODEL_PROFILE.json')['model_path']and res['num_gpu_blocks_override']==spec['gpu_blocks']
    finally:sys.argv=argv;sys.path.pop(0)
    assert not list((C/'attempts').iterdir())
    q['actual_controller_entry_check']='PASS';dump(C/'receipts/CPU_QUALIFICATION.json',q)
    spec['qualification_sha256']=sha(C/'receipts/CPU_QUALIFICATION.json');dump(C/'CASE_SPEC.json',spec);dump(C/'CASE_STATUS.json',{'state':'PREPARED','phase':'CPU_QUALIFIED','case':spec})
    return spec
