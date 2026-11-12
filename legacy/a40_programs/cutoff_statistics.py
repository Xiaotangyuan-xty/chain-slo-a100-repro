"""Observed-latency and scheduler-CPU statistics; incomplete chains remain censored."""
import json,statistics
def stats(v):
 v=sorted(v)
 if not v:return {'n':0,'mean':None,'p50':None,'p95':None,'max':None}
 def q(p):x=(len(v)-1)*p;i=int(x);return v[i]+(v[min(i+1,len(v)-1)]-v[i])*(x-i)
 return {'n':len(v),'mean':statistics.fmean(v),'p50':q(.5),'p95':q(.95),'max':v[-1]}
def summarize(A,snapshot,start,end,H):
 calls=[c for c in snapshot['roots']if c['success']and c['client_chain_end_monotonic']is not None and c['client_chain_end_monotonic']<end]
 jct=stats([c['client_chain_end_monotonic']-c['client_chain_start_monotonic']for c in calls])
 requests=[r for c in snapshot['roots']for s in c['stages']for r in s['requests']if r['success']and r['client_request_end_monotonic']is not None and r['client_request_end_monotonic']<end]
 ttft=stats([r['server_ttft']for r in requests if r.get('server_ttft')is not None]);tbt=stats([x for r in requests for x in r['server_tbt']])
 cpu=[json.loads(l)for l in(A/'SCHEDULER_CPU_EVENTS.jsonl').open()];receipt=json.loads((A/'SCHEDULER_CPU_RUNTIME.json').read_text())
 assert len(cpu)==receipt['calls']and receipt['failed_calls']==0 and all(e['error']is None for e in cpu)
 selected=[e for e in cpu if start<=e['start_monotonic']<end];timing=stats([e['thread_cpu_ns']/1e6 for e in selected]);assert timing['n']>0
 return {'completed_root_JCT_seconds':jct,'completed_request_TTFT_seconds':ttft,'completed_request_TBT_seconds':tbt,'observed_completed_requests':len(requests),'mean_JCT':jct['mean'],'p95_JCT':jct['p95'],'max_JCT':jct['max'],'schedule_calls_main':len(selected),'scheduler_CPU_P50_ms':timing['p50'],'scheduler_CPU_P95_ms':timing['p95'],'scheduler_CPU_total_seconds':sum(e['thread_cpu_ns']for e in selected)/1e9,'latency_scope':'JCT only fully completed roots; TTFT/TBT only fully completed requests before cutoff; unfinished work is censored','main_duration':H,'full_replay_and_drain_metrics_applicable':False}
