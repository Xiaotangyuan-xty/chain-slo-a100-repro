"""Launch the qualified GPU1 watcher once; watcher launches the runner once."""
from pathlib import Path
import json,shlex,subprocess
D=Path(__file__).resolve().parent;prep=json.loads((D/'CPU_PREPARATION_RECEIPT.json').read_text())
code=r'''
from pathlib import Path
import fcntl,json,os,subprocess,sys
packet=json.load(sys.stdin);S=Path(packet['study']);sys.path.insert(0,str(S/'common/programs'))
from bundle_runtime import L,read,dump,sha
os.sched_setaffinity(0,{28,30,84,86});assert os.environ.get('CUDA_VISIBLE_DEVICES','')==''
q=read(S/'CPU_QUALIFICATION.json');cq=read(S/'control/CONTROL_QUALIFICATION.json')
assert sha(S/'CPU_QUALIFICATION.json')==packet['CPU_qualification_sha256']==cq['runtime_CPU_qualification_sha256']
assert q['gate']==cq['gate']=='PASS'and q['actual_controller_entry_cases']==12
assert all(sha(S/n)==h for n,h in q['workflow_files'].items())and all(sha(S/'control'/n)==h for n,h in cq['files'].items())
plan=read(S/'PLAN.json');assert plan['GPU']==1 and plan['case_count']==12 and plan['rates']==[.1,.2]
with open('/tmp/xuetianyou_stage88_hour12_arm.lock','a+')as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 if(S/'WATCHER_LAUNCH.json').exists():
  print(json.dumps({'gate':'ALREADY_ARMED','watcher':read(S/'WATCHER_LAUNCH.json')}));sys.exit(0)
 assert not(S/'WATCHER_ARM_STARTED.json').exists(),'Inspect partial arm'
 for spec in read(S/'MATRIX.json')['cases']:
  assert spec['GPU']==1 and spec['gpu_blocks']is None and not list((Path(spec['stage'])/'attempts').iterdir())
 gpu=subprocess.check_output(['nvidia-smi','-i','1','--query-gpu=index,uuid,memory.used','--format=csv,noheader'],text=True).strip();assert gpu.startswith('1, '+L.UUIDS[1]+',')
 assert not subprocess.check_output(['nvidia-smi','-i','1','--query-compute-apps=pid','--format=csv,noheader'],text=True).strip(),'GPU1 occupied; no external signals'
 command=['taskset','-c','28,30,84,86',L.PYTHON,str(S/'control/watch_and_audit.py'),str(S)]
 dump(S/'WATCHER_ARM_STARTED.json',{'utc':L.utc(),'command':command,'GPU1_preflight':gpu})
 env=L.env();env.update(CUDA_VISIBLE_DEVICES='',PYTHONDONTWRITEBYTECODE='1',TOKENIZERS_PARALLELISM='false',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
 with(S/'WATCHER.log').open('x')as out:p=subprocess.Popen(command,cwd=L.ROOT if hasattr(L,'ROOT')else S.parent,env=env,stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
 ticks=int(Path(f'/proc/{p.pid}/stat').read_text().rsplit(')',1)[1].split()[19]);reg={'utc':L.utc(),'pid':p.pid,'pgid':p.pid,'proc_start_ticks':ticks,'command':command,'CPU_only':True,'GPU_allowed_for_later_runner':[1]}
 dump(S/'WATCHER_LAUNCH.json',reg);print(json.dumps({'gate':'ARMED','study':str(S),'watcher':reg,'CPU_qualification_sha256':sha(S/'CPU_QUALIFICATION.json'),'control_qualification_sha256':sha(S/'control/CONTROL_QUALIFICATION.json'),'GPU1_preflight':gpu}))
'''
r=subprocess.run(['ssh','-o','ConnectTimeout=12','gpu-node1','CUDA_VISIBLE_DEVICES= PYTHONDONTWRITEBYTECODE=1 python3 -c '+shlex.quote(code)],input=json.dumps(prep),capture_output=True,text=True,timeout=120)
(D/'arm_hour12.stderr').write_text(r.stderr);(D/'arm_hour12.stdout').write_text(r.stdout)
assert r.returncode==0,r.stderr
value=json.loads(r.stdout);(D/'ARM_HOUR12_RECEIPT.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');print(json.dumps(value,ensure_ascii=False))
