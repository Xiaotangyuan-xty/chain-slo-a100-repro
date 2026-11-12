from pathlib import Path
import copy,json,os,sys
from unittest.mock import patch
os.sched_setaffinity(0,{28,30,84,86});assert os.environ.get('CUDA_VISIBLE_DEVICES','')==''
packet=json.load(sys.stdin);S=Path(packet['study']);assert not(S/'RUNNER_LAUNCH.json').exists()
sys.path.insert(0,str(S/'common/programs'))
from bundle_runtime import L,read,dump,sha
import handoff
control=S/'control';control.mkdir();tests=S/'control_CPU_tests';tests.mkdir();passed=[]
for name,text in packet['files'].items():(control/name).write_text(text)
def fixture(name):
 B=tests/name;B.mkdir();P=B/'old';F=B/'new';P.mkdir();F.mkdir();(P/'source.py').write_text('CPU fixture')
 dump(P/'CPU_QUALIFICATION.json',{'gate':'PASS','workflow_files':{'source.py':sha(P/'source.py')}})
 specs=[]
 for label in ['v47pro3','A']:
  C=P/'cases'/label;A=C/'attempts/TEST';A.mkdir(parents=True);(C/'receipts').mkdir();(C/'source.py').write_text('CPU fixture')
  dump(C/'receipts/CPU_QUALIFICATION.json',{'gate':'PASS','stage_files':{'source.py':sha(C/'source.py')}})
  dump(C/'receipts/RUN_GATE_TEST.json',{'gate':'PASS','checks':{'fixture':True}});dump(C/'CASE_STATUS.json',{'state':'COMPLETED'})
  dump(A/'processes.json',[]);dump(A/'controller_receipt.json',{'gpu_released':True,'own_gpu_processes_remaining':[],'failure':None})
  specs.append({'name':C.name,'stage':str(C),'attempt':'TEST'})
  directory=P/'independent_bridge_audit';directory.mkdir(exist_ok=True);dump(directory/(C.name+'_INDEPENDENT.json'),{'gate':'PASS'})
 dump(P/'MATRIX.json',{'cases':specs});dump(P/'STUDY_STATUS.json',{'state':'COMPLETED','active_case':None,'completed':[s['name']for s in specs],'failed':[]})
 dump(P/'RUNNER_LAUNCH.json',{'pid':-987654,'proc_start_ticks':1,'command':['CPU_FIXTURE']})
 for n in ['FINAL_VALIDATION.json','FINAL_READY.json','PAIR_FINAL_COMPARISON.json']:dump(P/n,{'gate':'PASS'})
 dump(F/'PLAN.json',{'GPU':0,'after_study':str(P),'predecessor_CPU_qualification_sha256':sha(P/'CPU_QUALIFICATION.json')})
 return F,P,specs
F,P,sp=fixture('READY');assert handoff.dependency(F)['gate']=='READY';passed.append('FINAL_AUDITED_CLEAN_READY')
F,P,sp=fixture('RUNNING_WAITS');v=read(P/'STUDY_STATUS.json');v['state']='RUNNING';dump(P/'STUDY_STATUS.json',v);assert handoff.dependency(F)['gate']=='WAIT_CURRENT_QUEUE';passed.append('RUNNING_WAITS')
F,P,sp=fixture('HOLD');dump(F/'HOLD.json',{});assert handoff.dependency(F)['gate']=='HOLD_USER_CANCEL';passed.append('HOLD_PREVENTS_LAUNCH')
for name,mutate in [('DIRTY_RECEIPT',lambda F,P,s:dump(Path(s[0]['stage'])/'attempts/TEST/controller_receipt.json',{'gpu_released':False,'own_gpu_processes_remaining':[],'failure':None})),('CHANGED_SOURCE',lambda F,P,s:(P/'source.py').write_text('changed')),('FINAL_READY_FAIL',lambda F,P,s:dump(P/'FINAL_READY.json',{'gate':'FAIL'}))]:
 F,P,sp=fixture(name);mutate(F,P,sp)
 try:handoff.dependency(F)
 except AssertionError:passed.append(name+'_REJECTED')
 else:raise AssertionError(name+' accepted')
F,P,sp=fixture('DUPLICATE');dump(F/'CPU_QUALIFICATION.json',{'gate':'PASS','workflow_files':{}});dump(F/'RUNNER_LAUNCH.json',{'existing':True})
with patch.object(handoff.subprocess,'Popen',side_effect=AssertionError('Duplicate launch')):assert handoff.launch(F)['gate']=='ALREADY_LAUNCHED'
passed.append('DUPLICATE_NO_POPEN')
F,P,sp=fixture('WRONG_GPU');dump(F/'CPU_QUALIFICATION.json',{'gate':'PASS','workflow_files':{}});plan=read(F/'PLAN.json');plan['GPU']=1;dump(F/'PLAN.json',plan)
with patch.object(handoff,'dependency',return_value={'gate':'READY'}),patch.object(handoff.subprocess,'Popen',side_effect=AssertionError('Unapproved GPU launch')):
 try:handoff.launch(F)
 except AssertionError:passed.append('NON_GPU0_REJECTED')
 else:raise AssertionError('NonGPU0 accepted')
actual=handoff.dependency(S);assert actual['gate']=='READY'
proof={'gate':'PASS','utc':L.utc(),'GPU_used':False,'dependency_tests':passed,'actual_dependency_snapshot':actual,'files':{n:sha(control/n)for n in packet['files']},'runtime_CPU_qualification_sha256':sha(S/'CPU_QUALIFICATION.json'),'no_GPU_started':True}
dump(control/'CONTROL_QUALIFICATION.json',proof);print(json.dumps(proof))
