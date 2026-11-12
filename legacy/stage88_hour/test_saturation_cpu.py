"""CPU-only real FCFS scheduling and actual-client transport qualification."""
from pathlib import Path
import asyncio,copy,json,os,sys
from unittest.mock import patch
C=Path(sys.argv[1]);mode=sys.argv[2]
assert os.environ.get('CUDA_VISIBLE_DEVICES','')==''
p=json.loads((C/'PROTOCOL.json').read_text());w=json.loads((C/'WORKLOAD.json').read_text())
if mode=='native':
    from jitserve import server
    from install_suite_runtime import install
    out=C/'cpu_attempts/NATIVE_FCFS_STANDALONE';out.mkdir()
    receipt=install(server,out,method='native_vllm',model_key='llama8',port=p['prediction_ports'][p['runtime_arm']],predictor_protocol=p['predictor_protocol'])
    assert not receipt['candidate_scheduler_installed']and not receipt['prediction_enabled']and not receipt['graph_matching_enabled']
    assert not hasattr(server,'_length_oracle_predictor')
    from vllm.core.scheduler import Scheduler
    from vllm.config import SchedulerConfig,CacheConfig
    from vllm.sequence import SequenceStatus
    from jitserve.request_info import RequestInfo,RequestType
    from vllm.sequence import Sequence,SequenceGroup,Logprob
    from vllm import SamplingParams
    class NativeFixture:
        def setUp(self):
            self.wall=patch('time.time',return_value=100.);self.clock=patch('time.perf_counter',return_value=1000.)
            self.wall.start();self.clock.start()
        def doCleanups(self):self.wall.stop();self.clock.stop()
        def group(self,rid,kind=2,prompt=32,cid=0,stage=0,width=1,deadline=3600.):
            info=RequestInfo(RequestType(kind),(3600.,3600.,3600.),0,cid,3,prompt,3600.,stage_id=stage,request_id=0)
            info.chain_deadline=deadline;info.chain_stage_count=stage+1;info.chain_stage_widths=[1]*stage+[width]
            seq=Sequence(rid,inputs={'prompt_token_ids':list(range(prompt)),'prompt':'CPU'},block_size=16)
            return SequenceGroup(str(rid),[seq],100.,info,SamplingParams(temperature=0,max_tokens=3,ignore_eos=True))
        def step(self,scheduler):
            _,out,_=scheduler.schedule()
            for item in out.scheduled_seq_groups:
                g=item.seq_group;g.update_num_computed_tokens(item.token_chunk_size)
                if not g.is_prefill():g.first_seq.append_token_id(1,{1:Logprob(0.)})
            return out
        def cleanup(self,scheduler):
            scheduler.abort_seq_group([g.request_id for q in (scheduler.running,scheduler.waiting,scheduler.swapped)for g in q])
            assert scheduler.block_manager.get_num_free_gpu_blocks()==scheduler.block_manager.num_total_gpu_blocks
    fixture=NativeFixture();fixture.setUp()
    cache=CacheConfig(16,.85,1,'auto');cache.num_gpu_blocks=11357;cache.num_cpu_blocks=512
    config=SchedulerConfig('generate',2048,32,8192,enable_chunked_prefill=True,policy='fcfs')
    scheduler=Scheduler(config,cache,None)
    assert type(scheduler.policy).__name__=='FCFSPolicy'and not hasattr(scheduler,'cost_model')
    import vllm.engine.llm_engine as engine
    def dummy_init(self):self.scheduler=[scheduler]
    engine.LLMEngine.__init__=dummy_init
    from scheduler_cpu import install as install_cpu
    cpu=install_cpu(out);engine.LLMEngine()
    groups={};added={j['collection_id']:0 for j in w['main']};jobs={j['collection_id']:j for j in w['main']}
    def add(job,sid):
        cid=job['collection_id'];widths=list(map(len,job['stages']))
        for member in job['stages'][sid]:
            rid=f"{cid}:{sid}:{member['request_id']}"
            g=fixture.group(rid,2,prompt=32,cid=cid,stage=sid,width=widths[sid],deadline=3600.*len(widths))
            g.request_info.request_id=member['request_id'];g.request_info.slo_constraint=(3600.,3600.,3600.)
            g.request_info.chain_stage_count=len(widths);g.request_info.chain_stage_widths=widths
            scheduler.add_seq_group(g);groups[rid]=g
    try:
        for job in w['main']:add(job,0)
        for tick in range(3000):
            fixture.step(scheduler)
            for g in groups.values():
                if g.first_seq.get_output_len()>=3:g.first_seq.status=SequenceStatus.FINISHED_LENGTH_CAPPED
            scheduler.free_finished_seq_groups()
            live_roots={g.collection_id for q in [scheduler.running,scheduler.waiting,scheduler.swapped]for g in q}
            for cid,job in jobs.items():
                sid=added[cid]
                if cid not in live_roots and sid+1<len(job['stages']):add(job,sid+1);added[cid]+=1
            if not(scheduler.running or scheduler.waiting or scheduler.swapped):break
        assert tick<2999 and len(groups)==p['expected_main_requests'] and all(g.first_seq.is_finished()for g in groups.values())
        fixture.cleanup(scheduler);assert scheduler.block_manager.get_num_free_cpu_blocks()==512
        assert cpu['calls']==tick+1 and cpu['failed_calls']==0
    finally:fixture.doCleanups()
    result={'gate':'PASS','real_native_FCFS_scheduler':True,'real_policy_FCFS':True,'all200_roots_and1197_stage_dependent_groups':True,'all_KV_released':True,'thread_CPU_observer_on_real_scheduler':True,'no_prediction_or_candidate_install':True,'scheduler_calls':cpu['calls']}
elif mode=='transport':
    import aiohttp
    import client,saturation_checks
    out=C/'cpu_attempts/CLIENT_BURST_TRANSPORT';out.mkdir()
    expected={(phase,j['collection_id'],sid,r['request_id']):(j,r)for phase in ['warmup','main']for j in w[phase]for sid,s in enumerate(j['stages'])for r in s}
    observed={};active=set();peak=0;finished_members=set()
    class Content:
        def __init__(self,blob):self.blob=blob
        async def iter_any(self):
            await asyncio.sleep(0)
            yield self.blob
    class Response:
        status=200
        def __init__(self,payload):
            info=payload['request_info'];phase='warmup'if payload['client_id']==900000 else'main';self.key=(phase,info['collection_id'],info['stage_id'],info['request_id'])
            job,r=expected[self.key]
            assert self.key not in observed and info['prompt']==r['prompt']and payload['slo_constraint']==[3600.,3600.,3600.]and payload['target_output_length']==r['target_output_tokens']
            observed[self.key]=payload
            data={'text':[r['prompt']+'x'*r['target_output_tokens']],'ttft':.001,'tbt':[.001]*(r['target_output_tokens']-1),'service_gain':0}
            self.content=Content((__import__('json').dumps(data)+'\0').encode())
        async def __aenter__(self):
            global peak
            if self.key[0]=='main':active.add(self.key[1]);peak=max(peak,len(active))
            return self
        async def __aexit__(self,*args):
            if self.key[0]=='main':
                finished_members.add(self.key)
                job,_=expected[self.key];cid=self.key[1];sid=len(job['stages'])-1
                if all(('main',cid,sid,r['request_id'])in finished_members for r in job['stages'][sid]):active.discard(cid)
    class Session:
        def __init__(self,*args,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def post(self,url,json):return Response(copy.deepcopy(json))
    def warmup(out,work,protocol,calls):
        from native_graph_observation import exact_frozen_pure_warmup
        assert exact_frozen_pure_warmup(work,calls)
        return {'gate':'PASS','scope':'CPU fake transport only; not actual GPU warmup'}
    os.environ['STUDY_ARM']=p['runtime_arm']
    with patch.object(aiohttp,'ClientSession',Session),patch.object(saturation_checks,'qualify_warmup',warmup):
        asyncio.run(client.run(C.parents[2],C,out))
    calls=json.loads((out/'client_calls.json').read_text());main=[c for c in calls if c['phase']=='main']
    assert len(main)==200 and set(observed)==set(expected)and peak==200
    assert max(c['arrival_offset_seconds']for c in main)<=.5
    assert all(max(r['client_request_end_monotonic']for r in a['requests'])<=min(r['client_request_start_monotonic']for r in b['requests'])for c in calls for a,b in zip(c['stages'],c['stages'][1:]))
    result={'gate':'PASS','actual_client_run':True,'all200_roots_common_release':True,'all1197_main_payloads_exact':True,'all_stage_barriers':True,'max_CPU_release_error_seconds':max(c['arrival_offset_seconds']for c in main),'transport_only_no_GPU_claim':True}
elif mode=='metric':
    from saturation_gate import summarize_schedule
    events=[{'start_monotonic':i,'end_monotonic':i+.01,'thread_cpu_ns':int((i+1)*1e6),'wall_seconds':.01,'error':None}for i in range(10)]
    receipt={'version':'schedule_thread_cpu_v1','clock':'time.thread_time_ns','calls':10,'failed_calls':0,'CUDA_synchronization_added':False}
    m=summarize_schedule(events,2.,9.,receipt)
    assert m['schedule_calls_main']==7 and m['scheduler_CPU_P50_ms']==6. and abs(m['scheduler_CPU_P95_ms']-8.7)<1e-9
    try:summarize_schedule(events[:-1],2.,9.,receipt)
    except AssertionError:pass
    else:raise AssertionError('Missing CPU sample accepted')
    result={'gate':'PASS','thread_CPU_not_host_elapsed':True,'warmup_and_post_completion_excluded':True,'all_main_calls_included':True,'P50_P95_linear_interpolation':True,'missing_events_rejected':True}
else:raise ValueError(mode)
import torch
assert not torch.cuda.is_initialized()
result.update(GPU_used=False,CUDA_context_initialized=False)
print(json.dumps(result),flush=True)
