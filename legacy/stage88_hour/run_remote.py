from pathlib import Path
import json,shlex,subprocess,sys
D=Path(__file__).resolve().parent;name=sys.argv[1];assert name in ['prepare_study','qualify_control','prepare_hour12','qualify_hour12_control']
packet=(D/(name+'_packet.json')).read_text();code=(D/(name+'.py')).read_text()
with(D/(name+'.stdout')).open('x')as out,(D/(name+'.stderr')).open('x')as err:
 r=subprocess.run(['ssh','-o','ConnectTimeout=12','gpu-node1','CUDA_VISIBLE_DEVICES= PYTHONDONTWRITEBYTECODE=1 python3 -c '+shlex.quote(code)],input=packet,text=True,stdout=out,stderr=err)
print(json.dumps({'operation':name,'returncode':r.returncode,'stdout':str(D/(name+'.stdout')),'stderr':str(D/(name+'.stderr'))}));raise SystemExit(r.returncode)
