"""Offline-only checks; client arrival times are never provided to the Oracle."""
def lifecycle_checks(receipt, events, work, calls):
    expected={(phase+':'+str(job['collection_id']),sid,r['request_id'])
        for phase in ['warmup','main']for job in work[phase]
        for sid,stage in enumerate(job['stages'])for r in stage}
    roots={key for key,_,_ in expected}
    arrivals={c['phase']+':'+str(c['collection_id']):c['client_chain_start_monotonic']for c in calls}
    activated={};bound={};predicted=set();bad=[]
    for e in events:
        key=e.get('root');stamp=e.get('monotonic')
        if key not in roots or stamp is None:
            bad.append('unknown_root_or_timestamp');continue
        if e['kind']=='root_activated':
            if key in activated or key not in arrivals or stamp<arrivals[key]:
                bad.append('activation_before_actual_client_arrival_or_duplicate')
            activated[key]=stamp
            continue
        if key not in activated or stamp<activated[key]:
            bad.append('event_before_root_activation')
        if e['kind'] in ['request_bound','request_prediction']:
            identity=(key,e['stage_id'],e['request_id'])
            if identity not in expected:bad.append('unknown_request_identity')
            if e['kind']=='request_bound':
                if identity in bound:bad.append('duplicate_binding')
                bound[identity]=stamp
            else:
                if identity not in bound or bound[identity]>stamp:bad.append('prediction_before_binding')
                if identity in predicted:bad.append('duplicate_prediction')
                predicted.add(identity)
    return {
        'oracle_root_binding_hook_declared':receipt.get('request_root_binding')=={
            'hook':'_build_request_info','timing':'after_received_request_parse_before_prediction_thread'},
        'oracle_each_request_bound_before_prediction':not bad and set(bound)==predicted==expected,
        'oracle_root_activation_after_actual_client_arrival':not bad and set(activated)==roots and set(arrivals)==roots,
        'oracle_exact_request_binding_count':receipt.get('counts',{}).get('request_bindings')==len(expected),
    }

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
    if mode == 'oracle':
        calls=json.loads((attempt/'client_calls.json').read_text())
        events=[json.loads(line)for line in(attempt/'ORACLE_EVENTS.jsonl').open()]
        checks.update(lifecycle_checks(receipt,events,work,calls))
    return checks
