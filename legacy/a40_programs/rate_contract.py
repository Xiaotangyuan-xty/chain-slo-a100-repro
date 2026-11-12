"""Frozen 200-chain model/rate/window contract, independent of attained performance."""
from pathlib import Path
import hashlib,json,math
RATES=[.1,.2,.3,.4,.5,.6,.7,.8,.9,1.,1.2,1.4,1.6]
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def verify(C):
 C=Path(C);p=read(C/'PROTOCOL.json');w=read(C/'WORKLOAD.json');m=read(C/'MODEL_PROFILE.json');src=Path(p['fixed_workload_source']);base=read(src)
 assert sha(src)==p['fixed_workload_source_sha256']
 rate=p['generation']['arrival_rate'];H=p['cutoff_seconds'];assert rate in RATES and math.isclose(H,200/rate,rel_tol=0,abs_tol=1e-10)
 assert len(w['main'])==200 and sum(len(s)for j in w['main']for s in j['stages'])==1197
 assert sum(r['target_output_tokens']for j in w['main']for s in j['stages']for r in s)==504695
 for ph in ['warmup','main']:
  assert len(w[ph])==len(base[ph])
  for a,b in zip(w[ph],base[ph]):
   assert {k:v for k,v in a.items()if k!='arrival_offset_seconds'}=={k:v for k,v in b.items()if k!='arrival_offset_seconds'}
 assert w['warmup']==base['warmup']
 reference=read(Path(p['arrival_source']))
 target=[j['arrival_offset_seconds']*.4/rate for j in reference['main']]
 assert p['target_arrivals']==[j['arrival_offset_seconds']for j in w['main']]==target
 assert all(0<=t<H for t in target)and target==sorted(target)
 slo=[j['received_slo'][2]*len(j['stages'])for j in w['main']];assert min(slo)==80 and max(slo)==480
 assert p['resources']['physical_gpu_index']==0 and p['forbidden_gpu_indices']==[1,2]
 assert p['candidate_version']in ['v47pro','A','native_vllm']and not(C/'ORACLE_LENGTHS.json').exists()
 assert p['resources']['num_gpu_blocks_override']is None and m['resources']['num_gpu_blocks_override']is None
 assert 'gpu_blocks'not in p['expected_resource_caps']and m['gpu_KV_bytes']is None
 assert p['resources']['gpu_memory_utilization']==.85 and p['resources']['swap_space_gib']==1.
 assert p['resources']['dtype']=='bfloat16'and p['resources']['max_model_len']==8192
 assert p['resources']['max_num_seqs']==32 and p['resources']['max_num_batched_tokens']==2048
 assert p['model_key']==m['model_key']and p['model_path']==m['model_path']
 assert m['qrf_training_model']==('llama-3.1-8b'if p['model_key']=='llama8'else'qwen2.5-7b')
 return {'fixed_DR200_1197_504695':True,'original_prompts_SLO_and_stage_dependencies':True,'whole_chain_SLO80_to480':True,'GPU0_only':True,'automatic_KV_without_override':True,'predeclared_rate_and_N_over_rate_cutoff':True,'common_conditional_Poisson_shape':True,'frozen_per_model_deployment_no_training':True}
