from pathlib import Path
import copy,json,math,os,sys
from unittest.mock import patch
assert os.environ.get('CUDA_VISIBLE_DEVICES','')==''
S=Path(sys.argv[1]);specs=json.loads((S/'MATRIX.json').read_text())['cases']
from rate_contract import verify
assert len(specs)==78 and len({(s['model_key'],s['rate'])for s in specs})==26
for s in specs:assert all(verify(s['stage']).values())
for i in range(0,len(specs),3):
 assert len({s['workload_sha256']for s in specs[i:i+3]})==1
C=Path(next(s for s in specs if not s.get('reuse_existing_pass'))['stage']);p=C/'PROTOCOL.json';raw=p.read_bytes();base=json.loads(raw)
rejected=[]
try:
 for name,change in [('wrong_window',lambda q:q.update(cutoff_seconds=q['cutoff_seconds']+1)),('KV_override',lambda q:q['resources'].update(num_gpu_blocks_override=100)),('unapproved_GPU',lambda q:q['resources'].update(physical_gpu_index=1))]:
  q=copy.deepcopy(base);change(q);p.write_text(json.dumps(q))
  try:verify(C)
  except AssertionError:rejected.append(name)
  else:raise AssertionError(name+' accepted')
finally:p.write_bytes(raw)
warm=[c for c in json.loads((C/'cpu_attempts/WINDOW_CLIENT_TRANSPORT/client_calls.json').read_text())if c['phase']=='warmup']
from saturation_checks import qualify_warmup
for key in ['llama8','qwen14']:
 native=Path(next(s for s in specs if s['model_key']==key and s['version']=='native_vllm' and not s.get('reuse_existing_pass'))['stage']);pr=json.loads((native/'PROTOCOL.json').read_text());w=json.loads((native/'WORKLOAD.json').read_text())
 out=native/'cpu_attempts/NATIVE_WARMUP_FIXTURE';out.mkdir()
 ready={'kind':'engine_ready','scheduler_type':'vllm.core.scheduler.Scheduler','policy_type':'jitserve.scheduler.policy.FCFSPolicy',**pr['expected_resource_caps']}
 dev={'kind':'device_identity','physical_gpu_index':0,'actual_uuid':pr['resources']['gpu_uuid']}
 (out/'common_events.jsonl').write_text(json.dumps(ready)+'\n'+json.dumps(dev)+'\n')
 (out/'COMPARISON_SUITE_RUNTIME.json').write_text(json.dumps({'method':'native_vllm','candidate_scheduler_installed':False,'candidate_modules_loaded':False,'prediction_enabled':False,'graph_matching_enabled':False,'information_adapter':{'enabled':False}}))
 (out/'LIVE_EXECUTOR_OBSERVATION.json').write_text(json.dumps({'executor_hooked':True,'execution_observer':{'events':1,'failed_calls':0},'schedule_cpu':{'version':'schedule_thread_cpu_v1','calls':1,'failed_calls':0}}))
 assert qualify_warmup(out,w,pr,warm)['gate']=='PASS'
 wrong=copy.deepcopy(warm);wrong[0]['received_slo']=[1,1,1]
 try:qualify_warmup(out,w,pr,wrong)
 except RuntimeError:pass
 else:raise AssertionError('wrong native warmup SLO accepted')
from resource_contract_validation import verify as resource_verify
pr=copy.deepcopy(base);actual={**pr['expected_resource_caps'],'gpu_blocks':12345,'model_path':pr['model_path'],'dtype':'torch.bfloat16'}
reg={'name':'server','cuda_visible_devices':pr['resources']['gpu_uuid'],'command':['python','server.py','--model',pr['model_path'],'--dtype','bfloat16','--gpu-memory-utilization','.85']}
assert resource_verify(pr,{'resources':actual},[reg])['gate']=='PASS'
reg['command']+=['--num-gpu-blocks-override','12345'];assert resource_verify(pr,{'resources':actual},[reg])['gate']=='FAIL'
import native_graph_observation as graph
for key in ['llama8','qwen14']:
 for method in ['v47pro','A']:
  case=Path(next(s for s in specs if s['model_key']==key and s['version']==method and not s.get('reuse_existing_pass'))['stage']);pr=json.loads((case/'PROTOCOL.json').read_text());w=json.loads((case/'WORKLOAD.json').read_text());out=case/'cpu_attempts/AUTO_KV_WARMUP_FIXTURE';out.mkdir()
  ready={'kind':'engine_ready',**pr['expected_resource_caps'],'gpu_blocks':12345};dev={'kind':'device_identity','physical_gpu_index':0,'actual_uuid':pr['resources']['gpu_uuid']}
  def write_events(blocks):
   ready['gpu_blocks']=blocks;(out/'common_events.jsonl').write_text(json.dumps(ready)+'\n'+json.dumps(dev)+'\n')
  write_events(12345)
  (out/'COMPARISON_SUITE_RUNTIME.json').write_text(json.dumps({'method':method,'release':pr['release_version'],'frozen_candidate_modules_exact':True,'candidate_scheduler_installed':method=='v47pro'}))
  (out/'LIVE_EXECUTOR_OBSERVATION.json').write_text(json.dumps({'executor_hooked':True,'execution_observer':{'version':'executor_host_boundary_v1','events':1,'failed_calls':0},'candidate_cost_models_present':method=='v47pro','cost_accepted_samples':1,'schedule_cpu':{'version':'schedule_thread_cpu_v1','calls':1,'failed_calls':0}}))
  with patch.object(graph,'route_checks',return_value=({},[])),patch.object(graph,'shared_checks',return_value={'prediction_success_covers_requests':True,'no_prediction_fallback':True}):
   assert qualify_warmup(out,w,pr,warm)['gate']=='PASS'
   write_events(0)
   try:qualify_warmup(out,w,pr,warm)
   except RuntimeError:pass
   else:raise AssertionError('zero automatic GPU blocks accepted')
import torch
assert not torch.cuda.is_initialized()
print(json.dumps({'gate':'PASS','all78_contracts':True,'26_shared_workload_groups':True,'negative_controls_rejected':rejected,'native_warmup_both_models_positive_negative':True,'candidate_auto_KV_warmup_positive_zero_negative':True,'candidate_fixture_route_prediction_stubs_declared':True,'actual_auto_KV_positive_and_override_rejected':True,'GPU_used':False}))
