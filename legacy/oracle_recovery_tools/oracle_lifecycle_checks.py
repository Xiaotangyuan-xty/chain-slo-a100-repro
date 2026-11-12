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
