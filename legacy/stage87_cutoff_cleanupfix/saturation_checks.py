"""Warmup gates for saturated replay; native branch has no prediction requirement."""
from pathlib import Path
import json

def qualify_warmup(output,work,protocol,calls):
    from native_graph_observation import qualify_warmup as old,exact_frozen_pure_warmup
    output=Path(output);native=protocol['candidate_version']=='native_vllm'
    if not native:
        result=old(output,work,protocol,calls)
    else:
        rows=[json.loads(line)for line in(output/'common_events.jsonl').read_text().splitlines()]
        ready=[r for r in rows if r['kind']=='engine_ready'];devices=[r for r in rows if r['kind']=='device_identity']
        suite=json.loads((output/'COMPARISON_SUITE_RUNTIME.json').read_text())
        live=json.loads((output/'LIVE_EXECUTOR_OBSERVATION.json').read_text())
        checks={'warmup_exact_frozen_cohort':exact_frozen_pure_warmup(work,calls),
            'warmup_TBT_coverage':all(r['success']and len(r['server_tbt'])==r['target_output_tokens']-1 for c in calls if c['phase']=='warmup'for s in c['stages']for r in s['requests']),
            'native_FCFS_runtime':len(ready)==1 and ready[0]['scheduler_type']=='vllm.core.scheduler.Scheduler'and ready[0]['policy_type'].endswith('.FCFSPolicy'),
            'same_model_resources':len(ready)==1 and all(ready[0].get(k)==v for k,v in protocol['expected_resource_caps'].items()),
            'assigned_GPU':len(devices)==1 and devices[0]['actual_uuid']==protocol['resources']['gpu_uuid'],
            'no_candidate_or_prediction':suite['method']=='native_vllm'and not suite['candidate_scheduler_installed']and not suite['candidate_modules_loaded']and not suite['prediction_enabled']and not suite['graph_matching_enabled'],
            'real_executor_before_main':live['executor_hooked']and live['execution_observer']['events']>0 and live['execution_observer']['failed_calls']==0,
            'oracle_disabled':not suite['information_adapter']['enabled']}
        result={'checks':checks,'method':'native_vllm','warmup_excluded_from_main_metric':True}
    live=json.loads((output/'LIVE_EXECUTOR_OBSERVATION.json').read_text())
    result['checks']['thread_CPU_observer_installed_before_main']=live['schedule_cpu']['version']=='schedule_thread_cpu_v1'and live['schedule_cpu']['calls']>0 and live['schedule_cpu']['failed_calls']==0
    result.update(gate='PASS'if all(result['checks'].values())else'FAIL',main_GPU_replay_may_proceed=all(result['checks'].values()))
    if result['gate']!='PASS':
        (output/'WARMUP_NATIVE_TOT_GATE.json').write_text(json.dumps(result,indent=2)+'\n')
        raise RuntimeError('Saturation warmup failed: '+repr(result))
    return result
