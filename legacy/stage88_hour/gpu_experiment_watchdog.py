"""Check both queues every 30 minutes; exit to alert the agent on a real stop."""
import datetime,json,os,shlex,subprocess,time
STUDIES=[
 {'GPU':0,'expected':78,'name':'stage87_v47pro3_A_FCFS_llama8_qwen14_DR200_autoKV_rates13_cutoff_cleanupfix_gpu0_20261111_v6'},
 {'GPU':1,'expected':12,'name':'stage88_v47pro3_A_FCFS_llama8_qwen14_hour3600_r0p1_r0p2_autoKV_gpu1_20261111_v3'},
]
REMOTE=r'''
from pathlib import Path
import json
R=Path('/mnt/sda1/xuetianyou-a40/agent-dispatch-experiments/idea1_continuity/idea3_full_jitserve_compare_20261027T121314Z_v1')
def alive(reg):
 if not reg:return False
 try:
  P=Path('/proc')/str(reg['pid']);v=(P/'stat').read_text().rsplit(')',1)[1].split()
  if int(v[19])!=reg['proc_start_ticks']or v[0]=='Z':return False
  cmd=reg['command'];cmd=cmd[3:]if cmd[:2]==['taskset','-c']else cmd
  return(P/'cmdline').read_bytes().decode().split('\0')[:-1]==cmd
 except(FileNotFoundError,ProcessLookupError):return False
rows=[]
for item in packet:
 S=R/item['name'];st=json.loads((S/'STUDY_STATUS.json').read_text())
 launch=json.loads((S/'RUNNER_LAUNCH.json').read_text())if(S/'RUNNER_LAUNCH.json').exists()else None
 watcher=json.loads((S/'WATCHER_LAUNCH.json').read_text())if(S/'WATCHER_LAUNCH.json').exists()else None
 rows.append({'GPU':item['GPU'],'study':item['name'],'expected':item['expected'],'state':st.get('state'),'phase':st.get('phase'),'active_case':st.get('active_case'),'terminal':len(st.get('terminal',st.get('completed',[]))),'completed':len(st.get('completed',[])),'failed':st.get('failed',[]),'runner_alive':alive(launch),'watcher_alive':alive(watcher),'error':st.get('error')})
print(json.dumps(rows))
'''
def snapshot():
 code="import sys,json;packet=json.loads(sys.stdin.readline());exec(sys.stdin.read())"
 command='PYTHONDONTWRITEBYTECODE=1 python3 -c '+shlex.quote(code)
 r=subprocess.run(['ssh','-o','ConnectTimeout=12','gpu-node1',command],input=json.dumps(STUDIES)+'\n'+REMOTE,text=True,capture_output=True,timeout=60)
 if r.returncode:raise RuntimeError(r.stderr[-1500:])
 return json.loads(r.stdout)
def main():
 failures=0
 while True:
  stamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
  try:rows=snapshot();failures=0
  except Exception as exc:
   failures+=1;print(json.dumps({'utc':stamp,'event':'CHECK_ERROR','error':str(exc),'consecutive_failures':failures}),flush=True)
   if failures>=3:return 43
   time.sleep(1800);continue
  stopped=[];done=[]
  for row in rows:
   complete=row['state']in['COMPLETED','COMPLETED_WITH_FAILURES']and row['terminal']>=row['expected']and not row['runner_alive']
   if complete:done.append(row['GPU']);continue
   if row['state']=='NEEDS_ATTENTION'or not row['runner_alive']or not row['watcher_alive']:stopped.append(row)
  print(json.dumps({'utc':stamp,'event':'STATUS','rows':rows,'stopped':[r['GPU']for r in stopped],'done':done},ensure_ascii=False),flush=True)
  if stopped:
   print(json.dumps({'utc':stamp,'event':'EXPERIMENT_STOPPED','requires_diagnosis_and_safe_recovery':True,'stopped':stopped},ensure_ascii=False),flush=True);return 42
  if len(done)==len(STUDIES):print(json.dumps({'utc':stamp,'event':'ALL_QUEUES_TERMINAL'},ensure_ascii=False),flush=True);return 0
  if os.environ.get('CHECK_ONCE')=='1':return 0
  time.sleep(1800)
if __name__=='__main__':raise SystemExit(main())
