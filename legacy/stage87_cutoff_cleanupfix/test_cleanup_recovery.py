"""CPU-only regression for sampler cleanup race and independent-case continuation."""
from pathlib import Path
import ast,importlib.util,json,os,subprocess,sys,tempfile

S=Path(sys.argv[1]).resolve();R=S.parent
NEW=S/'common/programs/controller.py'
OLD=R/'stage87_v47pro3_A_FCFS_llama8_qwen14_DR200_autoKV_rates13_cutoff_gpu0_20261111_v3/common/programs/controller.py'

def load_stop(path):
 tree=ast.parse(path.read_text());main=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='main')
 node=next(n for n in main.body if isinstance(n,ast.FunctionDef)and n.name=='stop_process')
 node.decorator_list=[]
 ns={'os':os,'signal':__import__('signal'),'subprocess':subprocess}
 exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),str(path),'exec'),ns)
 return ns

class FakeProcess:
 def __init__(self,polls):self.polls=list(polls);self.waits=[]
 def poll(self):return self.polls.pop(0)if self.polls else self.polls[-1]
 def wait(self,timeout):self.waits.append(timeout);return 0

def race(path,still_running):
 ns=load_stop(path);p=FakeProcess([None,None]if still_running else[None,0]);ns['processes']={'sampler':p}
 ns['registry']=[{'name':'sampler','pid':123,'pgid':123,'proc_start_ticks':1,'command':['x']}]
 ns['same_process']=lambda identity:False
 try:ns['stop_process']('sampler',15)
 except RuntimeError:return 'RAISED'
 return 'RETURNED'

assert race(OLD,False)=='RAISED','Original failure was not reproduced'
assert race(NEW,False)=='RETURNED','Natural-exit cleanup race was not fixed'
assert race(NEW,True)=='RAISED','Changed live identity must still be refused'

spec=importlib.util.spec_from_file_location('recovery_workflow_test',S/'common/programs/workflow.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with tempfile.TemporaryDirectory()as td:
 T=Path(td);cases=[]
 for i in range(1,79):
  name=f'{i:02d}_fake';C=T/'cases'/name;A=C/'attempts'/('ATTEMPT_'+str(i));A.mkdir(parents=True)
  reuse=i==1 or i>3
  if reuse:
   (C/'receipts').mkdir();(C/'receipts'/('RUN_GATE_ATTEMPT_'+str(i)+'.json')).write_text(json.dumps({'gate':'PASS','checks':{'ok':True},'metrics':{}}))
   (C/'CASE_STATUS.json').write_text(json.dumps({'state':'COMPLETED'}))
  cases.append({'name':name,'stage':str(C),'attempt':'ATTEMPT_'+str(i),'model_key':'llama8','rate':.1,'reuse_existing_pass':reuse})
 (T/'CPU_QUALIFICATION.json').write_text(json.dumps({'gate':'PASS','workflow_files':{}}));(T/'PLAN.json').write_text(json.dumps({'GPU':0}));(T/'MATRIX.json').write_text(json.dumps({'cases':cases}))
 calls=[]
 def fake_execute(S,spec,status):
  calls.append(spec['name'])
  if spec['name']=='02_fake':raise RuntimeError('Simulated final gate FAIL')
  return {'gate':'PASS','metrics':{}}
 m.execute=fake_execute;m.owned_alive=lambda A:[];m.compare_group=lambda S,specs:{'gate':'PASS','cases':[]};m.summarize=lambda S:{'gate':'PASS','groups':[]}
 m.main(T)
 state=json.loads((T/'STUDY_STATUS.json').read_text())
 assert calls==['02_fake','03_fake'],calls
 assert len(state['terminal'])==78 and state['failed']==['02_fake']and state['state']=='COMPLETED_WITH_FAILURES'
 assert state['completed'][0]=='01_fake'and len(state['completed'])==77
 final=json.loads((T/'FINAL_RESULTS.json').read_text());assert final['reused_PASS_without_GPU_replay']==['01_fake']+[f'{i:02d}_fake'for i in range(4,79)]

import torch
assert not torch.cuda.is_initialized()
print(json.dumps({'gate':'PASS','original_cleanup_race_reproduced':True,'natural_exit_now_reaped':True,'changed_live_identity_still_refused':True,'gate_failure_continues_to_next_case':True,'passed_reuse_never_enters_executor':True,'GPU_used':False}))
