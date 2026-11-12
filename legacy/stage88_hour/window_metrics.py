"""Right-censored fixed-window chain credit; no reward for unfinished chains."""
import hashlib
def classify(snapshot,work,request_tokens):
    start=snapshot['origin_monotonic'];end=snapshot['cutoff_monotonic'];H=snapshot.get('window_seconds',end-start)
    jobs={j['collection_id']:j for j in work['main']};seen=set();credit=0;complete=met=expired=0;censored=0
    settlements=[];arrivals=[];finishes=[]
    for c in snapshot['roots']:
        cid=c['collection_id'];assert cid in jobs and cid not in seen;seen.add(cid);job=jobs[cid]
        assert c['request_type']==job['request_type']==2 and c['received_slo']==job['received_slo']
        arrived=c['client_chain_start_monotonic'];assert start<=arrived<end
        arrivals.append(arrived-start)
        done=c['client_chain_end_monotonic'];finished=c['success']and done is not None and done<end
        if finished:
            complete+=1;finishes.append(done-start);reward=0
            assert len(c['stages'])==len(job['stages'])
            for sid,(stage,frozen)in enumerate(zip(c['stages'],job['stages'])):
                assert stage['stage_id']==sid and stage['success']
                wanted={r['request_id']:r for r in frozen};actual={r['request_id']:r for r in stage['requests']}
                assert set(wanted)==set(actual)
                for member,r in actual.items():
                    assert r['success']and r['input_prompt_sha256']==wanted[member]['prompt_sha256']and r['received_slo']==job['received_slo']
                    assert r['client_request_end_monotonic']<end
                    inp,out=request_tokens[(cid,sid,member)]
                    assert inp>=0 and out>=0;reward+=inp+8*out
            for left,right in zip(c['stages'],c['stages'][1:]):
                assert max(r['client_request_end_monotonic']for r in left['requests'])<=min(r['client_request_start_monotonic']for r in right['requests'])
            if done-arrived<=job['received_slo'][2]*len(job['stages']):
                met+=1;credit+=reward;settlements.append({'collection_id':cid,'settle_seconds':done-start,'credit':reward})
            else:expired+=1
        elif arrived+job['received_slo'][2]*len(job['stages'])<=end:expired+=1
        else:censored+=1
    bins=[]
    for k in range(12):
        left=k*H/12;right=(k+1)*H/12;amount=sum(r['credit']for r in settlements if left<=r['settle_seconds']<right)
        bins.append({'start_seconds':left,'end_seconds':right,'settled_credit':amount,'credit_per_second':amount/(right-left),
            'arrived_roots':sum(t<right for t in arrivals),'finished_roots':sum(t<right for t in finishes),
            'unfinished_roots':sum(t<right for t in arrivals)-sum(t<right for t in finishes)})
    return {'fixed_window_settled_credit':credit,'fixed_window_credit_per_second':credit/H,'window_seconds':H,
        'arrived_roots':len(seen),'completed_chains_before_cutoff':complete,'SLO_attained_chains_before_cutoff':met,
        'definite_SLO_misses_by_cutoff':expired,'SLO_outcome_right_censored':censored,
        'unfinished_chains_at_cutoff':len(seen)-complete,'no_drain':True,
        'SLO_attainment_lower_bound':met/len(seen)if seen else 0.,'SLO_attainment_upper_bound':(met+censored)/len(seen)if seen else 0.,
        'equal_window_bins':bins,'settlements':settlements}
