"""CPU-only launch-control qualification for the twelve-case GPU1 queue."""
from pathlib import Path
import json,os,sys
os.sched_setaffinity(0,{28,30,84,86});assert os.environ.get('CUDA_VISIBLE_DEVICES','')==''
packet=json.load(sys.stdin);S=Path(packet['study']);assert not(S/'RUNNER_LAUNCH.json').exists()
sys.path.insert(0,str(S/'common/programs'))
from bundle_runtime import L,read,dump,sha
control=S/'control';control.mkdir()
for name,text in packet['files'].items():(control/name).write_text(text)
q=read(S/'CPU_QUALIFICATION.json');assert q['gate']=='PASS'and q['actual_controller_entry_cases']==12
assert all(sha(S/n)==h for n,h in q['workflow_files'].items())
plan=read(S/'PLAN.json');assert plan['GPU']==1 and plan['case_count']==12 and plan['rates']==[.1,.2]
for spec in read(S/'MATRIX.json')['cases']:
 assert spec['GPU']==1 and spec['gpu_blocks']is None and not list((Path(spec['stage'])/'attempts').iterdir())
P=S.parent/'stage85_llama8_SLOcompletion_sweep5x3_pure200_r0p4_KV22p1816_gpu1_after_stage83_20261111_v1'
assert read(P/'FINAL_READY.json')['gate']=='PASS'
def alive(reg):
 try:
  p=Path('/proc')/str(reg['pid']);v=(p/'stat').read_text().rsplit(')',1)[1].split();return int(v[19])==reg['proc_start_ticks']and v[0]!='Z'
 except FileNotFoundError:return False
assert not alive(read(P/'RUNNER_LAUNCH.json'))and not alive(read(P/'WATCHER_LAUNCH.json'))
proof={'gate':'PASS','utc':L.utc(),'GPU_used':False,'checks':['12_GPU1_cases','all_attempts_empty','workflow_hashes','predecessor_final_and_exited','control_sources_frozen'],'files':{n:sha(control/n)for n in packet['files']},'runtime_CPU_qualification_sha256':sha(S/'CPU_QUALIFICATION.json'),'no_GPU_started':True}
dump(control/'CONTROL_QUALIFICATION.json',proof);print(json.dumps(proof))
