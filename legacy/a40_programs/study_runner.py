"""Authorized sequential CPU qualification, normal-KV profile, Astar-only calibration, paired replay."""
from pathlib import Path
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
import ast,copy,fcntl,hashlib,json,os,shutil,subprocess,sys,time,traceback
from study_math import arrivals,choose,normal_blocks,ports
R=Path('/mnt/sda1/xuetianyou-a40/agent-dispatch-experiments/idea1_continuity/idea3_full_jitserve_compare_20261027T121314Z_v1')
S=R/'stage29_llama_Astar_v46_normalKV_20261106_v1'
B=R/'stage26_model_transfer_cpu_20261106_v1/binding_attempt01/llama8'
PARENT=R/'stage28_pure200_nativeA_v46_goodput_gpu01_20261106_v1/cases/llama8_pure_gpu1_A'
UUIDS=['GPU-ff8c7d5c-f75c-26e1-43de-b40ca283f938','GPU-f5874940-7f3b-ad3e-b810-bc7dda423d1a']
CPUS=[list(range(0,28,2))+list(range(56,84,2)),list(range(1,28,2))+list(range(57,84,2))]
USER='停止现有GPU0/GPU1实验；主指标token goodput，v46评分不变；复用之前Astar预算修正；用Llama-3.1-8B在单卡正常KV下校准到达强度，然后按校准强度比较Astar与v46的200链；可用GPU0和GPU1。'
def read(p):return json.loads(Path(p).read_text())
def sha(p):
 with Path(p).open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def dump(p,d):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n');os.replace(tmp,p)
def utc():return datetime.now(timezone.utc).isoformat()
def env():
 b=read(R/'FREEZE.json');library=read(b['runtime']['library_contract']);e=os.environ.copy()
 for k in b['runtime']['reuse_only']:e[k]=library[k]
 e.update(b['runtime']['new_environment_variables']);e.update(CUDA_VISIBLE_DEVICES='',PYTHONDONTWRITEBYTECODE='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2',TOKENIZERS_PARALLELISM='false')
 return e
PYTHON=read(R/'PREPARE.json')['python']

def verify_assets():
 os.sched_setaffinity(0,{28,30,32,34,84,86,88,90})
 m=read(B/'MODEL_PROFILE.json');files={}
 if(S/'common/ASSET_VERIFICATION.json').exists():
  receipt=read(S/'common/ASSET_VERIFICATION.json');assert receipt['gate']=='PASS'
  for name,spec in m['external_files'].items():
   st=Path(name).stat();record=receipt['files'][name];assert record['sha256']==spec['sha256']and record['bytes']==spec['bytes']
   assert {k:getattr(st,k)for k in ['st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns']}==record['stat']
  print(json.dumps({'phase':'STUDY_ASSET_SHA_RECEIPT_REVALIDATED','files':len(receipt['files'])}),flush=True);return
 for name,spec in m['external_files'].items():
  f=Path(name);st=f.stat();assert st.st_size==spec['bytes'];h=sha(f);assert h==spec['sha256'],name
  files[name]={'sha256':h,'bytes':st.st_size,'stat':{k:getattr(st,k)for k in ['st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns']}}
  print(json.dumps({'phase':'ASSET_SHA_VERIFIED','file':f.name}),flush=True)
 dump(S/'common/ASSET_VERIFICATION.json',{'gate':'PASS','utc':utc(),'model_path':m['model_path'],'files':files,'CUDA_VISIBLE_DEVICES':''})

def build_case(name,version,gpu,role,rate,blocks):
 qualification=read(S/'common/CPU_QUALIFICATION.json')
 for file,h in qualification['harness_files'].items():assert sha(S/'common/programs'/file)==h,file
 for file,h in qualification['published_v46_cpu_bound']['files'].items():assert sha(S/'published_v46'/file)==h,file
 stage=S/'cases'/name;assert not stage.exists()
 for n in ['programs','assets','receipts','attempts']:(stage/n).mkdir(parents=True)
 for f in(S/'common/programs').glob('*.py'):shutil.copyfile(f,stage/'programs'/f.name)
 if version=='v46':
  for f in(S/'published_v46').rglob('*'):
   if not f.is_file():continue
   rel=f.relative_to(S/'published_v46')
   if str(rel).startswith('tools/')or f.name.startswith(('test_','controlled_')):continue
   dest=stage/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,dest)
 model=copy.deepcopy(read(B/'MODEL_PROFILE.json'))
 model['resources'].update(num_gpu_blocks_override=blocks,gpu_memory_utilization=.85)
 model['expected_resource_caps'].pop('gpu_blocks',None)
 if blocks is not None:model['expected_resource_caps']['gpu_blocks']=blocks
 model['gpu_KV_bytes']=None if blocks is None else blocks*model['cache_block_bytes']
 model['resource_binding']={'policy':'profile at85% GPU memory, then90% of available KV blocks rounded down to64-block boundary','source_profile':str(S/'NORMAL_KV_PROFILE.json'),'shared_Astar_v46':True}
 dump(stage/'MODEL_PROFILE.json',model)
 w=copy.deepcopy(read(B/'pure/WORKLOAD.json'));parent_manifest=read(B/'pure/TRACE_MANIFEST.json')
 if role=='profile':
  w['warmup']=[];w['main']=copy.deepcopy(w['main'][:1])
  w['main'][0]['arrival_offset_seconds']=0.
  for rs in w['main'][0]['stages']:
   for req in rs:req['target_output_tokens']=min(32,req['target_output_tokens'])
 else:
  a=arrivals([j['arrival_offset_seconds']for j in w['main']],rate)
  for j,t in zip(w['main'],a):j['arrival_offset_seconds']=t
 w['study_binding']={'study':'Stage29','role':role,'target_root_rate':rate,'arrival_law':'Frozen near-periodic shape from historical seed42 array, time-scaled only; not claimed Poisson or Microsoft','parent_workload_sha256':sha(B/'pure/WORKLOAD.json'),'fixed_output_replay':True}
 dump(stage/'WORKLOAD.json',w)
 manifest={}
 for phase in ['warmup','main']:
  for j in w[phase]:
   for sid,rs in enumerate(j['stages']):
    for req in rs:
     k=f'{phase}:{j["collection_id"]}:{sid}:{req["request_id"]}';manifest[k]={n:req[n]for n in ['prompt_sha256','prompt_token_ids_sha256','prompt_tokens','target_output_tokens']}
     if role!='profile':assert manifest[k]==parent_manifest['requests'][k]
 dump(stage/'TRACE_MANIFEST.json',{'schema':'stage29-frozen-inputs/v1','requests':manifest,'workload_sha256':sha(stage/'WORKLOAD.json')})
 arm='C'if version=='v46'else'A';attempt=name.upper()+'_01'
 slot=len(list(S.glob('cases/*/CASE_SPEC.json')));http_port,prediction_port=ports(slot)
 approval={'authorized':True,'long_experiment_authorized':True,'user_instruction':USER,'utc':utc(),'devices':[{'physical_gpu_index':gpu,'gpu_uuid':UUIDS[gpu]}],'scope':role,'workload_sha256':sha(stage/'WORKLOAD.json')}
 dump(stage/'LONG_EXECUTION_APPROVAL.json',approval)
 p=copy.deepcopy(read(PARENT/'PROTOCOL.json'))
 p.update(schema='stage29-normalKV-Astar-v46/v1',study_mode='llama_normalKV_Astar_v46',case=name,role=role,workload_kind='pure',candidate_version=version,
  model_key='llama8',model_path=model['model_path'],model_profile_sha256=sha(stage/'MODEL_PROFILE.json'),expected_resource_caps=model['expected_resource_caps'],
  runtime_arm=arm,C_version='v46_v45_mixed_and_work_bounds_only'if arm=='C'else'official',mixed_variant='v46_v45_joint_foreground_v1'if arm=='C'else None,
  planned_arms=[arm],allowed_arms=[arm],attempts={arm:attempt},attempt_variants={attempt:'native'},
  arm_devices={arm:{'physical_gpu_index':gpu,'gpu_uuid':UUIDS[gpu],'authorization_file':'DEVICE_AUTHORIZATION.json'}},forbidden_gpu_indices=[x for x in [0,1,2]if x!=gpu],
  http_ports={arm:http_port},prediction_ports={arm:prediction_port},cpu_affinity={arm:CPUS[gpu]},
  resources={**p['resources'],**model['resources'],'physical_gpu_index':gpu,'gpu_uuid':UUIDS[gpu],'model':model['model_path'],'gpu_kv_tokens':None if blocks is None else blocks*16},
  workload_sha256=sha(stage/'WORKLOAD.json'),long_approval_sha256=sha(stage/'LONG_EXECUTION_APPROVAL.json'),
  expected_arrival_window_seconds=w['main'][-1]['arrival_offset_seconds'],target_arrivals=[j['arrival_offset_seconds']for j in w['main']],
  stage_counts={str(j['collection_id']):len(j['stages'])for j in w['main']},requests_per_stage={str(j['collection_id']):[len(rs)for rs in j['stages']]for j in w['main']},
  workloads={'full':{'main_root_jobs':len(w['main']),'main_compound_chains':len(w['main']),'main_call_count':sum(len(rs)for j in w['main']for rs in j['stages']),'warmup_call_count':sum(len(rs)for j in w['warmup']for rs in j['stages'])}},
  primary_metric='jitserve_token_goodput',secondary_metric='compound_attained',
  asset_receipt=str(S/'common/ASSET_VERIFICATION.json'),asset_receipt_sha256=sha(S/'common/ASSET_VERIFICATION.json'),
  baseline_budget_adapter_sha256=sha(stage/'programs/baseline_budget.py')if arm=='A'else None,
  controller_wall_seconds=28800,http_request_timeout_seconds=28200,client_transport='fresh_connection_per_request_v1',
  comparability='Stage29 Llama-only: same frozen200 traces/SLO/lengths and normal physical KV pool; Astar uses the previously published current-stage-inclusive budget adapter with native GMAX. v46 scoring/core unchanged and retains its own true whole-chain deadline. Calibration uses only Astar. Formal pairs share rate/KV/input and run in reverse order on each GPU.',
  A_semantics='Astar: native predictor/GMAX plus existing cumulative-through-current-stage/declared-depth budget adapter; not an oracle',
  C_semantics='Published minimal v46 unchanged, including unit-chain q/W score; no new baseline-budget or cadence adapter',
  full_trace_authorization=USER,requires_new_long_approval=False,
  stop_rules=['Only GPU0/GPU1 and identity-verified owned processes; GPU2 forbidden.','Profile then Astar calibration then formal pairs; no v46-dependent rate selection.','No deadline drops or request retries; preserve invalid attempts and stop affected phase.','Arrival error <=0.5 seconds; JCT reported only.'])
 p['generation']['arrival_rate']=rate;p['generation']['burst']=False;p['generation']['target_main_arrival_offsets_seconds']=p['target_arrivals']
 p['generation']['whole_chain_rule']='Whole-chain success gate for token credit and secondary attainment: client elapsed <= actual received_slo[2]*actual stage count'
 p['mixed_metrics']={'primary':'JITServe native DeepResearch text-retokenized input+8*output per full replay second','secondary':'Complete-chain SLO count','arrival_gate_seconds':.5,'JCT_constraint':False}
 p['lifetime_observation_sha256']=sha(stage/'programs/lifetime_observation.py')
 dump(stage/'PROTOCOL.json',p)
 auth=copy.deepcopy(read(PARENT/'DEVICE_AUTHORIZATION.json'));auth.update(physical_gpu_index=gpu,gpu_uuid=UUIDS[gpu],allowed_physical_gpu_indices=[gpu],max_attempt_wall_seconds=28800,http_request_timeout_seconds=28200,user_instruction=USER)
 dump(stage/'DEVICE_AUTHORIZATION.json',auth)
 basefiles=copy.deepcopy(read(PARENT/'receipts/CPU_QUALIFICATION.json')['base_files'])
 basefiles[str((S/'common/ASSET_VERIFICATION.json').relative_to(R))]=sha(S/'common/ASSET_VERIFICATION.json')
 q={'gate':'PASS','GPU_used':False,'source_commit':'16c86bb43b1b11f01699ce57cbe5609d69fae31d','base_files':basefiles,'stage_files':{str(f.relative_to(stage)):sha(f)for f in stage.rglob('*')if f.is_file()and'__pycache__'not in f.parts},'CPU_harness_receipt_sha256':sha(S/'common/CPU_QUALIFICATION.json'),'tests':'Astar semantic/selection/arrival/model/gate CPU qualification; frozen v46 publication hashes bound; exact model-tokenized parent manifest checked'}
 dump(stage/'receipts/CPU_QUALIFICATION.json',q)
 spec={'name':name,'GPU':gpu,'version':version,'role':role,'rate':rate,'gpu_blocks':blocks,'stage':str(stage),'arm':arm,'attempt':attempt,'qualification_sha256':sha(stage/'receipts/CPU_QUALIFICATION.json'),'workload_sha256':p['workload_sha256']}
 dump(stage/'CASE_SPEC.json',spec)
 return spec

def wait_idle(gpu):
 from gpu_idle import idle
 while True:
  line=subprocess.check_output(['nvidia-smi','-i',str(gpu),'--query-gpu=index,uuid,memory.used','--format=csv,noheader'],text=True).strip()
  procs=subprocess.check_output(['nvidia-smi','-i',str(gpu),'--query-compute-apps=pid,used_memory','--format=csv,noheader'],text=True).strip()
  util=int(subprocess.check_output(['nvidia-smi','-i',str(gpu),'--query-gpu=utilization.gpu','--format=csv,noheader,nounits'],text=True).strip())
  assert line.startswith(f'{gpu}, '+UUIDS[gpu]+',')
  if idle(line,procs,util):return
  dump(S/f'WAIT_GPU{gpu}.json',{'utc':utc(),'GPU':line,'processes':procs,'state':'WAIT_OTHER_JOB_NO_SIGNALS'});time.sleep(30)

def run_case(spec):
 stage=Path(spec['stage']);p=read(stage/'PROTOCOL.json');a=stage/'attempts'/spec['attempt']
 assert not list((stage/'attempts').iterdir())
 dump(stage/'CALIBRATION_STATUS.json',{'state':'RUNNING','active_arm':spec['arm'],'completed_arms':[],'phase':'WAIT_ASSIGNED_GPU_IDLE','utc':utc()})
 wait_idle(spec['GPU'])
 with(stage/'CONTROLLER.log').open('x')as log:
  subprocess.run([PYTHON,str(stage/'programs/controller.py'),str(R),str(stage),spec['arm'],spec['attempt'],'full'],cwd=R,env=env(),stdout=log,stderr=subprocess.STDOUT,check=True)
 if spec['role']=='profile':
  c=read(a/'common_audit_summary.json');receipt=read(a/'controller_receipt.json');done=read(a/'CLIENT_DONE.json')
  assert receipt['failure']is None and receipt['gpu_released']and done['complete']
  assert c['device']['physical_gpu_index']==0 and c['device']['actual_uuid']==UUIDS[0]
  assert c['resources']['model_path']==p['model_path']and c['resources']['dtype']=='torch.bfloat16'
  assert c['resources']['scheduler_type']=='jitserve.scheduler.slo_scheduler.SLOScheduler'
  assert c['final_kv_free']['gpu_blocks']==c['resources']['gpu_blocks']
  assert all(r['finished']for r in c['requests'])
  adapter=read(a/'BASELINE_BUDGET_ADAPTER.json');assert adapter['current_stage_included']
  shares=[json.loads(l)['share']for l in(a/'server_events.jsonl').open()if json.loads(l).get('kind')=='graph_stage_share'and json.loads(l).get('stage_id')==0]
  assert shares and all(x>0 for x in shares)
  n=c['resources']['gpu_blocks'];selected=normal_blocks(n)
  result={'gate':'PASS','utc':utc(),'GPU':0,'profiled_auto_gpu_blocks':n,'selected_shared_gpu_blocks':selected,'block_size':16,'selected_KV_bytes':selected*2097152,'selected_KV_GiB':selected*2097152/2**30,'gpu_memory_utilization':.85,'KV_block_headroom_fraction':.1,'first_stage_positive_shares':shares,'resources':c['resources'],'not_performance_evidence':True,'attempt':str(a)}
  dump(S/'NORMAL_KV_PROFILE.json',result)
 else:
  with(stage/'GATE.log').open('x')as log:subprocess.run([PYTHON,str(stage/'programs/offline_compare.py'),str(R),str(stage),spec['attempt']],cwd=R,env=env(),stdout=log,stderr=subprocess.STDOUT,check=True)
  result=read(stage/'receipts'/('RUN_GATE_'+spec['attempt']+'.json'));assert result['gate']=='PASS'
 dump(stage/'CALIBRATION_STATUS.json',{'state':'COMPLETED','active_arm':None,'completed_arms':[spec['arm']],'phase':'DONE','utc':utc()})
 return result

def main():
 assert read(S/'common/CPU_QUALIFICATION.json')['gate']=='PASS'
 state={'state':'RUNNING','phase':'CPU_ASSET_VERIFICATION','utc':utc(),'GPUs_allowed':[0,1],'calibration_GPU':0,'calibration':[],'formal':[]}
 def status(**kwargs):state.update(kwargs,updated_utc=utc());dump(S/'STUDY_STATUS.json',state)
 lock=None
 try:
  status();original_affinity=set(os.sched_getaffinity(0));verify_assets();os.sched_setaffinity(0,original_affinity);status(phase='NORMAL_KV_PROFILE')
  # Asset hashing precedes device locking/allocation, so CPU preparation does not reserve an idle GPU.
  lock=open('/tmp/xuetianyou_chain_slo_gpu0.lock','a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  lock.seek(0);lock.truncate();lock.write(json.dumps({'pid':os.getpid(),'study':str(S),'GPU':0}));lock.flush()
  if(S/'NORMAL_KV_PROFILE.json').exists():
   profile=read(S/'NORMAL_KV_PROFILE.json');assert profile['gate']=='PASS'and profile['GPU']==0
  else:
   probe=build_case('profile_gpu0_Astar','Astar',0,'profile',None,None);status(active_case=probe['name']);profile=run_case(probe)
  blocks=profile['selected_shared_gpu_blocks']
  status(phase='ASTAR_RATE_CALIBRATION',normal_KV=profile)
  rates=[.05,.1,.2,.4,.8,1.6];rows=[]
  def calibrate(rate):
   name='cal_gpu0_Astar_r'+str(rate).replace('.','p')+'_dispatch02';spec=build_case(name,'Astar',0,'calibration',rate,blocks);status(active_case=name)
   result=run_case(spec);row={'rate':rate,'gate':result['gate'],'goodput':result['metrics']['jitserve_token_goodput'],'compound_attained':result['metrics']['compound_attained'],'duration':result['metrics']['main_duration'],'case':name,'workload_sha256':spec['workload_sha256']}
   rows.append(row);status(calibration=rows);dump(S/'CALIBRATION_RESULTS.json',{'rows':rows,'gate':'IN_PROGRESS'})
  for rate in rates:calibrate(rate)
  # Predeclared endpoint checks, independent of all v46 observations.
  if rows[-1]['goodput']>1.05*rows[-2]['goodput']:calibrate(3.2)
  if rows[0]['goodput']>1.05*rows[1]['goodput']:calibrate(.025)
  selected,peak=choose(rows);selection={'gate':'PASS','utc':utc(),'selected_rate':selected['rate'],'observed_peak_Astar_goodput':peak,'selection_rule':'Lowest tested root arrival rate achieving >=95% observed Astar full-replay token-goodput maximum','rows':rows,'v46_used_for_selection':False,'same_full200_cohort_at_every_rate':True,'arrival_shape':'Frozen near-periodic historical shape, time scaled only','scope':'Finite200-chain replay working point; not a long-online sustainable-capacity claim','normal_gpu_blocks':blocks,'normal_KV_GiB':profile['selected_KV_GiB']}
  dump(S/'RATE_SELECTION.json',selection);status(phase='FORMAL_PAIRS_BUILD',selection=selection,active_case=None)
  specs=[]
  for gpu,versions in [(0,['Astar','v46']),(1,['v46','Astar'])]:
   for version in versions:specs.append(build_case(f'formal_gpu{gpu}_{version}',version,gpu,'formal',selected['rate'],blocks))
  assert len({s['workload_sha256']for s in specs})==1
  dump(S/'FORMAL_MATRIX.json',{'cases':specs,'total_arms':4,'GPUs':[0,1],'model':'Llama-3.1-8B-Instruct','rate_selection_sha256':sha(S/'RATE_SELECTION.json'),'same_KV_blocks':blocks,'v46_score_unchanged':True,'primary':'jitserve_token_goodput','secondary':'compound_attained'})
  # Release the calibration lock before each formal worker obtains its own exclusive lock.
  lock.close();lock=None;status(phase='FORMAL_PAIRS_RUNNING',formal=specs)
  def worker(gpu):
   with open(f'/tmp/xuetianyou_chain_slo_gpu{gpu}.lock','a+')as device_lock:
    fcntl.flock(device_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    device_lock.seek(0);device_lock.truncate();device_lock.write(json.dumps({'pid':os.getpid(),'study':str(S),'GPU':gpu}));device_lock.flush()
    results={}
    for spec in [x for x in specs if x['GPU']==gpu]:
     try:results[spec['version']]=run_case(spec)
     except BaseException as exc:
      dump(Path(spec['stage'])/'CALIBRATION_STATUS.json',{'state':'FAILED_PRESERVED','phase':'STOPPED','error':str(exc),'traceback':traceback.format_exc(),'utc':utc()});raise
    assert results['Astar']['request_signatures']==results['v46']['request_signatures']
    result={'gate':'PASS','GPU':gpu,'metrics':{v:r['metrics']for v,r in results.items()},'same_request_signatures':True,'normal_gpu_blocks':blocks,'rate':selected['rate']}
    dump(S/f'PAIR_GPU{gpu}.json',result);return result
  with ThreadPoolExecutor(max_workers=2)as pool:
   futures=[pool.submit(worker,gpu)for gpu in [0,1]]
   paired=[f.result()for f in futures]
  status(state='COMPLETED',phase='DONE',pairs=paired,completed_utc=utc())
 except BaseException as exc:
  status(state='FAILED_PRESERVED',phase='STOPPED',error=str(exc),traceback=traceback.format_exc())
  raise
 finally:
  if lock is not None:lock.close()
if __name__=='__main__':main()
