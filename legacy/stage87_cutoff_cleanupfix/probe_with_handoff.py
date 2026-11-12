"""Read-only generic probe with receipt-verified queued handoff resolution."""
from pathlib import Path
import hashlib,io,json,sys,contextlib
packet=json.load(sys.stdin);resolved=[];pending=[]
for q in packet['queues']:
    item=q.get('queued_successor')
    if not item:continue
    S=Path(item['remote_study'])
    if(S/'RUNNER_LAUNCH.json').exists():
        assert hashlib.sha256((S/'CPU_QUALIFICATION.json').read_bytes()).hexdigest()==item['CPU_qualification_sha256']
        assert json.loads((S/'PREDECESSOR_AUDIT.json').read_text())['gate']=='PASS'
        old=q['remote_study'];q.update(remote_study=str(S),kind=item.get('kind','fixed_hour_cutoff_no_drain'))
        resolved.append({'GPU':q['GPU'],'from':old,'to':str(S),'launch':json.loads((S/'RUNNER_LAUNCH.json').read_text()),'predecessor_independent_audit':'PASS'})
    else:
        status=json.loads((S/'HANDOFF_STATUS.json').read_text())if(S/'HANDOFF_STATUS.json').exists()else None
        pending.append({'GPU':q['GPU'],'remote_study':str(S),'status':status})
sys.stdin=io.StringIO(json.dumps(packet))
with contextlib.redirect_stdout(io.StringIO())as result:
    exec('"""Generic read-only snapshots for old queues and prepared follow-up workflows."""\nfrom pathlib import Path\nfrom datetime import datetime,timezone\nimport json,os,subprocess,sys,time\nos.sched_setaffinity(0,{28,30,84,86})\nP=json.load(sys.stdin)\ndef read(p):return json.loads(p.read_text())if p.exists()else None\ndef proc(pid):\n    try:\n        t=Path(f\'/proc/{pid}/stat\').read_text().rsplit(\')\',1)[1].split()\n        return {\'pid\':pid,\'state\':t[0],\'ppid\':int(t[1]),\'proc_start_ticks\':int(t[19]),\'argv\':Path(f\'/proc/{pid}/cmdline\').read_bytes().decode().split(\'\\0\')[:-1]}\n    except FileNotFoundError:return None\ndef tail(p):\n    if not p.exists():return None\n    with p.open(\'rb\')as f:f.seek(max(0,p.stat().st_size-65536));lines=f.read().decode(errors=\'replace\').splitlines()\n    for line in reversed(lines):\n        try:return json.loads(line)\n        except json.JSONDecodeError:pass\n    return None\nrows=[]\nfor q in P[\'queues\']:\n    S=Path(q[\'remote_study\']);gpu=q[\'GPU\'];assert gpu in[0,1]\n    st=read(S/\'STUDY_STATUS.json\');launch=read(S/\'RUNNER_LAUNCH.json\');run=proc(launch[\'pid\'])if launch else None\n    identity=run is not None and run[\'proc_start_ticks\']==launch[\'proc_start_ticks\']and str(S)in run[\'argv\']\n    specs=(read(S/\'MATRIX.json\')or{}).get(\'cases\',[])+(read(S/\'FORMAL_MATRIX.json\')or{}).get(\'cases\',[])\n    active=next((s for s in specs if s[\'name\']==st.get(\'active_case\')),None);details=None\n    if active:\n        C=Path(active[\'stage\']);A=C/\'attempts\'/active[\'attempt\'];regs=read(A/\'processes.json\')or[];ids=[];p=read(C/\'PROTOCOL.json\')\n        for r in regs:\n            live=proc(r[\'pid\']);match=live is not None and live[\'proc_start_ticks\']==r[\'proc_start_ticks\']and live[\'argv\']==r[\'command\']\n            row={\'name\':r[\'name\'],\'pid\':r[\'pid\'],\'identity_matches\':match,\'state\':live[\'state\']if live else None}\n            if match and r[\'name\']==\'server\':\n                env=Path(f"/proc/{r[\'pid\']}/environ").read_bytes().split(b\'\\0\');value=next((v.split(b\'=\',1)[1].decode()for v in env if v.startswith(b\'CUDA_VISIBLE_DEVICES=\')),None);row[\'GPU_UUID_matches\']=value==p[\'resources\'][\'gpu_uuid\']\n            ids.append(row)\n        controller=read(A/\'controller_status.json\');control=proc(controller[\'controller_pid\'])if controller else None\n        roots=failures=finished_requests=output_tokens=0\n        if(A/\'client_calls.jsonl\').exists():\n            for line in(A/\'client_calls.jsonl\').open():\n                try:c=json.loads(line)\n                except json.JSONDecodeError:continue\n                if c.get(\'phase\')==\'main\':roots+=1;failures+=not c[\'success\']\n        if(A/\'common_events.jsonl\').exists():\n            for line in(A/\'common_events.jsonl\').open():\n                try:e=json.loads(line)\n                except json.JSONDecodeError:continue\n                if e.get(\'phase\')==\'main\'and e[\'kind\']==\'request_finish\':finished_requests+=1;output_tokens+=e[\'output_tokens\']\n        event=tail(A/\'EXECUTOR_EVENTS.jsonl\')\n        details={\'case\':active[\'name\'],\'phase\':controller,\'controller_parent_matches\':bool(control and run and control[\'ppid\']==run[\'pid\']),\n                 \'processes\':ids,\'completed_main_roots\':roots,\'expected_main_roots\':active.get(\'root_counts\',{}).get(\'dr\'),\n                 \'completed_root_failures\':failures,\'finished_main_requests\':finished_requests,\'finished_main_output_tokens\':output_tokens,\n                 \'main_start\':read(A/\'MAIN_START.json\'),\'warmup\':read(A/\'WARMUP_NATIVE_TOT_GATE.json\'),\n                 \'latest_executor_event\':event,\'executor_log_bytes\':(A/\'EXECUTOR_EVENTS.jsonl\').stat().st_size if(A/\'EXECUTOR_EVENTS.jsonl\').exists()else 0,\n                 \'failure\':read(A/\'CONTROLLER_FAILURE.json\'),\'case_failure\':read(C/\'CASE_FAILURE.json\')}\n    gates=[]\n    for spec in specs:\n        C=Path(spec[\'stage\']);path=C/\'receipts\'/(\'RUN_GATE_\'+spec[\'attempt\']+\'.json\');gate=read(path)\n        if not gate and spec[\'name\']in q.get(\'derived_acceptance_paths\',{}):\n            path=Path(q[\'derived_acceptance_paths\'][spec[\'name\']]);gate=read(path)\n        if gate:gates.append({\'case\':spec[\'name\'],\'gate\':gate[\'gate\'],\'metrics\':gate[\'metrics\'],\'path\':str(path)})\n    rows.append({\'GPU\':gpu,\'study\':str(S),\'utc\':datetime.now(timezone.utc).isoformat(),\'status\':st,\n                 \'runner_launch\':launch,\'runner_identity_matches\':identity,\'runner_live\':run,\n                 \'active\':details,\'completed_final_gates\':gates,\'formal_freeze\':read(S/\'FORMAL_FREEZE.json\'),\n                 \'GPU_state\':subprocess.check_output([\'nvidia-smi\',\'-i\',str(gpu),\'--query-gpu=index,uuid,memory.used,utilization.gpu\',\'--format=csv,noheader\'],text=True).strip()})\nprint(json.dumps({\'read_only\':True,\'rows\':rows},ensure_ascii=False))\n',{'__name__':'receipt_resolved_readonly_probe'})
answer=json.loads(result.getvalue());answer['resolved_handoffs']=resolved;answer['pending_handoffs']=pending
for row in answer['rows']:
    q=next(q for q in packet['queues']if q['GPU']==row['GPU'])
    active=row.get('active')
    if q.get('kind')not in ['fixed_hour_cutoff_no_drain','fixed_window_cutoff_no_drain'] or not active:continue
    S=Path(row['study']);spec=next(s for s in json.loads((S/'MATRIX.json').read_text())['cases']if s['name']==active['case'])
    A=Path(spec['stage'])/'attempts'/spec['attempt'];snapfile=A/'CLIENT_CUTOFF_SNAPSHOT.json'
    if snapfile.exists():
        snap=json.loads(snapfile.read_text());end=snap['cutoff_monotonic']
        completed=sum(c['success']and c['client_chain_end_monotonic']is not None and c['client_chain_end_monotonic']<end for c in snap['roots'])
        active['generic_completed_main_roots_before_censor_correction']=active['completed_main_roots']
        active['completed_main_roots']=completed
        active['completed_root_failures']=len(snap['technical_errors_before_cutoff'])
        active['censored_main_roots']=snap['arrived_roots']-completed
        active['window_cutoff_reached']=True;active['no_drain']=True
        active['root_censoring_is_expected_not_failure']=True
        marker=A/'WINDOW_SERVER_CUTOFF.json'
        if marker.exists():
            server=json.loads(marker.read_text());active['actual_output_tokens_in_window']=sum(r['output_tokens']for r in server['requests']if r['phase']=='main')
        event=active.get('latest_executor_event')
        if event and event.get('error')=='CancelledError'and event.get('end_monotonic',0)>=end:active['expected_window_end_cancellation']=True
print(json.dumps(answer))
