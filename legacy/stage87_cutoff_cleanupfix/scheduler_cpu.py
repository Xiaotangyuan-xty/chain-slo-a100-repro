"""Observe every real schedule() call, with actual calling-thread CPU time."""
import atexit,functools,json,time
from pathlib import Path

def install(output):
    from vllm.engine.llm_engine import LLMEngine
    output=Path(output)
    assert not getattr(LLMEngine,'_saturation_cpu_observed',False)
    LLMEngine._saturation_cpu_observed=True
    stream=(output/'SCHEDULER_CPU_EVENTS.jsonl').open('x',buffering=1024*1024)
    receipt={'version':'schedule_thread_cpu_v1','clock':'time.thread_time_ns',
        'boundary':'entire actual scheduler.schedule() call; serialization outside boundary',
        'samples':'all calls, including empty calls; main interval selected by monotonic timestamps',
        'calls':0,'failed_calls':0,'CUDA_synchronization_added':False}
    def wrap(prior):
        @functools.wraps(prior)
        def measured(*args,**kwargs):
            start=time.perf_counter();cpu_start=time.thread_time_ns();error=None
            try:return prior(*args,**kwargs)
            except BaseException as exc:error=type(exc).__name__;raise
            finally:
                cpu_ns=time.thread_time_ns()-cpu_start;end=time.perf_counter()
                receipt['calls']+=1;receipt['failed_calls']+=error is not None
                stream.write(json.dumps({'start_monotonic':start,'end_monotonic':end,
                    'thread_cpu_ns':cpu_ns,'wall_seconds':end-start,'error':error})+'\n')
        return measured
    prior_init=LLMEngine.__init__
    @functools.wraps(prior_init)
    def initialized(self,*args,**kwargs):
        prior_init(self,*args,**kwargs)
        for scheduler in self.scheduler:
            scheduler.schedule=wrap(scheduler.schedule)
        receipt['scheduler_types']=[type(s).__module__+'.'+type(s).__name__ for s in self.scheduler]
    LLMEngine.__init__=initialized
    def finish():
        stream.flush();(output/'SCHEDULER_CPU_RUNTIME.json').write_text(json.dumps(receipt,indent=2)+'\n');stream.close()
    atexit.register(finish)
    return receipt
