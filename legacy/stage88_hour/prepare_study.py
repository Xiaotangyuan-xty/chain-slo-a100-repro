"""Prepare the authorized 78-case GPU0 matrix; CPU qualification, never GPU pre-runs."""
from pathlib import Path
import ast,copy,hashlib,json,os,shutil,socket,subprocess,sys,traceback
os.sched_setaffinity(0,{28,30,84,86});assert os.environ.get('CUDA_VISIBLE_DEVICES','')==''
packet=json.load(sys.stdin)
R=Path('/mnt/sda1/xuetianyou-a40/agent-dispatch-experiments/idea1_continuity/idea3_full_jitserve_compare_20261027T121314Z_v1')
S=R/packet['study_name'];DONOR=R/'stage81_llama8_hour_warmupManifestFix_gpu0_after_stage81_20261111_v2'
refs=packet['references'];PREV=Path(refs['qwen14']['source']).parents[1]
assert not S.exists(),'Inspect existing CPU preparation or launch; do not overwrite'
S.mkdir();(S/'common').mkdir();(S/'cases').mkdir()
try:
 shutil.copytree(DONOR/'common/programs',S/'common/programs',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
 for n,text in packet['sources'].items():(S/'common/programs'/n).write_text(text)
 sys.path.insert(0,str(S/'common/programs'))
 from bundle_runtime import R,L,read,dump,sha,prepare_case,freeze_case
 from rate_contract import RATES,verify as verify_contract
 assert sha(PREV/'CPU_QUALIFICATION.json')==refs['predecessor_qualification_sha256']
 assert read(PREV/'FINAL_READY.json')['gate']=='PASS'
 prep=read(R/'PREPARE.json');tests=[];specs=[];logs=S/'common/CPU_QUALIFICATION';logs.mkdir()
 profiles={};bases={};assets={}
 for key in ['llama8','qwen14']:
  C=Path(refs[key]['source']);bases[key]=read(C/'WORKLOAD.json');m=copy.deepcopy(refs[key]['profile'])
  assert sha(C/'WORKLOAD.json')==refs[key]['workload_sha256']
  m['resources'].update(num_gpu_blocks_override=None,gpu_memory_utilization=.85)
  m['expected_resource_caps'].pop('gpu_blocks',None);m['gpu_KV_bytes']=None
  m['resource_binding']={'GPU':0,'mode':'native_auto_KV_without_block_override','gpu_memory_utilization':.85,'CPU_swap_GiB':1.,'actual_GPU_blocks_recorded_per_run':True,'profile_frozen_before_GPU':True}
  profiles[key]=m;asset=copy.deepcopy(refs['assets'][key]);assert asset['gate']=='PASS'and asset['model_path']==m['model_path']
  for name,v in m['external_files'].items():
   f=Path(name);reg=asset['files'][name];st=f.stat();assert reg['sha256']==v['sha256']and reg['bytes']==v['bytes']==st.st_size
   assert reg['stat']=={k:getattr(st,k)for k in ['st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns']},('Asset changed',name)
  dump(S/'common'/('ASSET_VERIFICATION_'+key+'.json'),asset);assets[key]=S/'common'/('ASSET_VERIFICATION_'+key+'.json')
  dump(S/'common'/('MODEL_DEPLOYMENT_PROFILE_'+key+'.json'),m)
 # The default file is retained solely for the inherited case builder; protocols bind per-model receipts.
 shutil.copy2(assets['llama8'],S/'common/ASSET_VERIFICATION.json');dump(S/'common/PARENT_WORKLOAD.json',bases['llama8'])
 for ph in ['warmup','main']:
  for a,b in zip(bases['llama8'][ph],bases['qwen14'][ph]):
   assert a['collection_id']==b['collection_id']and a['received_slo']==b['received_slo']and len(a['stages'])==len(b['stages'])
   for sa,sb in zip(a['stages'],b['stages']):
    assert len(sa)==len(sb)
    for ra,rb in zip(sa,sb):assert {k:v for k,v in ra.items()if k not in ['prompt_tokens','prompt_token_ids_sha256']}=={k:v for k,v in rb.items()if k not in ['prompt_tokens','prompt_token_ids_sha256']}
 dump(S/'AUTHORIZATION.json',{'utc':L.utc(),'user_instruction':packet['user_instruction'],'latest_rate_steering':packet['rate_instruction'],'GPU_allowed':[0],'scope':'78 cases: 200 fixed chains, 3 methods, 2 models, 13 explicit rates; no KV block override; cutoff at200/rate, no drain. GPU1 existing queue untouched. No GPU2/GitHub/push/training.'})
 dump(S/'PLAN.json',{'kind':'crossmodel_200chain_rate_cutoff','GPU':0,'after_study':str(PREV),'predecessor_CPU_qualification_sha256':refs['predecessor_qualification_sha256'],'models':['llama8','qwen14'],'methods':['v47pro3','A','vLLM-FCFS'],'rates':RATES,'case_count':78,'root_count':200,'requests':1197,'target_output_tokens':504695,'SLO_seconds_min_max':[80,480],'cutoff_rule':'H=200/rate; half-open[MAIN,MAIN+H); cancel/clean without drain','arrival_shape':'Same Stage82 conditional-Poisson200 relative arrival array scaled by0.4/rate; seed2026111082','automatic_KV':{'num_gpu_blocks_override':None,'gpu_memory_utilization':.85,'swap_space_GiB':1.,'record_actual_blocks':True},'order':'model llama8 then qwen14; rates ascending; method order rotates by model-rate index before execution','algorithm_frozen_commit':'f8c5d84048536861a017adaa53648b6b753487e6','no_model_or_predictor_training':True,'no_SLO_normalization':True,'no_automatic_GPU_retry':True,'primary_metrics':['window actual-text SLO credit/H','actual emitted output tokens/H','completed and SLO-attained chains','definite misses and right-censored roots'],'official_14B_predictor':'officialQwen7QRF','total_MAIN_seconds':sum(200/r for r in RATES)*6})
 recovery=packet.get('recovery')
 if recovery:
  auth=read(S/'AUTHORIZATION.json');auth.update(latest_recovery_instruction=recovery['user_instruction'],continue_after_gate_failure=True,continue_only_after_terminal_cleanup=True);dump(S/'AUTHORIZATION.json',auth)
  plan=read(S/'PLAN.json');plan.update(recovery_from_study=str(R/recovery['from_study']),reuse_existing_PASS=True,continue_after_final_gate_FAILURE=True,independent_cases_do_not_inherit_validation_failure=True);dump(S/'PLAN.json',plan)
 arrival_source=Path(refs['llama8']['source'])/'WORKLOAD.json'
 dump(S/'WORKLOAD_FREEZE.json',{'models':{k:{'source':refs[k]['source'],'sha256':refs[k]['workload_sha256'],'model_profile_sha256':sha(S/'common'/('MODEL_DEPLOYMENT_PROFILE_'+k+'.json'))}for k in profiles},'same_prompt_strings_SLO_targets_and_stage_structure_across_models':True,'only_tokenizer_metadata_model_specific':True,'common_arrival_source':str(arrival_source),'arrival_source_sha256':sha(arrival_source),'rates':RATES,'roots':200,'calls':1197,'output_targets':504695})
 def env(C):
  e=L.env();e.update(CUDA_VISIBLE_DEVICES='',PYTHONDONTWRITEBYTECODE='1',TOKENIZERS_PARALLELISM='false',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
  e['PYTHONPATH']=os.pathsep.join([str(C/'programs'),str(C/'candidate_source/programs'),str(C/'common_runtime'),str(C/'runtime_repo'),str(S/'common/programs'),prep['repo'],str(Path(prep['repo'])/'third_party/vllm'),prep['sklearn_deps'],prep['support_deps']]);return e
 def run(C,name,code,args):
  prefix=logs/(C.name+'_'+name)
  with prefix.with_suffix('.stdout').open('x')as out,prefix.with_suffix('.stderr').open('x')as err:
   process=subprocess.run([L.PYTHON,'-c',code,*args],cwd=R/'runtime',env=env(C),stdout=out,stderr=err,timeout=600)
  assert process.returncode==0,(name,prefix.with_suffix('.stderr').read_text()[-6000:])
  rows=[json.loads(l)for l in prefix.with_suffix('.stdout').read_text().splitlines()if l.startswith('{')];assert rows and rows[-1]['gate']=='PASS'
  row={'name':C.name+'_'+name,'gate':'PASS','GPU_used':False,'result':rows[-1],'script_sha256':hashlib.sha256(code.encode()).hexdigest(),'stdout_sha256':sha(prefix.with_suffix('.stdout')),'stderr_sha256':sha(prefix.with_suffix('.stderr'))}
  tests.append(row);dump(prefix.with_suffix('.json'),row);print(json.dumps({'name':row['name'],'gate':'PASS'}),flush=True)
 repo=Path(prep['repo']);backend={str(repo/n):sha(repo/n)for n in ['third_party/vllm/vllm/core/scheduler.py','third_party/vllm/vllm/engine/llm_engine.py','jitserve/scheduler/policy.py']}
 for model_index,key in enumerate(['llama8','qwen14']):
  for rate_index,rate in enumerate(RATES):
   H=200/rate;work=copy.deepcopy(bases[key])
   for j,ref in zip(work['main'],bases['llama8']['main']):j['arrival_offset_seconds']=ref['arrival_offset_seconds']*.4/rate
   methods=['v47pro','A','native_vllm'];rotate=(model_index+rate_index)%3;methods=methods[rotate:]+methods[:rotate]
   for method in methods:
    label='v47pro3'if method=='v47pro'else'vLLM_FCFS'if method=='native_vllm'else'A'
    number=len(specs)+1;name=f'{number:02d}_{key}_r{str(rate).replace(".","p")}_{label}'
    spec=prepare_case(S,name,work,method=method,gpu=0,rate=rate,horizon=H,purpose='200chain_rate_cutoff_no_drain')
    C=Path(spec['stage']);m=profiles[key];dump(C/'MODEL_PROFILE.json',m)
    for n in ['controller.py','window_client.py','window_server.py','cutoff_observation.py','window_metrics.py','resource_sampler.py','cutoff_statistics.py','scheduler_cpu.py','saturation_checks.py','native_dispatch.py','install_suite_runtime.py','abc_observation.py','rate_contract.py','resource_contract_validation.py']:
     shutil.copy2(S/'common/programs'/n,C/'programs'/n)
    shutil.copy2(S/'common/programs/window_gate.py',C/'programs/offline_compare.py')
    p=read(C/'PROTOCOL.json');port=32400+number*2
    p.update(study_mode='stage87_crossmodel_cutoff_v1',model_key=key,model_path=m['model_path'],model_profile_sha256=sha(C/'MODEL_PROFILE.json'),expected_resource_caps=m['expected_resource_caps'],cutoff_seconds=H,hour_stop_policy='cancel_at_cutoff_no_drain',http_ports={spec['arm']:port},prediction_ports={spec['arm']:port+1},http_request_timeout_seconds=H+1800.,minimum_free_memory_MiB_before_load=44000,asset_receipt=str(assets[key]),asset_receipt_sha256=sha(assets[key]),fixed_workload_source=str(Path(refs[key]['source'])/'WORKLOAD.json'),fixed_workload_source_sha256=refs[key]['workload_sha256'],arrival_source=str(arrival_source),native_backend_sha256=backend,arrival_plan='All200 original chains; same frozen conditional-Poisson relative array, scaled by0.4/rate and strictly before H=200/rate',arrival_condition={'law':'conditional_Poisson','source_seed':2026111082,'rate_chains_per_second':rate,'N':200,'T':H},comparability='Three methods share exact per-model/rate workload bytes, prompts, SLO, targets, automatic-KV settings and common observers; full replay is not measured; actual capacities must match within each group.')
    p['resources'].update(m['resources']);p['resources'].update(model=m['model_path'],physical_gpu_index=0,gpu_uuid=L.UUIDS[0])
    p['generation'].update(whole_chain_rule='Credit only for whole chains completed and SLO-attained before cutoff; original80–480seconds unchanged',arrival_rate=rate)
    dump(C/'PROTOCOL.json',p)
    auth=read(C/'DEVICE_AUTHORIZATION.json');auth.update(max_attempt_wall_seconds=H+3600.,http_request_timeout_seconds=H+1800.);dump(C/'DEVICE_AUTHORIZATION.json',auth)
    spec.update(gpu_blocks=None,KV_GiB=None,model_key=key,display_method='vLLM-FCFS'if method=='native_vllm'else label,automatic_KV=True)
    dump(C/'CASE_SPEC.json',spec);verify_contract(C)
    for port_number in [port,port+1]:
     with socket.socket()as sock:sock.bind(('127.0.0.1',port_number))
    specs.append(spec)
   print(json.dumps({'prepared_model':key,'rate':rate,'window':H,'cases_so_far':len(specs)}),flush=True)
 if recovery:
  oldS=R/recovery['from_study'];oldspec=copy.deepcopy(read(oldS/'MATRIX.json')['cases'][0]);C=Path(oldspec['stage']);A=C/'attempts'/oldspec['attempt']
  gate=read(C/'receipts'/('RUN_GATE_'+oldspec['attempt']+'.json'))
  assert gate['gate']=='PASS'and all(gate['checks'].values())and read(C/'CASE_STATUS.json')['state']=='COMPLETED'
  assert read(A/'controller_receipt.json')['failure']is None
  oldspec.update(reuse_existing_pass=True,recovery_source_study=str(oldS),no_GPU_replay=True)
  specs[0]=oldspec
  dump(S/'RECOVERY_REUSE.json',{'gate':'PASS','source_study':str(oldS),'reused_case':oldspec,'source_gate_sha256':sha(C/'receipts'/('RUN_GATE_'+oldspec['attempt']+'.json')),'original_v3_immutable':True,'failed_case2_not_reused':True})
 dump(S/'MATRIX.json',{'schema':'stage87-crossmodel-rate-cutoff/v1','GPU':0,'cases':specs})
 fresh_first=Path(next(s for s in specs if not s.get('reuse_existing_pass'))['stage'])
 import_test="""from pathlib import Path
import json,runpy,sys
S=Path(sys.argv[1]);sys.path.insert(0,str(S/'common/programs'))
runner=runpy.run_path(str(S/'common/programs/workflow.py'),run_name='qualified_runner_import_without_GPU')
assert callable(runner['main'])and callable(runner['execute'])and callable(runner['owned_alive'])
assert len(json.loads((S/'MATRIX.json').read_text())['cases'])==78
import torch
assert not torch.cuda.is_initialized()
print(json.dumps({'gate':'PASS','actual_runner_imports_and_execution_base_resolve':True,'GPU_used':False}))"""
 run(fresh_first,'ACTUAL_RUNNER_IMPORT_DEPENDENCIES',import_test,[str(S)])
 token_test=r'''from pathlib import Path
import hashlib,json,os,sys
from transformers import AutoTokenizer
C=Path(sys.argv[1]);m=json.loads((C/'MODEL_PROFILE.json').read_text());w=json.loads((C/'WORKLOAD.json').read_text());t=AutoTokenizer.from_pretrained(m['model_path'],local_files_only=True,trust_remote_code=False)
n=0
for ph in ['warmup','main']:
 for j in w[ph]:
  for stage in j['stages']:
   for r in stage:
    ids=t(r['prompt'],add_special_tokens=True).input_ids
    assert len(ids)==r['prompt_tokens']and hashlib.sha256(json.dumps(ids).encode()).hexdigest()==r['prompt_token_ids_sha256'];n+=1
import torch
assert not torch.cuda.is_initialized()
print(json.dumps({'gate':'PASS','exact_model_tokenizer_prompts_checked':n,'GPU_used':False}))'''
 predictor_test=r'''from pathlib import Path
import json,os,sys,numpy as np
from jitserve.request_analyzer import prediction
C=Path(sys.argv[1]);m=json.loads((C/'MODEL_PROFILE.json').read_text());w=json.loads((C/'WORKLOAD.json').read_text());model,vec=prediction.load_model(m['qrf_model'],m['qrf_vectorizer']);v=prediction.predict(vec,model,[w['warmup'][0]['stages'][0][0]['prompt']]);assert np.isfinite(np.asarray(v,dtype=float)).all()
import torch
assert not torch.cuda.is_initialized()
print(json.dumps({'gate':'PASS','real_QRF_forward':True,'training':False,'GPU_used':False}))'''
 for key in ['llama8','qwen14']:
  items=[s for s in specs if s['model_key']==key and not s.get('reuse_existing_pass')];first=Path(items[0]['stage'])
  run(first,'MODEL_TOKENIZER_ALL1204',token_test,[str(first)]);run(first,'OFFICIAL_QRF_FORWARD',predictor_test,[str(first)])
  for method in ['v47pro','A','native_vllm']:
   C=Path(next(s for s in items if s['version']==method)['stage'])
   code=packet['test_followup_contracts']if method!='native_vllm'else packet['sources']['test_saturation_cpu.py']
   run(C,'ACTUAL_POLICY_INSTALL',code,[str(C),'stage87_install'if method!='native_vllm'else'native'])
 first=fresh_first
 for mode in ['accounting','guard','transport']:run(first,'WINDOW_'+mode.upper(),packet['sources']['test_window_cpu.py'],[str(first),mode])
 run(first,'CONTRACT_AND_NATIVE_WARMUP_NEGATIVES',packet['sources']['test_contract_cpu.py'],[str(S)])
 if recovery:run(first,'CLEANUP_RACE_AND_INDEPENDENT_CASE_RECOVERY',packet['sources']['test_cleanup_recovery.py'],[str(S)])
 assert len(specs)==78
 for i,spec in enumerate(specs,1):
  if spec.get('reuse_existing_pass'):
   print(json.dumps({'reused_existing_PASS':i,'case':spec['name'],'GPU_replay':False}),flush=True);continue
  freeze_case(S,spec,tests);assert not list((Path(spec['stage'])/'attempts').iterdir())
  print(json.dumps({'controller_entry_PASS':i,'case':spec['name']}),flush=True)
 dump(S/'MATRIX.json',{'schema':'stage87-crossmodel-rate-cutoff/v1','GPU':0,'cases':specs})
 files={str(f.relative_to(S)):sha(f)for f in(S/'common/programs').glob('*.py')}
 files.update({n:sha(S/n)for n in ['PLAN.json','MATRIX.json','AUTHORIZATION.json','WORKLOAD_FREEZE.json','common/PARENT_WORKLOAD.json','common/ASSET_VERIFICATION.json','common/ASSET_VERIFICATION_llama8.json','common/ASSET_VERIFICATION_qwen14.json','common/MODEL_DEPLOYMENT_PROFILE_llama8.json','common/MODEL_DEPLOYMENT_PROFILE_qwen14.json']})
 if recovery:files['RECOVERY_REUSE.json']=sha(S/'RECOVERY_REUSE.json')
 q={'gate':'PASS','utc':L.utc(),'GPU_used':False,'GPU_allowed':[0],'tests':tests,'actual_controller_entry_cases':78,'workflow_files':files,'case_qualifications':{s['name']:s['qualification_sha256']for s in specs},'published28_candidate_files_unchanged':True,'no_GPU_started':True}
 dump(S/'CPU_QUALIFICATION.json',q);dump(S/'STUDY_STATUS.json',{'state':'PREPARED','phase':'CPU_QUALIFIED_WAIT_LAUNCH','active_case':None,'completed':[],'failed':[],'results':[]})
 print(json.dumps({'gate':'PASS','study':str(S),'CPU_qualification_sha256':sha(S/'CPU_QUALIFICATION.json'),'CPU_test_groups':len(tests),'actual_controller_entry_cases':78,'cases':specs,'no_GPU_started':True}),flush=True)
except BaseException as exc:
 (S/'PREPARATION_FAILURE.json').write_text(json.dumps({'error':str(exc),'traceback':traceback.format_exc(),'GPU_used':False},indent=2)+'\n');raise
