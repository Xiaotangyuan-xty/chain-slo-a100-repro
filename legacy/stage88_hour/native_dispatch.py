"""Existing vLLM FCFS Scheduler, without custom SLO/candidate/prediction installs."""
from pathlib import Path
import atexit,json,hashlib

def install(server,output,*,method,model_key,port,predictor_protocol,timeout_seconds=10.):
    assert method=='native_vllm'
    output=Path(output);stage=output.parents[1]
    from install_suite_runtime import load_common
    common=load_common(stage)
    information,truth=common['oracle_length_adapter'].prepare(server,output)
    assert truth is None and not information['enabled']
    observation=common['execution_observation'].install(output)
    server.use_prediction=False;server.use_graph_matching=False
    active={n:{'path':m.__file__,'sha256':hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()}for n,m in common.items()}
    receipt={'release':'native_vllm','release_commit':None,'method':method,'model_key':model_key,
        'candidate_scheduler_installed':False,'shared_prediction':None,'candidate_receipt':None,
        'stage_budget_adapter':None,'execution_observer':observation,'information_adapter':information,
        'active_modules':active,'common_hashes':{str(Path(v['path']).relative_to(stage)):v['sha256']for v in active.values()},
        'frozen_candidate_modules_exact':True,'candidate_modules_loaded':False,
        'backend':'existing frozen vLLM fork native FCFS branch; not a separate upstream installation',
        'native_scheduler':'vllm.core.scheduler.Scheduler','native_policy':'FCFSPolicy',
        'prediction_enabled':False,'graph_matching_enabled':False,'installer_allocates_GPU':False}
    def write():
        outer=getattr(server,'engine',None);inner=getattr(outer,'engine',outer)
        schedulers=getattr(inner,'scheduler',[])if inner else[]
        rows=[]
        for s in schedulers:
            assert type(s).__module__=='vllm.core.scheduler'and type(s).__name__=='Scheduler'
            assert type(s.policy).__name__=='FCFSPolicy'and not hasattr(s,'cost_model')
            rows.append({'type':type(s).__module__+'.'+type(s).__name__,'policy':type(s.policy).__name__})
        (output/'COMPARISON_SUITE_RUNTIME.json').write_text(json.dumps({**receipt,'schedulers':rows},indent=2)+'\n')
    write();atexit.register(write)
    return receipt
