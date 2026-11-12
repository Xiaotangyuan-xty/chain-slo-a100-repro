from pathlib import Path
import json,shlex,subprocess
D=Path(__file__).resolve().parent
code=r'''
from pathlib import Path
import hashlib,json,os
os.sched_setaffinity(0,{28,30,84,86})
R=Path('/mnt/sda1/xuetianyou-a40/agent-dispatch-experiments/idea1_continuity/idea3_full_jitserve_compare_20261027T121314Z_v1')
refs={'llama8':R/'stage82_llama8_v47pro3_lengthOracle_pure200_r0p4_r0p8_gpu1_after_stage79_20261110_v1/cases/01_r0p4_v47pro3','qwen14':R/'stage86_qwen14_fixedDR200_504695_r0p4_KV8p625_v47pro3_A_gpu0_after_stage84_20261111_v1/cases/01_qwen14_fixed504695_r0p4_v47pro3'}
out={}
for k,C in refs.items():
 w=json.loads((C/'WORKLOAD.json').read_text());p=json.loads((C/'PROTOCOL.json').read_text())
 out[k]={'source':str(C),'profile':json.loads((C/'MODEL_PROFILE.json').read_text()),'protocol':p,'workload_sha256':hashlib.sha256((C/'WORKLOAD.json').read_bytes()).hexdigest(),'main_first':w['main'][0]['arrival_offset_seconds'],'main_last':w['main'][-1]['arrival_offset_seconds'],'main_payload_digest':hashlib.sha256(json.dumps([{a:v for a,v in j.items()if a not in ['arrival_offset_seconds','source']}for j in w['main']],sort_keys=True).encode()).hexdigest(),'warmup':len(w['warmup']),'root_ids':[j['collection_id']for j in w['main']]}
 print('',end='')
out['predecessor_qualification_sha256']=hashlib.sha256((refs['qwen14'].parents[1]/'CPU_QUALIFICATION.json').read_bytes()).hexdigest()
out['model_payload_differences']=[];out['member_field_differences']={}
wa=json.loads((refs['llama8']/'WORKLOAD.json').read_text());wb=json.loads((refs['qwen14']/'WORKLOAD.json').read_text())
for ph in ['warmup','main']:
 for i,(a,b)in enumerate(zip(wa[ph],wb[ph])):
  for k in set(a)|set(b):
   if k not in ['arrival_offset_seconds','source'] and a.get(k)!=b.get(k):out['model_payload_differences'].append([ph,i,k])
  for sa,sb in zip(a['stages'],b['stages']):
   for ra,rb in zip(sa,sb):
    for k in set(ra)|set(rb):
     if ra.get(k)!=rb.get(k):out['member_field_differences'][k]=out['member_field_differences'].get(k,0)+1
out['assets']={k:json.loads((Path(out[k]['protocol']['asset_receipt'])).read_text())for k in refs}
out['prepare']=json.loads((R/'PREPARE.json').read_text())
out['read_only']=True
print(json.dumps(out))
'''
r=subprocess.run(['ssh','-o','ConnectTimeout=12','gpu-node1','CUDA_VISIBLE_DEVICES= PYTHONDONTWRITEBYTECODE=1 python3 -c '+shlex.quote(code)],text=True,capture_output=True,timeout=90)
(D/'references.stderr').write_text(r.stderr);assert r.returncode==0,r.stderr
(D/'references.json').write_text(r.stdout)
x=json.loads(r.stdout);print(json.dumps({'read_only':True,'models':{k:{'source':x[k]['source'],'first':x[k]['main_first'],'last':x[k]['main_last'],'profile':x[k]['profile']['model_path']}for k in ['llama8','qwen14']},'member_field_differences':x['member_field_differences']},ensure_ascii=False))
