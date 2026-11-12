"""Protected once-only launch for the human-authorized second Oracle recovery."""
from pathlib import Path
import argparse, hashlib, json, shlex, subprocess

D=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('action',choices=['check','advance']);args=p.parse_args()
m=json.loads((D/'GPU1_ORDER_RECOVERY_MANIFEST.json').read_text())
q=json.loads((D/'COMPARISON_SOURCE_CPU_QUALIFICATION.json').read_text())
assert q['gate']=='PASS' and m['repair_generation']==2
assert m['human_authorization']['authorized_repair_generation']==2
for name,expected in q['program_sha256'].items():
    assert hashlib.sha256((D/name).read_bytes()).hexdigest()==expected
source="""from pathlib import Path
import contextlib,io,json,subprocess,sys
S=Path(sys.argv[1]);expected=sys.argv[2];check_only=sys.argv[3]=='check'
sys.path.insert(0,str(S/'common/programs'))
from bundle_runtime import sha,read
from adapter_order_contract import verify_source_delta,verify_validator_delta,normalize_runtime_hashes
from launch_if_ready import main,dependency
assert sha(S/'CPU_QUALIFICATION.json')==expected
q=read(S/'CPU_QUALIFICATION.json');assert q['gate']=='PASS' and q['repair_generation']==2
assert all(sha(S/n)==h for n,h in q['workflow_files'].items())
repair=read(S/'ADAPTER_ORDER_REPAIR.json')
assert repair['human_authorization']['authorized_repair_generation']==2
assert all(sha(Path(path))==h for path,h in repair['original_failed_evidence_hashes'].items())
specs=read(S/'MATRIX.json')['cases']
assert len(specs)==2 and all(s['GPU']==1 and s['information_mode']=='oracle' for s in specs)
assert all('90_' not in s['name'] for s in specs)
preflight=[]
for spec in specs:
    C=Path(spec['stage']);qc=read(C/'receipts/CPU_QUALIFICATION.json')
    assert sha(C/'receipts/CPU_QUALIFICATION.json')==spec['qualification_sha256']
    assert qc['actual_controller_entry_check']=='PASS'
    assert all(sha(C/n)==h for n,h in qc['stage_files'].items())
    row=next(r for r in repair['cases'] if r['continuation_case']==str(C))
    P=Path(row['ordinary_counterpart'])
    proof=verify_source_delta((P/'common_runtime/oracle_length_adapter.py').read_text(),(C/'common_runtime/oracle_length_adapter.py').read_text())
    verify_validator_delta((P/'programs/followup_checks.py').read_text(),(C/'programs/followup_checks.py').read_text())
    normalize_runtime_hashes(read(P/'PROTOCOL.json')['common_runtime_hashes'],read(C/'PROTOCOL.json')['common_runtime_hashes'],proof)
    for name in ['WORKLOAD.json','MODEL_PROFILE.json','programs/client.py','programs/pure_metrics.py','programs/offline_compare.py']:
        assert sha(C/name)==sha(P/name),('Frozen paired contract mismatch',name)
    assert read(C/'SUITE_SPEC.json')['candidate_hashes']==read(P/'SUITE_SPEC.json')['candidate_hashes']
    preflight.append({'case':C.name,'gate':'PASS','frozen_pair_and_declared_source_delta_exact':True})
if (S/'RUNNER_LAUNCH.json').exists():
    print(json.dumps({'gate':'ALREADY_LAUNCHED','launch':read(S/'RUNNER_LAUNCH.json'),'preflight':preflight}));sys.exit(0)
assert not (S/'LAUNCH_STARTED.json').exists(),'Partial prior launch must be inspected, never repeated'
decision=dependency(S)
if decision['gate']!='READY':
    print(json.dumps(decision));sys.exit(0)
gpu=subprocess.run(['nvidia-smi','--id=1','--query-gpu=index,uuid,memory.used','--format=csv,noheader,nounits'],capture_output=True,text=True,check=True).stdout.strip()
assert int(gpu.split(',')[-1].strip())==0,('GPU1 is occupied; do not touch external processes',gpu)
with contextlib.redirect_stdout(io.StringIO()) as result:
    main(S,check_only=check_only)
answer=json.loads(result.getvalue());answer.update(preflight=preflight,GPU1_before_launch=gpu)
print(json.dumps(answer))
"""
python='/mnt/sda1/xuetianyou-a40/agent-dispatch-experiments/slo_declaration_robustness/gpu_closed_loop_20261013T122407Z_v1/env/bin/python'
command=[python,'-c',source,m['remote_study'],m['CPU_qualification_sha256'],args.action]
r=subprocess.run(['ssh','-o','ConnectTimeout=12','gpu-node1','PYTHONDONTWRITEBYTECODE=1 '+shlex.join(command)],capture_output=True,text=True,timeout=90)
if r.returncode:
    print(json.dumps({'gate':'CONNECTION_OR_CONTROL_ERROR','stdout':r.stdout,'stderr':r.stderr}));raise SystemExit(r.returncode)
print(json.dumps({'GPU':1,'result':json.loads(r.stdout)},ensure_ascii=False))
