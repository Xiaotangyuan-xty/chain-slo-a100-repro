"""Frozen one-hour, 360/720-root GPU1 contract with automatic KV."""
from pathlib import Path
import hashlib,json,math

def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def verify(C):
 C=Path(C);p=read(C/'PROTOCOL.json');w=read(C/'WORKLOAD.json');m=read(C/'MODEL_PROFILE.json');src=Path(p['fixed_workload_source']);base=read(src)
 assert sha(src)==p['fixed_workload_source_sha256']
 rate=p['generation']['arrival_rate'];H=p['cutoff_seconds'];N=p['root_count']
 assert rate in[.1,.2] and math.isclose(H,3600.,rel_tol=0,abs_tol=1e-10) and N==int(3600*rate)
 assert len(w['main'])==N and len({j['collection_id']for j in w['main']})==N
 assert len(w['warmup'])==len(base['warmup'])==1
 for a,b in zip(w['warmup'],base['warmup']):
  assert a['collection_id']==900000 and {k:v for k,v in a.items()if k!='collection_id'}=={k:v for k,v in b.items()if k!='collection_id'}
 for j in w['main']:
  source=base['main'][j['source']['template_root_index']]
  assert j['stages']==source['stages']and j['received_slo']==source['received_slo']and j['request_type']==2
 requests=sum(len(s)for j in w['main']for s in j['stages']);outputs=sum(r['target_output_tokens']for j in w['main']for s in j['stages']for r in s)
 assert requests==p['expected_main_requests']and outputs==p['expected_target_output_tokens']
 target=[j['arrival_offset_seconds']for j in w['main']]
 assert p['target_arrivals']==target and target==sorted(target)and all(0<=t<H for t in target)
 slo=[j['received_slo'][2]*len(j['stages'])for j in w['main']];assert min(slo)==80 and max(slo)==480
 assert p['resources']['physical_gpu_index']==1 and p['forbidden_gpu_indices']==[0,2]
 assert p['candidate_version']in['v47pro','A','native_vllm']and not(C/'ORACLE_LENGTHS.json').exists()
 assert p['resources']['num_gpu_blocks_override']is None and m['resources']['num_gpu_blocks_override']is None
 assert 'gpu_blocks'not in p['expected_resource_caps']and m['gpu_KV_bytes']is None
 assert p['resources']['gpu_memory_utilization']==.85 and p['resources']['swap_space_gib']==1.
 assert p['resources']['dtype']=='bfloat16'and p['resources']['max_model_len']==8192
 assert p['resources']['max_num_seqs']==32 and p['resources']['max_num_batched_tokens']==2048
 assert p['model_key']==m['model_key']and p['model_path']==m['model_path']
 assert m['qrf_training_model']==('llama-3.1-8b'if p['model_key']=='llama8'else'qwen2.5-7b')
 return {'fixed_hour_3600':True,'root_count_matches_rate':True,'template_payloads_SLO_dependencies_preserved':True,'GPU1_only':True,'automatic_KV_without_override':True,'frozen_per_model_deployment_no_training':True}
