"""Launch GPU1 once, then independently audit twelve terminal cutoff cases."""
from pathlib import Path
import fcntl,json,os,subprocess,sys,time,traceback
S=Path(sys.argv[1]).resolve();sys.path.insert(0,str(S/'common/programs'))
from bundle_runtime import R,L,read,dump,sha
os.sched_setaffinity(0,{28,30,84,86});assert os.environ.get('CUDA_VISIBLE_DEVICES','')==''
control=S/'control';proof=read(control/'CONTROL_QUALIFICATION.json')
assert proof['gate']=='PASS'and all(sha(control/n)==h for n,h in proof['files'].items())

def alive(reg):
 if not reg:return False
 try:
  P=Path('/proc')/str(reg['pid']);v=(P/'stat').read_text().rsplit(')',1)[1].split()
  if int(v[19])!=reg['proc_start_ticks']or v[0]=='Z':return False
  cmd=reg['command'];cmd=cmd[3:]if cmd[:2]==['taskset','-c']else cmd
  return(P/'cmdline').read_bytes().decode().split('\0')[:-1]==cmd
 except(FileNotFoundError,ProcessLookupError):return False

def launch_runner():
 if(S/'RUNNER_LAUNCH.json').exists():return{'gate':'ALREADY_LAUNCHED','launch':read(S/'RUNNER_LAUNCH.json')}
 assert not(S/'LAUNCH_STARTED.json').exists(),'Inspect partial launch'
 previous=R/'stage85_llama8_SLOcompletion_sweep5x3_pure200_r0p4_KV22p1816_gpu1_after_stage83_20261111_v1'
 assert read(previous/'FINAL_READY.json')['gate']=='PASS'and not alive(read(previous/'RUNNER_LAUNCH.json'))
 gpu=subprocess.check_output(['nvidia-smi','-i','1','--query-gpu=index,uuid,memory.used','--format=csv,noheader'],text=True).strip();assert gpu.startswith('1, '+L.UUIDS[1]+',')
 assert not subprocess.check_output(['nvidia-smi','-i','1','--query-compute-apps=pid','--format=csv,noheader'],text=True).strip(),'GPU1 occupied; no external signals'
 command=['taskset','-c',','.join(map(str,L.CPUS[1])),L.PYTHON,str(S/'common/programs/workflow.py'),str(S)]
 dump(S/'LAUNCH_STARTED.json',{'utc':L.utc(),'command':command,'GPU1_preflight':gpu})
 with(S/'RUNNER.log').open('x')as out:p=subprocess.Popen(command,cwd=R,env=L.env(),stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
 expected=command[3:];until=time.monotonic()+5
 while True:
  assert p.poll()is None,'Runner exited before stable identity'
  current=Path(f'/proc/{p.pid}/cmdline').read_bytes().decode().split('\0')[:-1]
  if current==expected:break
  assert time.monotonic()<until,'Runner identity did not settle';time.sleep(.01)
 ticks=int(Path(f'/proc/{p.pid}/stat').read_text().rsplit(')',1)[1].split()[19]);reg={'utc':L.utc(),'pid':p.pid,'pgid':p.pid,'proc_start_ticks':ticks,'command':command,'study':str(S),'GPU_allowed':[1]}
 dump(S/'RUNNER_LAUNCH.json',reg);return{'gate':'LAUNCHED','launch':reg}

try:
 with open('/tmp/xuetianyou_stage88_hour12_auditor.lock','a+')as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  result=launch_runner();dump(S/'HANDOFF_STATUS.json',{'state':result['gate'],'utc':L.utc(),**result})
  directory=S/'independent_window_audit';directory.mkdir(exist_ok=True);matrix=read(S/'MATRIX.json')['cases'];assert len(matrix)==12
  done=set();audit_failed={}
  while True:
   state=read(S/'STUDY_STATUS.json')
   if state['state']=='PREPARED'and not alive(read(S/'RUNNER_LAUNCH.json')):raise RuntimeError('Runner exited before START')
   terminal=set(state.get('terminal',state.get('completed',[])))
   for spec in matrix:
    if spec['name']not in terminal or spec['name']in done:continue
    row={'path':spec['stage'],'attempt':spec['attempt'],'name':spec['name']}
    e=L.env();e.update(CUDA_VISIBLE_DEVICES='',PYTHONDONTWRITEBYTECODE='1',TOKENIZERS_PARALLELISM='false',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
    r=subprocess.run([L.PYTHON,str(control/'recompute_window_readonly.py')],input=json.dumps({'cases':[row]}),capture_output=True,text=True,env=e,cwd=R/'runtime',timeout=900)
    (directory/(spec['name']+'.stderr')).write_text(r.stderr)
    if r.returncode:
     (directory/(spec['name']+'.failed_stdout')).write_text(r.stdout);audit_failed[spec['name']]={'error':r.stderr[-3000:],'returncode':r.returncode}
    else:
     value=json.loads(r.stdout);dump(directory/(spec['name']+'.json'),value)
     if value['gate']!='PASS':audit_failed[spec['name']]={'error':'Independent audit gate FAIL'}
    done.add(spec['name'])
   compared=[];comparison_failed=[]
   for i in range(0,12,3):
    group=matrix[i:i+3]
    if all(s['name']in done for s in group):
     f=S/('GROUP_'+group[-1]['model_key']+'_r'+str(group[-1]['rate']).replace('.','p')+'_COMPARISON.json')
     if f.exists()and read(f).get('gate')=='PASS':compared.append(str(f))
     else:comparison_failed.append(group[-1]['name'])
   dump(S/'INDEPENDENT_AUDIT_STATUS.json',{'utc':L.utc(),'state':'COMPLETE'if len(done)==12 else'WAIT_CASE_COMPLETION','completed':sorted(done),'audit_failed':audit_failed,'audited_strict_group_comparisons':compared,'comparison_failed':comparison_failed})
   if len(done)==12 and state['state']in['COMPLETED','COMPLETED_WITH_FAILURES']and not alive(read(S/'RUNNER_LAUNCH.json')):
    final_path=S/'CROSSMODEL_CUTOFF_FINAL_COMPARISON.json';final_ok=final_path.exists()and read(final_path).get('gate')=='PASS'
    okay=not audit_failed and not comparison_failed and not state.get('failed')and final_ok
    value={'gate':'PASS'if okay else'COMPLETED_WITH_FAILURES','utc':L.utc(),'all12_cases_terminal':True,'all12_independent_audits_PASS':not audit_failed,'all4_strict_group_comparisons_PASS':not comparison_failed and len(compared)==4,'final_comparison_PASS':final_ok,'audit_failed':audit_failed,'case_failed':state.get('failed',[]),'no_drain':True,'runner_exited':True}
    dump(S/'FINAL_VALIDATION.json',value)
    if okay:dump(S/'FINAL_READY.json',value)
    break
   if state['state']=='NEEDS_ATTENTION':raise RuntimeError('Unsafe or startup workflow stop')
   time.sleep(30)
except Exception as exc:
 value={'utc':L.utc(),'error':str(exc),'traceback':traceback.format_exc(),'no_automatic_retry':True,'audit_failure_does_not_hold_gpu_runner':True}
 dump(S/'HANDOFF_OR_AUDIT_FAILURE.json',value);raise
