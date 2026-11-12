"""Preserve the dead import-only runner and let its CPU watcher exit normally."""
from pathlib import Path
import json,shlex,subprocess
D=Path(__file__).resolve().parent;prep=json.loads((D/'CPU_PREPARATION_RECEIPT.json').read_text())
code=r'''
from pathlib import Path
from datetime import datetime,timezone
import json,os,sys
S=Path(json.load(sys.stdin)['study']);sys.path.insert(0,str(S/'common/programs'))
from handoff import alive
from bundle_runtime import read,dump
assert not alive(read(S/'RUNNER_LAUNCH.json'))
specs=read(S/'MATRIX.json')['cases'];assert len(specs)==78 and all(not list((Path(s['stage'])/'attempts').iterdir())for s in specs)
original=read(S/'STUDY_STATUS.json');assert original['state']=='PREPARED'
log=(S/'RUNNER.log').read_text();assert 'ModuleNotFoundError: No module named \'execution_base\''in log
failure={'utc':datetime.now(timezone.utc).isoformat(),'type':'PACKAGING_IMPORT_FAILURE_BEFORE_GPU','error':'Missing execution_base.py in new runtime bundle','runner_log':log,'original_study_status':original,'GPU_used':False,'MAIN_started':False,'model_loaded':False,'attempt_directories_created':0,'original_evidence_preserved':True,'next_action':'Prepare fresh v2 with dependency restored and explicit runner import qualification; never re-arm v1'}
dump(S/'FAILED_STARTUP.json',failure);dump(S/'HOLD.json',failure)
dump(S/'STUDY_STATUS.json',{**original,'state':'NEEDS_ATTENTION','phase':'IMPORT_FAILURE_PRESERVED_NO_GPU','error':failure['error'],'updated_utc':failure['utc']})
print(json.dumps({'gate':'PRESERVED','study':str(S),'GPU_used':False,'attempts':0,'no_signals_sent':True}))
'''
r=subprocess.run(['ssh','-o','ConnectTimeout=12','gpu-node1','CUDA_VISIBLE_DEVICES= PYTHONDONTWRITEBYTECODE=1 python3 -c '+shlex.quote(code)],input=json.dumps(prep),capture_output=True,text=True,timeout=60)
(D/'PRESERVED_STARTUP_FAILURE.json').write_text(r.stdout);assert r.returncode==0,r.stderr;print(r.stdout)
