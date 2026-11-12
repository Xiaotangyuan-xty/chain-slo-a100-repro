"""Strict within-model/rate comparison, with censored outcomes and observed capacities."""
from pathlib import Path
import hashlib,json,math
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
CAPS=['model_path','tokenizer_path','dtype','gpu_blocks','cpu_blocks','block_size','max_num_seqs','max_num_batched_tokens','max_model_len','enforce_eager','single_engine','enable_chunked_prefill','enable_prefix_caching']
def compare_group(S,specs):
 assert len(specs)==3 and {s['version']for s in specs}=={'v47pro','A','native_vllm'}
 rows=[];signatures=[]
 for spec in specs:
  C=Path(spec['stage']);g=read(C/'receipts'/('RUN_GATE_'+spec['attempt']+'.json'));p=read(C/'PROTOCOL.json')
  assert g['gate']=='PASS'and all(g['checks'].values());signatures.append(g['request_signatures'])
  rows.append({'case':spec['name'],'method':spec['display_method'],'model_key':spec['model_key'],'rate':spec['rate'],'window_seconds':p['cutoff_seconds'],'metrics':g['metrics'],'workload_sha256':sha(C/'WORKLOAD.json'),'model_profile_sha256':sha(C/'MODEL_PROFILE.json'),'resources':{k:g['resources'][k]for k in CAPS},'GPU_UUID':g['GPU_UUID'],'common_runtime_hashes':p['common_runtime_hashes'],'candidate_hashes':read(C/'SUITE_SPEC.json')['candidate_hashes'],'window_program_hashes':{n:sha(C/'programs'/n)for n in ['window_client.py','window_server.py','cutoff_observation.py','window_metrics.py','resource_sampler.py','scheduler_cpu.py']}})
 checks={k:all(r[k]==rows[0][k]for r in rows)for k in ['workload_sha256','model_profile_sha256','resources','GPU_UUID','common_runtime_hashes','candidate_hashes','window_program_hashes','window_seconds','model_key','rate']}
 shared={};same=True
 for sig in signatures:
  for k,v in sig.items():
   if k in shared and shared[k]!=v:same=False
   shared[k]=v
 checks['overlapping_actual_request_signatures']=same
 return {'gate':'PASS'if all(checks.values())else'FAIL','checks':checks,'cases':rows,'automatic_KV_actual_capacity_must_match_within_group':True,'no_drain':True,'different_observed_request_sets_allowed':True}
def summarize(S):
 specs=read(S/'MATRIX.json')['cases'];assert len(specs)==78
 groups={}
 for s in specs:groups.setdefault((s['model_key'],s['rate']),[]).append(s)
 results=[]
 for (model,rate),items in groups.items():
  r=compare_group(S,items);assert r['gate']=='PASS',(model,rate,r['checks']);results.append(r)
 result={'gate':'PASS','groups':results,'cases':78,'group_count':26,'no_drain':True,'single_repetition':True}
 (S/'CROSSMODEL_CUTOFF_FINAL_COMPARISON.json').write_text(json.dumps(result,indent=2)+'\n')
 text=['# 200链、两模型、三方法、十三档到达率：固定窗口截断结果','', '| 模型 | 到达率 | 方法 | 窗口秒 | credit/s | 实际输出token/s | 完成链 | SLO达标 | 确定违约 | 右删失 | 实际KV块 |','|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|']
 for group in results:
  for r in group['cases']:
   m=r['metrics'];text.append(f"| {r['model_key']} | {r['rate']} | {r['method']} | {r['window_seconds']:.6f} | {m['fixed_window_credit_per_second']:.6f} | {m['actual_output_tokens_per_second']:.6f} | {m['completed_chains_before_cutoff']} | {m['SLO_attained_chains_before_cutoff']} | {m['definite_SLO_misses_by_cutoff']} | {m['SLO_outcome_right_censored']} | {r['resources']['gpu_blocks']} |")
 text+=['','每组正式窗口为200/到达率，半开区间[MAIN,MAIN+H)，到点阻止新GPU执行并取消/清理，不自然排空。未完成链分为确定违约与右删失，不按技术失败处理；完整回放收益不适用。原prompt、目标输出和整链SLO80–480秒不改；不同模型保留各自tokenizer元数据和冻结部署档案。','', 'KV无人工块数覆盖；统一显存使用比例0.85、CPU swap1GiB，实际GPU块数单列。FCFS为现有冻结后端原生vLLM Scheduler/FCFSPolicy，预测/图匹配/候选机制关闭。单次运行不宣称统计显著性。']
 (S/'CROSSMODEL_CUTOFF_FINAL_REPORT.md').write_text('\n'.join(text)+'\n')
 return result
