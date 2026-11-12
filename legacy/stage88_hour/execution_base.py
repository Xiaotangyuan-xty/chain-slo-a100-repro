"""Finite serial follow-up workflows. Never retries or touches another GPU."""
from pathlib import Path
import fcntl, json, os, subprocess, sys, time, traceback
from bundle_runtime import R,L,read,dump,sha,prepare_case,freeze_case
from workload_design import root_backlog_stats,freeze_work,HOUR_SECONDS,HEADROOM_FACTOR


def owned_alive(attempt):
    file=attempt/'processes.json'
    if not file.exists():return []
    live=[]
    for reg in read(file):
        try:
            data=Path(f"/proc/{reg['pid']}/stat").read_text().rsplit(')',1)[1].split()
            cmd=Path(f"/proc/{reg['pid']}/cmdline").read_bytes().decode().split('\0')[:-1]
            if int(data[19])==reg['proc_start_ticks']and data[0]!='Z':
                if cmd!=reg['command']:raise RuntimeError('Registered live identity changed')
                live.append(reg)
        except FileNotFoundError:pass
    return live


def execute(S,spec,status):
    C=Path(spec['stage']);A=C/'attempts'/spec['attempt'];p=read(C/'PROTOCOL.json');gpu=spec['GPU']
    assert gpu in [0,1]and not list((C/'attempts').iterdir())
    assert sha(C/'receipts/CPU_QUALIFICATION.json')==spec['qualification_sha256']
    until=time.monotonic()+21600
    while True:
        apps=subprocess.check_output(['nvidia-smi','-i',str(gpu),'--query-compute-apps=pid,used_memory','--format=csv,noheader'],text=True).strip()
        free=int(subprocess.check_output(['nvidia-smi','-i',str(gpu),'--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True).strip())
        if not apps and free>=p['minimum_free_memory_MiB_before_load']:break
        status(phase='WAIT_RESOURCES_NO_EXTERNAL_SIGNALS',active_case=spec['name'])
        if time.monotonic()>=until:raise TimeoutError('Resource wait exhausted; preserve, never signal external process')
        time.sleep(30)
    status(phase='CONTROLLER',active_case=spec['name'])
    dump(C/'CASE_STATUS.json',{'state':'RUNNING','utc':L.utc(),'case':spec})
    with(C/'CONTROLLER.log').open('x')as f:
        subprocess.run([L.PYTHON,str(C/'programs/controller.py'),str(R),str(C),spec['arm'],spec['attempt'],'full'],cwd=R,env=L.env(),stdout=f,stderr=subprocess.STDOUT,check=True)
    if owned_alive(A):raise RuntimeError('Controller left owned processes; refuse overlap')
    status(phase='FINAL_GATE',active_case=spec['name'])
    with(C/'GATE.log').open('x')as f:
        subprocess.run([L.PYTHON,str(C/'programs/offline_compare.py'),str(R),str(C),spec['attempt']],cwd=R,env=L.env(),stdout=f,stderr=subprocess.STDOUT,check=True)
    gate=read(C/'receipts'/('RUN_GATE_'+spec['attempt']+'.json'))
    assert gate['gate']=='PASS'and all(gate['checks'].values())
    return {'gate':'PASS','metrics':gate['metrics'],'gate_path':str(C/'receipts'/('RUN_GATE_'+spec['attempt']+'.json'))}


def main(S):
    plan=read(S/'PLAN.json');q=read(S/'CPU_QUALIFICATION.json');matrix=read(S/'MATRIX.json')
    gpu=plan['GPU'];assert q['gate']=='PASS'and gpu in [0,1]
    assert all(sha(S/n)==h for n,h in q['workflow_files'].items())
    results=[];state={'state':'RUNNING','phase':'START','active_case':None,'completed':[],'failed':[],'results':[]}
    def status(**fields):
        state.update(fields,updated_utc=L.utc());dump(S/'STUDY_STATUS.json',state)
    def run(spec):
        try:row=execute(S,spec,status)
        except Exception as error:row={'gate':'FAIL','error':str(error),'traceback':traceback.format_exc()}
        C=Path(spec['stage']);A=C/'attempts'/spec['attempt'];row={'case':spec,**row};results.append(row)
        dump(C/'CASE_STATUS.json',{'state':'COMPLETED'if row['gate']=='PASS'else'FAILED_PRESERVED','utc':L.utc(),'result':row})
        if row['gate']!='PASS':dump(C/'CASE_FAILURE.json',row)
        status(completed=[r['case']['name']for r in results if r['gate']=='PASS'],failed=[r['case']['name']for r in results if r['gate']!='PASS'],results=results)
        if owned_alive(A):raise RuntimeError('Owned processes remain; do not launch another case')
        return row
    def trio(specs):
        rows=[run(s)for s in specs]
        if any(r['gate']!='PASS'for r in rows):raise RuntimeError('Technical/gate failure preserved; do not interpret as capacity instability')
        stable=[]
        for row in rows:
            spec=row['case'];C=Path(spec['stage']);A=C/'attempts'/spec['attempt'];work=read(C/'WORKLOAD.json');calls=[c for c in read(A/'client_calls.json')if c['phase']=='main'];origin=read(A/'MAIN_START.json')['origin_monotonic']
            s=root_backlog_stats([c['client_chain_start_monotonic']-origin for c in calls],[c['client_chain_end_monotonic']-origin for c in calls],spec['horizon_seconds'])
            dump(C/'receipts/STABILITY_GATE.json',s);stable.append(s)
        return all(s['gate']=='PASS'for s in stable),stable
    try:
        with open(f'/tmp/xuetianyou_chain_slo_gpu{gpu}.lock','a+')as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            lock.seek(0);lock.truncate();lock.write(json.dumps({'pid':os.getpid(),'GPU':gpu,'study':str(S)}));lock.flush()
            if plan['kind']=='oracle':
                for spec in matrix['cases']:run(spec)
            else:
                selected=None
                for level,rate in enumerate(plan['pilot_rates']):
                    scan=[s for s in matrix['cases']if s['pilot_level']==level and s['pilot_phase']=='scan']
                    okay,scan_state=trio(scan)
                    if not okay:continue
                    confirm=[s for s in matrix['cases']if s['pilot_level']==level and s['pilot_phase']=='confirm']
                    okay,confirm_state=trio(confirm)
                    if okay:
                        selected={'level':level,'capacity_candidate_rate':rate,'formal_rate':rate*HEADROOM_FACTOR,'scan':scan_state,'confirmation':confirm_state};break
                if selected is None:raise RuntimeError('No preregistered stable common rate; preserve pilots and request a lower-rate decision')
                assert not(S/'FORMAL_FREEZE.json').exists()
                parent=read(S/'common/PARENT_WORKLOAD.json');split=read(S/'PILOT_FORMAL_SPLIT.json')
                work=freeze_work(parent,split['formal_root_indices'],horizon=HOUR_SECONDS,rate=selected['formal_rate'],seed=202611108103,purpose='formal_hour')
                specs=[]
                for number,method in enumerate(['Astar','v47pro','A'],1):
                    name=f'{90+number:02d}_hour_'+('v47pro3'if method=='v47pro'else method)
                    s=prepare_case(S,name,work,method=method,gpu=gpu,rate=selected['formal_rate'],horizon=HOUR_SECONDS,purpose='formal_hour')
                    freeze_case(S,s,q['tests']);specs.append(s)
                frozen={'utc':L.utc(),'selected_only_by_backlog_and_drain':True,'selection':selected,
                        'workload_sha256':specs[0]['workload_sha256'],'hour_denominator':3600.,'cases':specs}
                assert len({s['workload_sha256']for s in specs})==1
                dump(S/'FORMAL_MATRIX.json',{'cases':specs});dump(S/'FORMAL_FREEZE.json',frozen)
                for s in specs:run(s)
            failed=[r['case']['name']for r in results if r['gate']!='PASS']
            dump(S/'FINAL_RESULTS.json',{'gate':'PASS'if not failed else'COMPLETED_WITH_FAILURES','utc':L.utc(),'cases':results,'failed':failed,'no_automatic_retries':True})
            status(state='COMPLETED'if not failed else'COMPLETED_WITH_FAILURES',phase='DONE',active_case=None)
    except BaseException as error:
        status(state='NEEDS_ATTENTION',phase='PRESERVED_NO_BLIND_RETRY',error=str(error),traceback=traceback.format_exc())
        raise


if __name__=='__main__':main(Path(sys.argv[1]).resolve())
