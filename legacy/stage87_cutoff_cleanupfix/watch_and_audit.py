"""Persistent CPU-only audit; validation failures are recorded, never block later cases."""
from pathlib import Path
import fcntl,json,os,subprocess,sys,time,traceback
S=Path(sys.argv[1]).resolve();sys.path.insert(0,str(S/'common/programs'))
from bundle_runtime import R,L,read,dump,sha
from handoff import launch,alive
os.sched_setaffinity(0,{28,30,84,86});assert os.environ.get('CUDA_VISIBLE_DEVICES','')==''
control=S/'control';proof=read(control/'CONTROL_QUALIFICATION.json')
assert proof['gate']=='PASS'and all(sha(control/n)==h for n,h in proof['files'].items())
try:
 with open('/tmp/xuetianyou_stage87_v4_cutoff_auditor.lock','a+')as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  result=launch(S);dump(S/'HANDOFF_STATUS.json',{'state':result['gate'],'utc':L.utc(),**result})
  assert result['gate']in ['LAUNCHED','ALREADY_LAUNCHED']
  directory=S/'independent_window_audit';directory.mkdir(exist_ok=True);matrix=read(S/'MATRIX.json')['cases'];assert len(matrix)==78
  done=set();audit_failed={}
  while True:
   state=read(S/'STUDY_STATUS.json')
   if state['state']=='PREPARED'and not alive(read(S/'RUNNER_LAUNCH.json')):raise RuntimeError('Runner exited before START; preserve startup failure')
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
   for i in range(0,78,3):
    group=matrix[i:i+3]
    if all(s['name']in done for s in group):
     f=S/('GROUP_'+group[-1]['model_key']+'_r'+str(group[-1]['rate']).replace('.','p')+'_COMPARISON.json')
     if f.exists()and read(f).get('gate')=='PASS':compared.append(str(f))
     else:comparison_failed.append(group[-1]['name'])
   dump(S/'INDEPENDENT_AUDIT_STATUS.json',{'utc':L.utc(),'state':'COMPLETE'if len(done)==78 else'WAIT_CASE_COMPLETION','completed':sorted(done),'audit_failed':audit_failed,'audited_strict_group_comparisons':compared,'comparison_failed':comparison_failed})
   if len(done)==78 and state['state']in['COMPLETED','COMPLETED_WITH_FAILURES']and not alive(read(S/'RUNNER_LAUNCH.json')):
    final_path=S/'CROSSMODEL_CUTOFF_FINAL_COMPARISON.json';final_ok=final_path.exists()and read(final_path).get('gate')=='PASS'
    okay=not audit_failed and not comparison_failed and not state.get('failed')and final_ok
    value={'gate':'PASS'if okay else'COMPLETED_WITH_FAILURES','utc':L.utc(),'all78_cases_terminal':True,'all78_independent_audits_PASS':not audit_failed,'all26_strict_group_comparisons_PASS':not comparison_failed and len(compared)==26,'final_comparison_PASS':final_ok,'audit_failed':audit_failed,'case_failed':state.get('failed',[]),'no_drain':True,'runner_exited':True,'validation_failures_do_not_block_independent_cases':True}
    dump(S/'FINAL_VALIDATION.json',value)
    if okay:dump(S/'FINAL_READY.json',value)
    break
   if state['state']=='NEEDS_ATTENTION':raise RuntimeError('Unsafe or startup workflow stop; inspect before any recovery')
   time.sleep(30)
except Exception as exc:
 value={'utc':L.utc(),'error':str(exc),'traceback':traceback.format_exc(),'no_automatic_retry':True,'audit_failure_does_not_hold_gpu_runner':True}
 dump(S/'HANDOFF_OR_AUDIT_FAILURE.json',value)
 raise
