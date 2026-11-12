"""GPU0 serial recovery: reuse certified PASS, isolate case gates, never overlap owners."""
from pathlib import Path
import fcntl,json,os,sys,traceback
from bundle_runtime import L,read,dump,sha
from execution_base import execute,owned_alive
from window_summary import compare_group,summarize

def main(S):
 q=read(S/'CPU_QUALIFICATION.json');assert q['gate']=='PASS'and read(S/'PLAN.json')['GPU']==0
 assert all(sha(S/n)==h for n,h in q['workflow_files'].items())
 matrix=read(S/'MATRIX.json')['cases'];assert len(matrix)==78
 state={'state':'RUNNING','phase':'START','active_case':None,'completed':[],'failed':[],'terminal':[],'results':[]}
 def status(**v):state.update(v,updated_utc=L.utc());dump(S/'STUDY_STATUS.json',state)
 try:
  with open('/tmp/xuetianyou_chain_slo_gpu0.lock','a+')as lock:
   fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);lock.seek(0);lock.truncate();lock.write(json.dumps({'pid':os.getpid(),'GPU':0,'study':str(S)}));lock.flush()
   for i,spec in enumerate(matrix):
    if(S/'HOLD.json').exists():raise RuntimeError('User HOLD observed; no next case')
    C=Path(spec['stage']);A=C/'attempts'/spec['attempt']
    if spec.get('reuse_existing_pass'):
     gate=read(C/'receipts'/('RUN_GATE_'+spec['attempt']+'.json'))
     assert gate['gate']=='PASS'and all(gate['checks'].values())
     assert read(C/'CASE_STATUS.json')['state']=='COMPLETED'and not owned_alive(A)
     result={'gate':'PASS','metrics':gate['metrics'],'gate_path':str(C/'receipts'/('RUN_GATE_'+spec['attempt']+'.json')),'reused_existing_PASS_without_GPU_replay':True}
    else:
     try:result=execute(S,spec,status)
     except BaseException as exc:
      result={'gate':'FAIL','error':str(exc),'traceback':traceback.format_exc()}
      dump(C/'CASE_FAILURE.json',result)
    # A failed gate never blocks the next case. Unsafe owned processes do.
    if owned_alive(A):raise RuntimeError('Owned processes remain; refuse overlap')
    row={'case':spec,**result};state['results'].append(row);state['terminal'].append(spec['name'])
    if result['gate']=='PASS':state['completed'].append(spec['name'])
    else:state['failed'].append(spec['name'])
    if not spec.get('reuse_existing_pass'):
     dump(C/'CASE_STATUS.json',{'state':'COMPLETED'if result['gate']=='PASS'else'FAILED_PRESERVED','utc':L.utc(),'result':row})
    status(phase='CASE_TERMINAL',active_case=spec['name'])
    if(i+1)%3==0:
     try:group=compare_group(S,matrix[i-2:i+1])
     except BaseException as exc:group={'gate':'FAIL','error':str(exc),'traceback':traceback.format_exc(),'cases':[s['name']for s in matrix[i-2:i+1]]}
     dump(S/('GROUP_'+spec['model_key']+'_r'+str(spec['rate']).replace('.','p')+'_COMPARISON.json'),group)
   final_error=None
   try:final=summarize(S)
   except BaseException as exc:
    final_error={'error':str(exc),'traceback':traceback.format_exc()};final={'gate':'FAIL','error':str(exc)}
   dump(S/'FINAL_RESULTS.json',{'gate':'PASS'if not state['failed']and not final_error else'COMPLETED_WITH_FAILURES','utc':L.utc(),'cases':state['results'],'failed':state['failed'],'terminal':state['terminal'],'final_comparison':final,'final_comparison_error':final_error,'no_automatic_retries':True,'reused_PASS_without_GPU_replay':[s['name']for s in matrix if s.get('reuse_existing_pass')]})
   status(state='COMPLETED'if not state['failed']and not final_error else'COMPLETED_WITH_FAILURES',phase='DONE',active_case=None)
 except BaseException as exc:status(state='NEEDS_ATTENTION',phase='PRESERVED_NO_BLIND_RETRY',error=str(exc),traceback=traceback.format_exc());raise
if __name__=='__main__':main(Path(sys.argv[1]).resolve())
