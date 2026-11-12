"""Information-boundary and generic frozen pure-chain final checks."""
from collections import Counter
import hashlib
import json


def validate(stage, attempt, work):
    suite = json.loads((stage/'SUITE_SPEC.json').read_text())
    mode = suite.get('information_mode','predicted')
    receipt = json.loads((attempt/'INFORMATION_ADAPTER.json').read_text())
    checks = {'declared_information_mode':receipt['enabled']==(mode=='oracle'),
              'no_future_arrivals_or_execution_time':not receipt['future_arrivals_accessed'] and not receipt['true_execution_times_accessed'],
              'no_future_input_truth':not receipt['future_input_tokens_accessed'],
              'published_candidate_files_unchanged_by_adapter':not receipt['frozen_candidate_files_modified'],
              'same_score_and_service_time_model':not receipt['score_formula_changed']}
    if mode == 'oracle':
        table = json.loads((stage/'ORACLE_LENGTHS.json').read_text())
        expected = {phase+':'+str(j['collection_id']):[[r['target_output_tokens']for r in s]for s in j['stages']]
                    for phase in ['warmup','main']for j in work[phase]}
        checks['length_truth_table_exact_and_only_lengths'] = set(table)=={'schema','roots'} and table['roots']==expected
        checks['oracle_lengths_frozen_hash'] = hashlib.sha256((stage/'ORACLE_LENGTHS.json').read_bytes()).hexdigest()==suite['oracle_lengths_sha256']==receipt['oracle_lengths_sha256']
        expected_ids={(key,sid,i)for key,stages in expected.items()for sid,s in enumerate(stages)for i in range(len(s))}
        active={};seen=set();bad=[];samples=0
        for line in (attempt/'ORACLE_EVENTS.jsonl').open():
            e=json.loads(line);key=e['root']
            if e['kind']=='root_activated':active[key]=e['monotonic'];continue
            if key not in active or active[key]>e['monotonic']:bad.append('unarrived_root')
            if e['kind']=='request_prediction':
                identity=(key,e['stage_id'],e['request_id'])
                if identity in seen or e['prediction']!=expected[key][e['stage_id']][e['request_id']]:bad.append('wrong_or_duplicate_length')
                seen.add(identity)
            elif e['kind']=='remaining_sample':
                samples+=1
                if e['true_total']!=expected[key][e['stage_id']][e['request_id']] or e['remaining']!=e['true_total']-e['generated']:bad.append('wrong_remaining')
        counts=receipt['counts']
        checks.update(oracle_actual_prediction_identities_exact=seen==expected_ids,
                      oracle_activated_only_after_actual_root_arrival=not bad and len(active)==len(expected),
                      oracle_remaining_lengths_reach_real_forecaster=counts.get('forecast_calls',0)>0 and counts.get('future_stage_length_reads',0)>0 and samples>0,
                      oracle_no_unarrived_length_access=counts.get('unarrived_root_access_rejected',0)==0,
                      oracle_not_rewriting_input_or_service=not receipt['input_forecast_changed']and not receipt['service_time_model_changed'],
                      oracle_native_runtime_truth_declaration=json.loads((attempt/'V47PRO_RUNTIME.json').read_text())['future_truth_access'] is True)
    else:
        checks['ordinary_uses_predicted_information'] = not receipt['future_output_lengths_accessed'] and not (attempt/'ORACLE_EVENTS.jsonl').exists()
    return checks
