"""CPU replay of the actual native HTTP handler and real prediction threads."""
import asyncio
from collections import Counter
import copy, hashlib, json, os
from pathlib import Path
import sys, threading, time
from unittest.mock import patch

assert os.environ.get('CUDA_VISIBLE_DEVICES','')==''
C=Path(sys.argv[1]);mode=sys.argv[2]
assert mode in ['early','late','overlap','original_early_failure']
from jitserve import server
from install_suite_runtime import install
from stage_replay import payload_for
assert Path(server.__file__).resolve()==(C/'runtime_repo/jitserve/server.py').resolve()

server.graph_ctx=None
server.use_prediction=True
server.use_default_length=False
server.use_graph_matching=False
p=json.loads((C/'PROTOCOL.json').read_text())
work=json.loads((C/'WORKLOAD.json').read_text())
out=C/'cpu_attempts'/('REAL_NATIVE_ORDER_'+mode);out.mkdir()
receipt=install(server,out,method=p['candidate_version'],model_key='llama8',
    port=p['prediction_ports'][p['runtime_arm']],predictor_protocol=p['predictor_protocol'])
assert receipt['frozen_candidate_modules_exact']
assert receipt['information_adapter']['enabled']
expected={}
payloads=[]
for phase in ['warmup','main']:
    for job in work[phase]:
        for sid,stage in enumerate(job['stages']):
            for member in stage:
                payload=payload_for(job,sid,member,phase)
                payload['stream']=False
                identity=(phase+':'+str(job['collection_id']),sid,member['request_id'])
                expected[identity]=member['target_output_tokens']
                payloads.append((identity,payload))
if mode=='original_early_failure':
    payloads=payloads[:1]
    expected={payloads[0][0]:expected[payloads[0][0]]}

provider=server._length_oracle_predictor
provider_entries=[]
def observed_provider(info):
    provider_entries.append({'key_present':hasattr(info,'_oracle_root_key'),
        'root':getattr(info,'_oracle_root_key',None),'stage':info.stage_id,'member':info.request_id})
    return provider(info)
server._length_oracle_predictor=observed_provider
RealThread=threading.Thread
pending=[]
release=threading.Event()
captured=[]
arrivals={}

class ControlledThread:
    def __init__(self,target=None,args=(),daemon=None,**kwargs):
        def body():
            if mode in ['late','overlap']:
                assert release.wait(15), 'Controlled prediction release timed out'
            target(*args)
        self.thread=RealThread(target=body,daemon=daemon,**kwargs)
    def start(self):
        pending.append(self);self.thread.start()
        if mode in ['early','original_early_failure']:
            self.join(10)
    def join(self,timeout=None):
        self.thread.join(timeout)
        assert not self.thread.is_alive(), 'Prediction thread did not finish'

class ReachedActualEngineBoundary(Exception):
    pass

class NoModelEngine:
    def generate(self,prompt,info,sampling_params,request_id,client_id):
        captured.append(info)
        if mode=='late':
            release.set()
            for thread in pending:thread.join(10)
        raise ReachedActualEngineBoundary()

server.engine=NoModelEngine()
class ReceivedRequest:
    def __init__(self,identity,payload):self.identity=identity;self.payload=payload
    async def json(self):
        arrivals.setdefault(self.identity[0],time.perf_counter())
        return copy.deepcopy(self.payload)

async def request(identity,payload):
    # This invokes native generate(), including native parse, deadline setup,
    # _maybe_start_prediction, collective handling and engine.generate ordering.
    try:
        await server.generate(ReceivedRequest(identity,payload))
    except ReachedActualEngineBoundary:
        return
    raise AssertionError('Actual native handler did not reach its engine boundary')

with patch.object(server.threading,'Thread',ControlledThread):
    if mode=='overlap':
        for start in range(0,len(payloads),16):
            batch=payloads[start:start+16];release.clear();pending.clear()
            for identity,payload in batch:asyncio.run(request(identity,payload))
            release.set()
            for thread in pending:thread.join(10)
    else:
        for identity,payload in payloads:
            release.clear();pending.clear();asyncio.run(request(identity,payload))
            for thread in pending:thread.join(10)

shared=[json.loads(line)for line in(out/'SHARED_PREDICTION_EVENTS.jsonl').read_text().splitlines()]
counts=Counter(e['kind']for e in shared)
oracle=[json.loads(line)for line in(out/'ORACLE_EVENTS.jsonl').read_text().splitlines()]
(out/'CPU_RECEIVED_REQUESTS.json').write_text(json.dumps(arrivals,indent=2)+'\n')
if mode=='original_early_failure':
    assert counts=={'prediction_fallback':1}
    assert shared[0]['error_type']=='AttributeError' and '_oracle_root_key'in shared[0]['error']
    assert provider_entries==[{'key_present':False,'root':None,'stage':payloads[0][0][1],'member':payloads[0][0][2]}]
    result={'gate':'PASS','expected_original_lifecycle_failure_reproduced':True,
        'actual_native_handler_used':True,'real_prediction_thread_forced_before_collective':True}
else:
    assert counts=={'prediction_success':len(expected)},counts
    assert all(e['key_present']for e in provider_entries)
    assert len(captured)==len(expected)
    for (identity,_),info in zip(payloads,captured):
        assert info._oracle_root_key==identity[0]
        assert info.output_len==expected[identity]
        assert info.prediction_status=='ready'
    activated={};bound={};seen=set()
    for e in oracle:
        key=e['root']
        if e['kind']=='root_activated':
            assert key not in activated and e['monotonic']>=arrivals[key]
            activated[key]=e['monotonic'];continue
        assert key in activated and e['monotonic']>=activated[key]
        if e['kind']=='request_bound':
            identity=(key,e['stage_id'],e['request_id'])
            assert identity in expected and identity not in bound
            bound[identity]=e['monotonic']
        if e['kind']=='request_prediction':
            identity=(key,e['stage_id'],e['request_id'])
            assert identity in bound and bound[identity]<=e['monotonic']
            assert identity not in seen and e['prediction']==expected[identity]
            seen.add(identity)
    assert seen==set(bound)==set(expected)
    assert set(activated)==set(arrivals)
    result={'gate':'PASS','mode':mode,'actual_native_handler_used':True,
        'real_prediction_threads':True,'all_frozen_payloads':len(expected),
        'exact_predictions_no_fallback':True,'binding_precedes_prediction':True,
        'activation_after_actual_received_JSON':True,'all_frozen_root_namespaces':len(activated)}
import torch
assert not torch.cuda.is_initialized()
result.update(GPU_used=False,CUDA_context_initialized=False,
    native_handler_path=str(Path(server.__file__).resolve()),
    native_handler_file_sha256=hashlib.sha256(Path(server.__file__).read_bytes()).hexdigest())
print(json.dumps(result),flush=True)
