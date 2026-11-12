"""Launch the qualified CPU watcher once; it launches the qualified GPU0 runner once."""
from pathlib import Path
import json,shlex,subprocess
D=Path(__file__).resolve().parent;prep=json.loads((D/'CPU_PREPARATION_RECEIPT.json').read_text())
code=r'''
from pathlib import Path
import fcntl,json,os,subprocess,sys
packet=json.load(sys.stdin);S=Path(packet['study']);sys.path.insert(0,str(S/'common/programs'))
from bundle_runtime import R,L,read,dump,sha
from handoff import dependency,alive
os.sched_setaffinity(0,{28,30,84,86});assert os.environ.get('CUDA_VISIBLE_DEVICES','')==''
q=read(S/'CPU_QUALIFICATION.json');cq=read(S/'control/CONTROL_QUALIFICATION.json')
assert sha(S/'CPU_QUALIFICATION.json')==packet['CPU_qualification_sha256']==cq['runtime_CPU_qualification_sha256']
assert q['gate']==cq['gate']=='PASS'and q['actual_controller_entry_cases']==78
assert all(sha(S/n)==h for n,h in q['workflow_files'].items())and all(sha(S/'control'/n)==h for n,h in cq['files'].items())
plan=read(S/'PLAN.json');assert plan['GPU']==0 and plan['case_count']==78
assert plan['rates']==[.1,.2,.3,.4,.5,.6,.7,.8,.9,1.,1.2,1.4,1.6]
with open('/tmp/xuetianyou_stage87_arm.lock','a+')as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 if(S/'WATCHER_LAUNCH.json').exists():
  r=read(S/'WATCHER_LAUNCH.json');print(json.dumps({'gate':'ALREADY_ARMED','watcher':r,'identity_matches':alive(r),'no_duplicate_launch':True}));sys.exit(0)
 assert not(S/'WATCHER_ARM_STARTED.json').exists(),'Inspect partial arm; never repeat'
 for spec in read(S/'MATRIX.json')['cases']:
  assert spec['GPU']==0 and spec['gpu_blocks']is None
  C=Path(spec['stage'])
  if spec.get('reuse_existing_pass'):
   g=read(C/'receipts'/('RUN_GATE_'+spec['attempt']+'.json'));assert g['gate']=='PASS'and read(C/'CASE_STATUS.json')['state']=='COMPLETED'
  else:assert not list((C/'attempts').iterdir())
  assert sha(C/'receipts/CPU_QUALIFICATION.json')==spec['qualification_sha256']
 d=dependency(S);assert d['gate']=='READY'
 gpu=subprocess.check_output(['nvidia-smi','-i','0','--query-gpu=index,uuid,memory.used','--format=csv,noheader'],text=True).strip()
 assert gpu.startswith('0, '+L.UUIDS[0]+',')
 assert not subprocess.check_output(['nvidia-smi','-i','0','--query-compute-apps=pid','--format=csv,noheader'],text=True).strip()
 command=['taskset','-c','28,30,84,86',L.PYTHON,str(S/'control/watch_and_audit.py'),str(S)]
 dump(S/'WATCHER_ARM_STARTED.json',{'utc':L.utc(),'command':command,'GPU0_preflight':gpu,'dependency':d})
 env=L.env();env.update(CUDA_VISIBLE_DEVICES='',PYTHONDONTWRITEBYTECODE='1',TOKENIZERS_PARALLELISM='false',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
 with(S/'WATCHER.log').open('x')as out:p=subprocess.Popen(command,cwd=R/'runtime',env=env,stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
 ticks=int(Path(f'/proc/{p.pid}/stat').read_text().rsplit(')',1)[1].split()[19]);reg={'utc':L.utc(),'pid':p.pid,'pgid':p.pid,'proc_start_ticks':ticks,'command':command,'CPU_only':True,'GPU_allowed_for_later_runner':[0]}
 dump(S/'WATCHER_LAUNCH.json',reg);print(json.dumps({'gate':'ARMED','study':str(S),'watcher':reg,'CPU_qualification_sha256':sha(S/'CPU_QUALIFICATION.json'),'control_qualification_sha256':sha(S/'control/CONTROL_QUALIFICATION.json'),'GPU0_preflight':gpu,'application_automation_changed':False}))
'''
r=subprocess.run(['ssh','-o','ConnectTimeout=12','gpu-node1','CUDA_VISIBLE_DEVICES= PYTHONDONTWRITEBYTECODE=1 python3 -c '+shlex.quote(code)],input=json.dumps(prep),capture_output=True,text=True,timeout=120)
(D/'arm_once.stderr').write_text(r.stderr);(D/'arm_once.stdout').write_text(r.stdout)
assert r.returncode==0,r.stderr
value=json.loads(r.stdout);(D/'ARM_RECEIPT.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');print(json.dumps(value,ensure_ascii=False))
