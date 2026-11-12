"""Common window evidence and a post-cutoff executor barrier; no pre-cutoff policy change."""
from pathlib import Path
import asyncio,atexit,functools,hashlib,json,time

class Window:
    def __init__(self,output,seconds,clock=time.perf_counter):
        self.output=Path(output);self.seconds=seconds;self.clock=clock;self.origin=None;self.deadline=None
        self.closed=False;self.engine=None;self.rows={};self.prefixes={};self.blocked=0;self.resource_samples=0
        self.stream=(self.output/'WINDOW_TOKEN_DELTAS.jsonl').open('x',buffering=1024*1024)
        self.resources=(self.output/'WINDOW_KV_SAMPLES.jsonl').open('x',buffering=1024*1024)
        self.hold=asyncio.Event();atexit.register(self.finish)
    def refresh(self):
        if self.deadline is None and(self.output/'MAIN_START.json').exists():
            p=json.loads((self.output/'MAIN_START.json').read_text());self.origin=p['origin_monotonic'];self.deadline=self.origin+self.seconds
            assert p['cutoff_monotonic']==self.deadline
        return self.deadline
    def sample(self):
        row={'monotonic':self.clock()}
        if self.engine is not None:
            inner=getattr(self.engine,'engine',self.engine);s=inner.scheduler[0];manager=s.block_manager
            row.update(gpu_blocks_free=manager.get_num_free_gpu_blocks(),cpu_blocks_free=manager.get_num_free_cpu_blocks(),
                waiting_groups=len(s.waiting),running_groups=len(s.running),swapped_groups=len(s.swapped),
                queued_root_ids=list({g.collection_id for q in [s.waiting,s.running,s.swapped]for g in q}))
        self.resources.write(json.dumps(row)+'\n');self.resource_samples+=1
        return row
    def trip(self,reason):
        if self.closed:return
        self.closed=True;stamp=self.clock();self.sample()
        for key,ids in self.prefixes.items():self.rows[key]['output_prefix_sha256']=hashlib.sha256(json.dumps([ids]).encode()).hexdigest()
        row={'reason':reason,'planned_cutoff_monotonic':self.deadline,'actual_server_stop_monotonic':stamp,
            'stop_lag_seconds':stamp-self.deadline,'requests':list(self.rows.values()),
            'no_drain':True,'execution_policy':'All subsequent model-executor calls are held until process cleanup; no new GPU work is started by this wrapper.'}
        (self.output/'WINDOW_SERVER_CUTOFF.json').write_text(json.dumps(row)+'\n');self.stream.flush();self.resources.flush()
    async def watch(self):
        while self.refresh()is None:await asyncio.sleep(.1)
        while self.clock()<self.deadline:
            self.sample();await asyncio.sleep(min(5.,max(0.,self.deadline-self.clock())))
        self.trip('deadline_timer')
    def guard(self,prior):
        @functools.wraps(prior)
        async def execute(*args,**kwargs):
            self.refresh()
            if self.deadline is not None and(self.closed or self.clock()>=self.deadline):
                self.trip('executor_deadline_guard');self.blocked+=1
                await self.hold.wait()
                raise AssertionError('Cutoff barrier must never be released')
            return await prior(*args,**kwargs)
        return execute
    def record_output(self,row,output):
        stamp=self.clock();self.refresh()
        if row['phase']=='main'and self.deadline is not None and stamp>=self.deadline:
            self.trip('output_cutoff');return False
        ids=output.outputs[0].token_ids;previous=row['output_tokens']
        assert len(ids)>=previous
        delta=list(ids[previous:]);self.prefixes.setdefault(row['request_uuid'],[]).extend(delta)
        row.update(output_tokens=len(ids),last_monotonic=stamp,finished=bool(output.finished))
        if row['prompt_tokens']is None:
            row.update(prompt_tokens=len(output.prompt_token_ids),prompt_token_ids_sha256=hashlib.sha256(json.dumps(list(output.prompt_token_ids)).encode()).hexdigest())
        if delta:self.stream.write(json.dumps({'monotonic':stamp,'request_uuid':row['request_uuid'],'phase':row['phase'],
            'collection_id':row['collection_id'],'stage_id':row['stage_id'],'request_id':row['request_id'],
            'previous_tokens':previous,'new_token_ids':delta,'output_tokens':len(ids)})+'\n')
        return True
    def finish(self):
        if self.stream.closed:return
        self.stream.flush();self.resources.flush()
        (self.output/'WINDOW_OBSERVATION_RUNTIME.json').write_text(json.dumps({'version':'fixed_hour_cutoff_v1',
            'cutoff_monotonic':self.deadline,'closed':self.closed,'blocked_post_cutoff_executor_calls':self.blocked,
            'resource_samples':self.resource_samples,'CUDA_synchronization_added':False,'no_pre_cutoff_scoring_or_admission_change':True})+'\n')
        self.stream.close();self.resources.close()

def install(server,engine_class,output,protocol):
    window=Window(output,protocol['cutoff_seconds'])
    previous=engine_class.generate
    @functools.wraps(previous)
    async def generate(self,prompt,info,sampling_params,request_id,*args,**kwargs):
        row={'request_uuid':request_id,'phase':'warmup'if info.client_id==900000 else'main','collection_id':info.collection_id,
            'stage_id':info.stage_id,'request_id':info.request_id,'start_monotonic':time.perf_counter(),
            'prompt_sha256':hashlib.sha256(str(prompt).encode()).hexdigest(),'received_slo':list(info.slo_constraint),
            'output_tokens':0,'finished':False,'prompt_tokens':None}
        window.rows[request_id]=row
        async for result in previous(self,prompt,info,sampling_params,request_id,*args,**kwargs):
            if not window.record_output(row,result):break
            yield result
    engine_class.generate=generate
    from vllm.engine.llm_engine import LLMEngine
    original_init=LLMEngine.__init__
    @functools.wraps(original_init)
    def initialized(self,*args,**kwargs):
        original_init(self,*args,**kwargs)
        self.model_executor.execute_model_async=window.guard(self.model_executor.execute_model_async)
    LLMEngine.__init__=initialized
    return window
