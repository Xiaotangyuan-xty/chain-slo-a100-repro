"""CPU-only observation of the assigned GPU and registered server/predictor."""
from pathlib import Path
import json,subprocess,sys,time
C=Path(sys.argv[1]);A=Path(sys.argv[2]);p=json.loads((C/'PROTOCOL.json').read_text())
gpu_index=p['resources']['physical_gpu_index'];assert gpu_index in[0,1]
with(A/'WINDOW_GPU_CPU_SAMPLES.jsonl').open('x')as stream:
    while not(A/'CLIENT_CUTOFF_SNAPSHOT.json').exists():
        stamp=time.perf_counter();regs=json.loads((A/'processes.json').read_text());processes=[]
        for r in regs:
            if r['name']not in ['server','predictor']:continue
            try:
                stat=Path(f"/proc/{r['pid']}/stat").read_text().rsplit(')',1)[1].split()
                if int(stat[19])!=r['proc_start_ticks']:raise RuntimeError('Registered process identity changed')
                processes.append({'name':r['name'],'pid':r['pid'],'user_ticks':int(stat[11]),'system_ticks':int(stat[12]),'rss_pages':int(stat[21])})
            except FileNotFoundError:pass
        gpu=subprocess.run(['nvidia-smi',f'--id={gpu_index}','--query-gpu=index,uuid,utilization.gpu,memory.used','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=4)
        row={'monotonic':stamp,'GPU':gpu_index,'query_returncode':gpu.returncode,'gpu':gpu.stdout.strip(),'processes':processes}
        stream.write(json.dumps(row)+'\n');stream.flush();time.sleep(5.)
