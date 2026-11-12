"""Read-only GPU0/1 and CPU-supervisor snapshot; never arm, advance or signal."""
from pathlib import Path
from datetime import datetime,timezone
import json,shlex,subprocess
D=Path(__file__).resolve().parent;T=D.parents[1]
W=Path('/Users/xuetianyou/Documents/Codex/2026-11-08/gpu-node1-stage47-gpu0-stage45-gpu1-2')
s=json.loads((W/'work/gpu01_monitor_20261110/MONITOR_STATE.json').read_text())
prep=json.loads((D/'CPU_PREPARATION_RECEIPT.json').read_text());queues=s['queues']
q0=next(q for q in queues if q['GPU']==0);q0.update(remote_study=prep['study'],kind='fixed_window_cutoff_no_drain');q0.pop('queued_successor',None)
source=(T/'work/stage86_qwen14_fixedreplay_bridge_20261111/probe_with_handoff.py').read_text().replace("q.get('kind')!='fixed_hour_cutoff_no_drain'","q.get('kind')not in ['fixed_hour_cutoff_no_drain','fixed_window_cutoff_no_drain']")
code=r'''
from pathlib import Path
from datetime import datetime,timezone
import contextlib,io,hashlib,json,os,sys
source=SOURCE_LITERAL
with contextlib.redirect_stdout(io.StringIO())as buf:exec(source,{'__name__':'readonly_queue_probe'})
answer=json.loads(buf.getvalue());answer['supervisors']=[]
def read(p):return json.loads(p.read_text())if p.exists()else None
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def identity(r):
 if not r:return {'matches':False,'receipt':None,'live':None}
 try:
  P=Path('/proc')/str(r['pid']);v=(P/'stat').read_text().rsplit(')',1)[1].split();argv=(P/'cmdline').read_bytes().decode().split('\0')[:-1];cmd=r['command'];cmd=cmd[3:]if cmd[:2]==['taskset','-c']else cmd
  try:
   env=(P/'environ').read_bytes().split(b'\0');mask=next((x.split(b'=',1)[1].decode()for x in env if x.startswith(b'CUDA_VISIBLE_DEVICES=')),None)
  except PermissionError:mask='UNREADABLE'
  live={'pid':r['pid'],'state':v[0],'proc_start_ticks':int(v[19]),'argv':argv,'CUDA_VISIBLE_DEVICES':mask,'affinity':sorted(os.sched_getaffinity(r['pid']))}
  return {'matches':int(v[19])==r['proc_start_ticks']and v[0]!='Z'and argv==cmd,'receipt':r,'live':live}
 except(FileNotFoundError,ProcessLookupError):return {'matches':False,'receipt':r,'live':None}
for row in answer['rows']:
 S=Path(row['study']);cq=read(S/'control/CONTROL_QUALIFICATION.json')
 supervisor={'GPU':row['GPU'],'study':str(S),'runner':identity(read(S/'RUNNER_LAUNCH.json')),'watcher':identity(read(S/'WATCHER_LAUNCH.json')),'control_qualification':{'gate':cq.get('gate')if cq else None,'files_match':{k:sha(S/'control'/k)==v for k,v in(cq or{}).get('files',{}).items()}},'artifacts':{k:read(S/k)for k in ['HANDOFF_STATUS.json','INDEPENDENT_AUDIT_STATUS.json','HANDOFF_OR_AUDIT_FAILURE.json','FINAL_READY.json','FINAL_VALIDATION.json']}}
 active=row.get('active')
 if active:
  spec=next(x for x in read(S/'MATRIX.json')['cases']if x['name']==active['case']);C=Path(spec['stage']);A=C/'attempts'/spec['attempt']
  ready=[]
  if(A/'common_events.jsonl').exists():
   for l in(A/'common_events.jsonl').open():
    try:e=json.loads(l)
    except json.JSONDecodeError:continue
    if e['kind']in ['device_identity','engine_ready']:ready.append(e)
  supervisor.update(active_case=active['case'],actual_engine_resources=ready,live_executor=read(A/'LIVE_EXECUTOR_OBSERVATION.json'),runtime=read(A/'COMPARISON_SUITE_RUNTIME.json'),protocol_summary={k:read(C/'PROTOCOL.json').get(k)for k in ['model_key','model_path','resources','cutoff_seconds','expected_resource_caps','target_arrivals']})
 answer['supervisors'].append(supervisor)
S=Path(answer['rows'][0]['study'])
answer['new_study_artifacts']={k:read(S/k)for k in ['PLAN.json','MATRIX.json','CPU_QUALIFICATION.json','AUTHORIZATION.json','PREDECESSOR_AUDIT.json','RUNNER_LAUNCH.json','WATCHER_LAUNCH.json','control/CONTROL_QUALIFICATION.json']}
answer['read_only']=True;answer['utc']=datetime.now(timezone.utc).isoformat()
print(json.dumps(answer))
'''.replace('SOURCE_LITERAL',repr(source))
stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');out=D/'readonly_snapshots';out.mkdir(exist_ok=True)
r=subprocess.run(['ssh','-o','ConnectTimeout=12','gpu-node1','CUDA_VISIBLE_DEVICES= PYTHONDONTWRITEBYTECODE=1 python3 -c '+shlex.quote(code)],input=json.dumps({'queues':queues}),capture_output=True,text=True,timeout=120)
(out/(stamp+'.stderr')).write_text(r.stderr);assert r.returncode==0,r.stderr
value=json.loads(r.stdout);path=out/(stamp+'.json');path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');print(path)
for row,supervisor in zip(value['rows'],value['supervisors']):
 active=row.get('active')or{}
 print(json.dumps({'GPU':row['GPU'],'state':row['status']['state'],'active':active.get('case'),'phase':active.get('phase',{}).get('phase'),'MAIN':bool(active.get('main_start')),'completed_main_roots':active.get('completed_main_roots'),'finished_requests':active.get('finished_main_requests'),'finished_request_output_tokens':active.get('finished_main_output_tokens'),'runner_matches':supervisor['runner']['matches'],'watcher_matches':supervisor['watcher']['matches'],'supervisor_failure':supervisor['artifacts']['HANDOFF_OR_AUDIT_FAILURE.json'],'failure':active.get('failure'),'case_failure':active.get('case_failure'),'GPU_state':row['GPU_state']},ensure_ascii=False))
