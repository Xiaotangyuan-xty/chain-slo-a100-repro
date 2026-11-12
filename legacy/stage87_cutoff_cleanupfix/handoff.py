"""Receipt-qualified, single GPU0 launch after completed Stage86; no external signals."""
from pathlib import Path
import fcntl,json,os,subprocess,time
from bundle_runtime import R,L,read,dump,sha
def alive(reg):
 if not reg:return False
 try:
  P=Path('/proc')/str(reg['pid']);v=(P/'stat').read_text().rsplit(')',1)[1].split()
  if int(v[19])!=reg['proc_start_ticks']or v[0]=='Z':return False
  cmd=reg['command'];cmd=cmd[3:]if cmd[:2]==['taskset','-c']else cmd
  assert(P/'cmdline').read_bytes().decode().split('\0')[:-1]==cmd
  return True
 except FileNotFoundError:return False
def dependency(S):
 plan=read(S/'PLAN.json');P=Path(plan['after_study'])
 if(S/'HOLD.json').exists()or(P/'HOLD.json').exists():return {'gate':'HOLD_USER_CANCEL'}
 st=read(P/'STUDY_STATUS.json')
 if st['state']!='COMPLETED'or st.get('active_case')is not None or alive(read(P/'RUNNER_LAUNCH.json')):return {'gate':'WAIT_CURRENT_QUEUE'}
 assert sha(P/'CPU_QUALIFICATION.json')==plan['predecessor_CPU_qualification_sha256']
 q=read(P/'CPU_QUALIFICATION.json');assert q['gate']=='PASS'and all(sha(P/n)==h for n,h in q['workflow_files'].items())
 specs=read(P/'MATRIX.json')['cases'];assert len(specs)==2 and set(st['completed'])=={s['name']for s in specs}and not st.get('failed')
 for spec in specs:
  C=Path(spec['stage']);A=C/'attempts'/spec['attempt'];g=read(C/'receipts'/('RUN_GATE_'+spec['attempt']+'.json'))
  assert g['gate']=='PASS'and all(g['checks'].values())and read(C/'CASE_STATUS.json')['state']=='COMPLETED'
  cq=read(C/'receipts/CPU_QUALIFICATION.json');assert cq['gate']=='PASS'and all(sha(C/n)==h for n,h in cq['stage_files'].items())
  assert not any(alive(r)for r in read(A/'processes.json'))
  c=read(A/'controller_receipt.json');assert c['gpu_released']and not c['own_gpu_processes_remaining']and not c['failure']
  audit=P/'independent_bridge_audit'/(spec['name']+'_INDEPENDENT.json');assert read(audit)['gate']=='PASS'
 assert not(P/'HANDOFF_OR_AUDIT_FAILURE.json').exists()
 for name in ['FINAL_VALIDATION.json','FINAL_READY.json','PAIR_FINAL_COMPARISON.json']:assert read(P/name)['gate']=='PASS'
 result={'gate':'READY','predecessor':str(P),'all2_final_clean_independent_full_trace_pair_comparison_PASS':True,'runner_exited':True,'no_GPU_replay':True}
 recovery=plan.get('recovery_from_study')
 if recovery:
  V=Path(recovery);vst=read(V/'STUDY_STATUS.json');assert vst['state']=='NEEDS_ATTENTION'
  assert not alive(read(V/'RUNNER_LAUNCH.json'))and not alive(read(V/'WATCHER_LAUNCH.json'))
  oldspecs=read(V/'MATRIX.json')['cases'];first,second=oldspecs[:2]
  C1=Path(first['stage']);g1=read(C1/'receipts'/('RUN_GATE_'+first['attempt']+'.json'))
  assert g1['gate']=='PASS'and all(g1['checks'].values())and read(C1/'CASE_STATUS.json')['state']=='COMPLETED'
  C2=Path(second['stage']);assert read(C2/'CASE_STATUS.json')['state']=='FAILED_PRESERVED'
  assert 'changed identity for sampler' in read(C2/'attempts'/second['attempt']/'controller_receipt.json')['failure']['error']
  for spec in oldspecs:
   A=Path(spec['stage'])/'attempts'/spec['attempt']
   if (A/'processes.json').exists():assert not any(alive(r)for r in read(A/'processes.json'))
  result.update(recovery_from_study=str(V),recovery_from_terminal_failure=True,reused_case1_PASS=True,failed_case2_preserved_and_not_reused=True,old_runner_and_watcher_exited=True,continue_after_gate_FAILURE=True)
 return result
def launch(S):
 q=read(S/'CPU_QUALIFICATION.json');assert q['gate']=='PASS'and all(sha(S/n)==h for n,h in q['workflow_files'].items())
 with open('/tmp/xuetianyou_followup_launch_gpu0.lock','a+')as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  if(S/'RUNNER_LAUNCH.json').exists():return {'gate':'ALREADY_LAUNCHED','launch':read(S/'RUNNER_LAUNCH.json')}
  assert not(S/'LAUNCH_STARTED.json').exists(),'Inspect partial launch; do not repeat'
  d=dependency(S)
  if d['gate']!='READY':return d
  assert read(S/'PLAN.json')['GPU']==0
  assert not subprocess.check_output(['nvidia-smi','-i','0','--query-compute-apps=pid','--format=csv,noheader'],text=True).strip(),'GPU0 is occupied; do not signal external owners'
  P=Path(read(S/'PLAN.json')['after_study']);proof={'gate':'PASS','utc':L.utc(),'predecessor':str(P),'checks':d,'files':{n:sha(P/n)for n in ['CPU_QUALIFICATION.json','FINAL_VALIDATION.json','FINAL_READY.json','PAIR_FINAL_COMPARISON.json']},'reused_existing_audit_no_GPU_replay':True}
  dump(S/'PREDECESSOR_AUDIT.json',proof)
  command=['taskset','-c',','.join(map(str,L.CPUS[0])),L.PYTHON,str(S/'common/programs/workflow.py'),str(S)]
  dump(S/'LAUNCH_STARTED.json',{'utc':L.utc(),'command':command,'dependency':d})
  with(S/'RUNNER.log').open('x')as out:p=subprocess.Popen(command,cwd=R,env=L.env(),stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
  # taskset execs Python under the same PID/ticks; publish only the stable Python identity.
  expected=command[3:];until=time.monotonic()+5.
  while True:
   assert p.poll()is None,'Runner exited before stable launch identity'
   current=Path(f'/proc/{p.pid}/cmdline').read_bytes().decode().split('\0')[:-1]
   if current==expected:break
   assert time.monotonic()<until,'Runner exec identity did not settle'
   time.sleep(.01)
  ticks=int(Path(f'/proc/{p.pid}/stat').read_text().rsplit(')',1)[1].split()[19]);reg={'utc':L.utc(),'pid':p.pid,'pgid':p.pid,'proc_start_ticks':ticks,'command':command,'study':str(S),'GPU_allowed':[0],'dependency':d}
  dump(S/'RUNNER_LAUNCH.json',reg);return {'gate':'LAUNCHED','launch':reg}
