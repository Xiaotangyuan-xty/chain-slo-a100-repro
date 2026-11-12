"""Read-only real Oracle lifecycle evidence, including incomplete live logs."""
from pathlib import Path
from collections import Counter
from datetime import datetime,timezone
import json,sys

S=Path(sys.argv[1])
def read(p):return json.loads(p.read_text()) if p.exists() else None
def lines(p):
    result=[]
    if p.exists():
        for line in p.open():
            try:result.append(json.loads(line))
            except json.JSONDecodeError:pass
    return result
cases=[]
for spec in read(S/'MATRIX.json')['cases']:
    C=Path(spec['stage']);A=C/'attempts'/spec['attempt'];work=read(C/'WORKLOAD.json')
    events=lines(A/'ORACLE_EVENTS.jsonl');shared=lines(A/'SHARED_PREDICTION_EVENTS.jsonl')
    warmup=[e for e in events if e.get('root','').startswith('warmup:')]
    expected={(f"warmup:{job['collection_id']}",sid,r['request_id']) for job in work['warmup'] for sid,stage in enumerate(job['stages']) for r in stage}
    bound={};seen={};bad=[]
    for e in events:
        if e['kind'] in ['request_bound','request_prediction']:
            identity=(e['root'],e['stage_id'],e['request_id'])
            if e['kind']=='request_bound':bound[identity]=e['monotonic']
            else:
                if identity not in bound or bound[identity]>e['monotonic']:bad.append(identity)
                seen[identity]=e['monotonic']
    warm_bound={i for i in bound if i[0].startswith('warmup:')};warm_seen={i for i in seen if i[0].startswith('warmup:')}
    cases.append({'case':C.name,'attempt':spec['attempt'],'case_status':read(C/'CASE_STATUS.json'),
        'controller':read(A/'controller_status.json'),'warmup_gate':read(A/'WARMUP_NATIVE_TOT_GATE.json'),
        'MAIN_START':read(A/'MAIN_START.json'),'INFORMATION_ADAPTER':read(A/'INFORMATION_ADAPTER.json'),
        'oracle_event_counts':dict(Counter(e['kind']for e in events)),
        'shared_prediction_counts':dict(Counter(e['kind']for e in shared)),
        'fallback_events':[e for e in shared if e['kind']=='prediction_fallback'],
        'warmup_oracle_event_counts':dict(Counter(e['kind']for e in warmup)),
        'warmup_exact_binding_and_prediction_identities':warm_bound==warm_seen==expected,
        'all_observed_predictions_after_binding':not bad,
        'first_oracle_events':events[:5],
        'controller_failure':read(A/'CONTROLLER_FAILURE.json')})
print(json.dumps({'utc':datetime.now(timezone.utc).isoformat(),'read_only':True,'study':str(S),'cases':cases}))
