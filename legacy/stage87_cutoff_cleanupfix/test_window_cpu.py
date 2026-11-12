from pathlib import Path
from types import SimpleNamespace as NS
import asyncio,copy,json,os,sys,time
from unittest.mock import patch
C=Path(sys.argv[1]);mode=sys.argv[2];assert os.environ.get('CUDA_VISIBLE_DEVICES','')==''
if mode=='accounting':
    from window_metrics import classify
    jobs=[];roots=[];tokens={}
    for cid in range(4):
        jobs.append({'collection_id':cid,'request_type':2,'received_slo':[2.,.1,20.],'stages':[[{'request_id':0,'prompt_sha256':'p','target_output_tokens':6}]]})
        roots.append({'collection_id':cid,'request_type':2,'received_slo':[2.,.1,20.],
            'client_chain_start_monotonic':0. if cid<2 else 90.,'client_chain_end_monotonic':10. if cid==0 else 100. if cid==3 else None,
            'success':cid in [0,3],'stages':[{'stage_id':0,'success':True,'requests':[{'request_id':0,'success':True,'input_prompt_sha256':'p','received_slo':[2.,.1,20.],'client_request_start_monotonic':1.,'client_request_end_monotonic':9.}]}]})
        tokens[(cid,0,0)]=(10,5)
    snapshot={'origin_monotonic':0.,'cutoff_monotonic':100.,'roots':roots};work={'main':jobs}
    result=classify(snapshot,work,tokens)
    assert result['fixed_window_settled_credit']==50 and result['completed_chains_before_cutoff']==1
    assert result['definite_SLO_misses_by_cutoff']==1 and result['SLO_outcome_right_censored']==2 and result['unfinished_chains_at_cutoff']==3
    assert sum(r['settled_credit']for r in result['equal_window_bins'])==50
    for label,mutate in [('duplicate',lambda s:s['roots'].append(copy.deepcopy(s['roots'][0]))),('wrong_SLO',lambda s:s['roots'][0].__setitem__('received_slo',[1,1,1])),('unarrived',lambda s:s['roots'][0].__setitem__('client_chain_start_monotonic',101.))]:
        bad=copy.deepcopy(snapshot);mutate(bad)
        try:classify(bad,work,tokens)
        except AssertionError:pass
        else:raise AssertionError(label+' accepted')
    result={'gate':'PASS','half_open_cutoff':True,'no_partial_chain_credit':True,'retokenized_text_counts_used':True,'expired_vs_unresolved_censoring':True,'time_bin_conservation':True,'invalid_records_rejected':True}
elif mode=='guard':
    from cutoff_observation import Window
    out=C/'cpu_attempts/WINDOW_GUARD';out.mkdir();clock=[99.];w=Window(out,100.,clock=lambda:clock[0])
    (out/'MAIN_START.json').write_text(json.dumps({'origin_monotonic':0.,'cutoff_monotonic':100.}))
    calls=[]
    async def model():calls.append(clock[0]);return 1
    async def test():
        guarded=w.guard(model);assert await guarded()==1
        row={'request_uuid':'r','phase':'main','collection_id':1,'stage_id':0,'request_id':0,'output_tokens':0,'prompt_tokens':None,'finished':False};w.rows['r']=row
        assert w.record_output(row,NS(outputs=[NS(token_ids=[11,12])],prompt_token_ids=[1,2,3],finished=False))
        clock[0]=100.001
        assert not w.record_output(row,NS(outputs=[NS(token_ids=[11,12,13])],prompt_token_ids=[1,2,3],finished=True))
        task=asyncio.create_task(guarded());await asyncio.sleep(.01);assert not task.done()and calls==[99.]
        task.cancel();await asyncio.gather(task,return_exceptions=True)
    asyncio.run(test());w.finish();snapshot=json.loads((out/'WINDOW_SERVER_CUTOFF.json').read_text())
    assert snapshot['no_drain']and snapshot['requests'][0]['output_tokens']==2
    result={'gate':'PASS','pre_cutoff_executor_unchanged':True,'post_cutoff_no_new_model_call':True,'post_cutoff_output_excluded':True,'partial_prefix_preserved':True,'cleanup_cancels_held_call_without_draining':True}
elif mode=='transport':
    import aiohttp,window_client,native_graph_observation,saturation_checks
    p=json.loads((C/'PROTOCOL.json').read_text());work=json.loads((C/'WORKLOAD.json').read_text());work=copy.deepcopy(work)
    work['main']=work['main'][:16];p=copy.deepcopy(p);p['cutoff_seconds']=.35
    for i,j in enumerate(work['main']):j['arrival_offset_seconds']=i*.008
    out=C/'cpu_attempts/WINDOW_CLIENT_TRANSPORT';out.mkdir()
    expected={(ph,j['collection_id'],sid,r['request_id']):(i,j,r)for ph in ['warmup','main']for i,j in enumerate(work[ph])for sid,s in enumerate(j['stages'])for r in s}
    starts=[]
    class Content:
        def __init__(self,ph,i,j,r):self.ph=ph;self.i=i;self.j=j;self.r=r
        async def iter_any(self):
            data={'text':[self.r['prompt']+'x'],'ttft':.001,'tbt':[],'service_gain':0}
            yield(json.dumps(data)+'\0').encode()
            await asyncio.sleep(.002 if self.ph=='warmup'or self.i<8 else 2.)
            data['text']=[self.r['prompt']+'x'*self.r['target_output_tokens']];data['tbt']=[.001]*(self.r['target_output_tokens']-1)
            yield(json.dumps(data)+'\0').encode()
    class Response:
        status=200
        def __init__(self,payload):
            info=payload['request_info'];ph='warmup'if payload['client_id']==900000 else'main';key=(ph,info['collection_id'],info['stage_id'],info['request_id']);i,j,r=expected[key]
            assert payload['slo_constraint']==j['received_slo']and info['prompt']==r['prompt']and payload['target_output_length']==r['target_output_tokens']
            starts.append((ph,time.perf_counter()));self.content=Content(ph,i,j,r)
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    class Session:
        def __init__(self,*args,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def post(self,url,json):return Response(json)
    def warmup(out,work,protocol,calls):
        assert native_graph_observation.exact_frozen_pure_warmup(work,calls)
        return {'gate':'PASS','scope':'CPU fake transport only'}
    os.environ['STUDY_ARM']=p['runtime_arm']
    with patch.object(aiohttp,'ClientSession',Session),patch.object(saturation_checks,'qualify_warmup',warmup):asyncio.run(window_client.replay(C.parents[2],C,out,p,work))
    snapshot=json.loads((out/'CLIENT_CUTOFF_SNAPSHOT.json').read_text());done=json.loads((out/'CLIENT_DONE.json').read_text());cut=snapshot['cutoff_monotonic']
    assert snapshot['arrived_roots']==16 and not snapshot['technical_errors_before_cutoff']and done['all_local_tasks_stopped']and done['no_drain']
    assert done['observation_end_monotonic']-cut<.2 and all(t<cut for ph,t in starts if ph=='main')
    completed=[c for c in snapshot['roots']if c['success']and c['client_chain_end_monotonic']<cut]
    assert len(completed)==8 and len(snapshot['roots'])-len(completed)==8
    assert any(r['generated_text']==''for c in snapshot['roots']if not c['success']for s in c['stages']for r in s['requests'])
    result={'gate':'PASS','actual_client_deadline_and_cancel_path':True,'16arrivals_8complete_8censored':True,'no_post_cutoff_requests_or_stage_advance':True,'no_wait_for2second_slow_responses':True,'stop_lag':snapshot['stop_lag_seconds']}
else:raise ValueError(mode)
import torch
assert not torch.cuda.is_initialized();result.update(GPU_used=False,CUDA_context_initialized=False)
print(json.dumps(result),flush=True)
