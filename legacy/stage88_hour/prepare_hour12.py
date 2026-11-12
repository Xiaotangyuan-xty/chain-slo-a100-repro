"""Prepare twelve GPU1 one-hour cutoff cases; CPU qualification only."""
from pathlib import Path
import ast,copy,hashlib,json,os,shutil,socket,subprocess,sys,traceback
os.sched_setaffinity(0,{28,30,84,86});assert os.environ.get('CUDA_VISIBLE_DEVICES','')==''
packet=json.load(sys.stdin)
R=Path('/mnt/sda1/xuetianyou-a40/agent-dispatch-experiments/idea1_continuity/idea3_full_jitserve_compare_20261027T121314Z_v1')
S=R/packet['study_name'];DONOR=R/'stage81_llama8_hour_warmupManifestFix_gpu0_after_stage81_20261111_v2'
refs=packet['references'];PREV=Path(refs['qwen14']['source']).parents[1]
assert not S.exists(),'Fresh preparation required'
S.mkdir();(S/'common').mkdir();(S/'cases').mkdir()
try:
 shutil.copytree(DONOR/'common/programs',S/'common/programs',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
 for n,text in packet['sources'].items():(S/'common/programs'/n).write_text(text)
 sys.path.insert(0,str(S/'common/programs'))
 from bundle_runtime import R,L,read,dump,sha,prepare_case,freeze_case
 from workload_design import freeze_work
 from rate_contract import verify as verify_contract
 assert sha(PREV/'CPU_QUALIFICATION.json')==refs['predecessor_qualification_sha256']and read(PREV/'FINAL_READY.json')['gate']=='PASS'
 prep=read(R/'PREPARE.json');tests=[];specs=[];logs=S/'common/CPU_QUALIFICATION';logs.mkdir()
 profiles={};bases={};assets={}
 for key in ['llama8','qwen14']:
  C=Path(refs[key]['source']);bases[key]=read(C/'WORKLOAD.json');m=copy.deepcopy(refs[key]['profile'])
  assert sha(C/'WORKLOAD.json')==refs[key]['workload_sha256']
  m['resources'].update(num_gpu_blocks_override=None,gpu_memory_utilization=.85)
  m['expected_resource_caps'].pop('gpu_blocks',None);m['gpu_KV_bytes']=None
  m['resource_binding']={'GPU':1,'mode':'native_auto_KV_without_block_override','gpu_memory_utilization':.85,'CPU_swap_GiB':1.,'actual_GPU_blocks_recorded_per_run':True,'profile_frozen_before_GPU':True}
  profiles[key]=m;asset=copy.deepcopy(refs['assets'][key]);assert asset['gate']=='PASS'and asset['model_path']==m['model_path']
  for name,v in m['external_files'].items():
   f=Path(name);reg=asset['files'][name];st=f.stat();assert reg['sha256']==v['sha256']and reg['bytes']==v['bytes']==st.st_size
   assert reg['stat']=={k:getattr(st,k)for k in ['st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns']}
  dump(S/'common'/('ASSET_VERIFICATION_'+key+'.json'),asset);assets[key]=S/'common'/('ASSET_VERIFICATION_'+key+'.json')
  dump(S/'common'/('MODEL_DEPLOYMENT_PROFILE_'+key+'.json'),m)
 shutil.copy2(assets['llama8'],S/'common/ASSET_VERIFICATION.json');dump(S/'common/PARENT_WORKLOAD.json',bases['llama8'])
 dump(S/'AUTHORIZATION.json',{'utc':L.utc(),'user_instruction':packet['user_instruction'],'GPU_allowed':[1],'scope':'12 cases: v47pro3/A/vLLM-FCFS, Llama8/Qwen14, 0.1/0.2 roots/s, exactly3600s each, 360/720 roots, cancel at cutoff without drain. Continue after gate failure once terminal cleanup is safe. GPU0 recovery preserved; no GPU2/GitHub/push/training.'})
 dump(S/'PLAN.json',{'kind':'crossmodel_fixed_hour_cutoff','GPU':1,'after_study':str(PREV),'predecessor_CPU_qualification_sha256':refs['predecessor_qualification_sha256'],'models':['llama8','qwen14'],'methods':['v47pro3','A','vLLM-FCFS'],'rates':[.1,.2],'case_count':12,'duration_seconds':3600.,'root_counts':{'0.1':360,'0.2':720},'arrival_seed':202611118401,'template_pool':200,'template_reuse_not_new_dataset':True,'cutoff_rule':'Exactly3600s; half-open[MAIN,MAIN+3600); cancel and clean; no drain','automatic_KV':{'num_gpu_blocks_override':None,'gpu_memory_utilization':.85,'swap_space_GiB':1.,'record_actual_blocks':True},'order':'llama8 then qwen14; rate0.1 then0.2; v47pro3,A,vLLM-FCFS','algorithm_frozen_commit':'f8c5d84048536861a017adaa53648b6b753487e6','no_model_or_predictor_training':True,'no_SLO_normalization':True,'continue_after_final_gate_FAILURE':True,'no_automatic_GPU_retry_within_case':True,'total_MAIN_seconds':43200.})
 workload_receipts={}
 for key in ['llama8','qwen14']:
  for rate in [.1,.2]:
   work=freeze_work(bases[key],list(range(200)),horizon=3600.,rate=rate,seed=202611118401,purpose='fixed_hour_cutoff_no_drain')
   N=int(3600*rate);assert len(work['main'])==N and len({j['collection_id']for j in work['main']})==N
   work['study_binding'].update(stop_policy='cancel_at3600_no_drain',right_censoring=True,template_reuse_not_new_dataset=True)
   for j in work['main']:
    source=bases[key]['main'][j['source']['template_root_index']];assert j['stages']==source['stages']and j['received_slo']==source['received_slo']
   workload_receipts[f'{key}_r{rate}']={'N':N,'requests':sum(len(s)for j in work['main']for s in j['stages']),'target_output_tokens':sum(r['target_output_tokens']for j in work['main']for s in j['stages']for r in s),'first_arrival':work['main'][0]['arrival_offset_seconds'],'last_arrival':work['main'][-1]['arrival_offset_seconds'],'sha256':hashlib.sha256(json.dumps(work,sort_keys=True).encode()).hexdigest()}
   for method in ['v47pro','A','native_vllm']:
    label='v47pro3'if method=='v47pro'else'vLLM_FCFS'if method=='native_vllm'else'A';number=len(specs)+1
    name=f'{number:02d}_{key}_hour_r{str(rate).replace(".","p")}_{label}'
    spec=prepare_case(S,name,work,method=method,gpu=1,rate=rate,horizon=3600.,purpose='fixed_hour_cutoff_no_drain')
    C=Path(spec['stage']);m=profiles[key];dump(C/'MODEL_PROFILE.json',m)
    for n in ['controller.py','window_client.py','window_server.py','cutoff_observation.py','window_metrics.py','resource_sampler.py','cutoff_statistics.py','scheduler_cpu.py','saturation_checks.py','native_dispatch.py','install_suite_runtime.py','abc_observation.py','rate_contract.py','resource_contract_validation.py']:
     shutil.copy2(S/'common/programs'/n,C/'programs'/n)
    shutil.copy2(S/'common/programs/window_gate.py',C/'programs/offline_compare.py')
    p=read(C/'PROTOCOL.json');port=33400+number*2;N=int(3600*rate)
    p.update(study_mode='stage87_crossmodel_cutoff_v1',model_key=key,model_path=m['model_path'],model_profile_sha256=sha(C/'MODEL_PROFILE.json'),expected_resource_caps=m['expected_resource_caps'],cutoff_seconds=3600.,root_count=N,expected_main_requests=workload_receipts[f'{key}_r{rate}']['requests'],expected_target_output_tokens=workload_receipts[f'{key}_r{rate}']['target_output_tokens'],hour_stop_policy='cancel_at_cutoff_no_drain',http_ports={spec['arm']:port},prediction_ports={spec['arm']:port+1},http_request_timeout_seconds=5400.,minimum_free_memory_MiB_before_load=44000,asset_receipt=str(assets[key]),asset_receipt_sha256=sha(assets[key]),fixed_workload_source=str(Path(refs[key]['source'])/'WORKLOAD.json'),fixed_workload_source_sha256=refs[key]['workload_sha256'],arrival_source=str(Path(refs[key]['source'])/'WORKLOAD.json'),native_backend_sha256={str(Path(prep['repo'])/n):sha(Path(prep['repo'])/n)for n in ['third_party/vllm/vllm/core/scheduler.py','third_party/vllm/vllm/engine/llm_engine.py','jitserve/scheduler/policy.py']},arrival_plan=f'ConditionalPoisson N={N} over3600s; seed202611118401; shuffled full template cycles; unique instance IDs; no new-topic claim',arrival_condition={'law':'conditional_Poisson','rate_chains_per_second':rate,'N':N,'T':3600.,'seed':202611118401},comparability='Within model/rate, three methods share workload bytes, prompts, SLO, targets, arrivals, automatic-KV and observers; exactly one hour; no drain.')
    p['resources'].update(m['resources']);p['resources'].update(model=m['model_path'],physical_gpu_index=1,gpu_uuid=L.UUIDS[1])
    p['generation'].update(whole_chain_rule='Credit only for whole chains completed and SLO-attained before3600s cutoff; original80–480seconds unchanged',arrival_rate=rate)
    dump(C/'PROTOCOL.json',p)
    auth=read(C/'DEVICE_AUTHORIZATION.json');auth.update(max_attempt_wall_seconds=7200.,http_request_timeout_seconds=5400.);dump(C/'DEVICE_AUTHORIZATION.json',auth)
    spec.update(gpu_blocks=None,KV_GiB=None,model_key=key,display_method='vLLM-FCFS'if method=='native_vllm'else label,automatic_KV=True,root_count=N)
    dump(C/'CASE_SPEC.json',spec);verify_contract(C)
    for port_number in[port,port+1]:
     with socket.socket()as sock:sock.bind(('127.0.0.1',port_number))
    specs.append(spec)
 dump(S/'MATRIX.json',{'schema':'stage88-crossmodel-fixed-hour/v1','GPU':1,'cases':specs})
 dump(S/'WORKLOAD_FREEZE.json',{'utc':L.utc(),'seed':202611118401,'T':3600.,'rates':[.1,.2],'source_templates':200,'not_independent_new_topics':True,'SLO_and_stage_payloads_unchanged':True,'cases':workload_receipts})
 def env(C):
  e=L.env();e.update(CUDA_VISIBLE_DEVICES='',PYTHONDONTWRITEBYTECODE='1',TOKENIZERS_PARALLELISM='false',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
  e['PYTHONPATH']=os.pathsep.join([str(C/'programs'),str(C/'candidate_source/programs'),str(C/'common_runtime'),str(C/'runtime_repo'),str(S/'common/programs'),prep['repo'],str(Path(prep['repo'])/'third_party/vllm'),prep['sklearn_deps'],prep['support_deps']]);return e
 def run(C,name,code,args):
  prefix=logs/(C.name+'_'+name)
  with prefix.with_suffix('.stdout').open('x')as out,prefix.with_suffix('.stderr').open('x')as err:process=subprocess.run([L.PYTHON,'-c',code,*args],cwd=R/'runtime',env=env(C),stdout=out,stderr=err,timeout=600)
  assert process.returncode==0,(name,prefix.with_suffix('.stderr').read_text()[-6000:])
  rows=[json.loads(l)for l in prefix.with_suffix('.stdout').read_text().splitlines()if l.startswith('{')];assert rows and rows[-1]['gate']=='PASS'
  row={'name':C.name+'_'+name,'gate':'PASS','GPU_used':False,'result':rows[-1],'script_sha256':hashlib.sha256(code.encode()).hexdigest(),'stdout_sha256':sha(prefix.with_suffix('.stdout')),'stderr_sha256':sha(prefix.with_suffix('.stderr'))}
  tests.append(row);dump(prefix.with_suffix('.json'),row);print(json.dumps({'name':row['name'],'gate':'PASS'}),flush=True)
 first=Path(specs[0]['stage'])
 import_test="""from pathlib import Path
import json,runpy,sys
S=Path(sys.argv[1]);sys.path.insert(0,str(S/'common/programs'))
runner=runpy.run_path(str(S/'common/programs/workflow.py'),run_name='qualified_runner_import_without_GPU')
assert callable(runner['main'])and len(json.loads((S/'MATRIX.json').read_text())['cases'])==12
import torch
assert not torch.cuda.is_initialized()
print(json.dumps({'gate':'PASS','GPU_used':False}))"""
 run(first,'ACTUAL_RUNNER_IMPORT_DEPENDENCIES',import_test,[str(S)])
 token_test=r'''from pathlib import Path
import hashlib,json,sys
from transformers import AutoTokenizer
C=Path(sys.argv[1]);m=json.loads((C/'MODEL_PROFILE.json').read_text());w=json.loads((C/'WORKLOAD.json').read_text());t=AutoTokenizer.from_pretrained(m['model_path'],local_files_only=True,trust_remote_code=False);n=0
for ph in['warmup','main']:
 for j in w[ph]:
  for stage in j['stages']:
   for r in stage:
    ids=t(r['prompt'],add_special_tokens=True).input_ids;assert len(ids)==r['prompt_tokens']and hashlib.sha256(json.dumps(ids).encode()).hexdigest()==r['prompt_token_ids_sha256'];n+=1
import torch
assert not torch.cuda.is_initialized()
print(json.dumps({'gate':'PASS','exact_model_tokenizer_prompts_checked':n,'GPU_used':False}))'''
 predictor_test=r'''from pathlib import Path
import json,sys,numpy as np
from jitserve.request_analyzer import prediction
C=Path(sys.argv[1]);m=json.loads((C/'MODEL_PROFILE.json').read_text());w=json.loads((C/'WORKLOAD.json').read_text());model,vec=prediction.load_model(m['qrf_model'],m['qrf_vectorizer']);v=prediction.predict(vec,model,[w['warmup'][0]['stages'][0][0]['prompt']]);assert np.isfinite(np.asarray(v,dtype=float)).all()
import torch
assert not torch.cuda.is_initialized()
print(json.dumps({'gate':'PASS','real_QRF_forward':True,'GPU_used':False}))'''
 for key in['llama8','qwen14']:
  items=[s for s in specs if s['model_key']==key];first_model=Path(items[0]['stage'])
  run(first_model,'MODEL_TOKENIZER_ALL_PROMPTS',token_test,[str(first_model)]);run(first_model,'OFFICIAL_QRF_FORWARD',predictor_test,[str(first_model)])
  for method in['v47pro','A','native_vllm']:
   C=Path(next(s for s in items if s['version']==method)['stage']);code=packet['test_followup_contracts']if method!='native_vllm'else packet['sources']['test_saturation_cpu.py']
   run(C,'ACTUAL_POLICY_INSTALL',code,[str(C),'stage88_install'if method!='native_vllm'else'native'])
 for mode in['accounting','guard','transport']:run(first,'WINDOW_'+mode.upper(),packet['sources']['test_window_cpu.py'],[str(first),mode])
 run(first,'CONTRACT_AND_NATIVE_WARMUP_NEGATIVES',packet['sources']['test_contract_cpu.py'],[str(S)])
 run(first,'CLEANUP_RACE_AND_INDEPENDENT_CASE_CONTINUATION',packet['sources']['test_cleanup_recovery.py'],[str(S)])
 for spec in specs:
  freeze_case(S,spec,tests);assert not list((Path(spec['stage'])/'attempts').iterdir())
 dump(S/'MATRIX.json',{'schema':'stage88-crossmodel-fixed-hour/v1','GPU':1,'cases':specs})
 files={str(f.relative_to(S)):sha(f)for f in(S/'common/programs').glob('*.py')}
 files.update({n:sha(S/n)for n in['PLAN.json','MATRIX.json','AUTHORIZATION.json','WORKLOAD_FREEZE.json','common/PARENT_WORKLOAD.json','common/ASSET_VERIFICATION.json','common/ASSET_VERIFICATION_llama8.json','common/ASSET_VERIFICATION_qwen14.json','common/MODEL_DEPLOYMENT_PROFILE_llama8.json','common/MODEL_DEPLOYMENT_PROFILE_qwen14.json']})
 q={'gate':'PASS','utc':L.utc(),'GPU_used':False,'GPU_allowed':[1],'tests':tests,'actual_controller_entry_cases':12,'workflow_files':files,'case_qualifications':{s['name']:s['qualification_sha256']for s in specs},'published28_candidate_files_unchanged':True,'no_GPU_started':True}
 dump(S/'CPU_QUALIFICATION.json',q);dump(S/'STUDY_STATUS.json',{'state':'PREPARED','phase':'CPU_QUALIFIED_WAIT_LAUNCH','active_case':None,'completed':[],'failed':[],'terminal':[],'results':[]})
 print(json.dumps({'gate':'PASS','study':str(S),'CPU_qualification_sha256':sha(S/'CPU_QUALIFICATION.json'),'CPU_test_groups':len(tests),'actual_controller_entry_cases':12,'cases':specs,'workload_freeze':read(S/'WORKLOAD_FREEZE.json'),'no_GPU_started':True}),flush=True)
except BaseException as exc:
 (S/'PREPARATION_FAILURE.json').write_text(json.dumps({'error':str(exc),'traceback':traceback.format_exc(),'GPU_used':False},indent=2)+'\n');raise
