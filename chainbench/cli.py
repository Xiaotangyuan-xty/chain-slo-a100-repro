import argparse
import csv
import gzip
import json
from pathlib import Path
from .core import ROOT, matrix, workload, dump, read, source_check, assess_profile

def main():
    p=argparse.ArgumentParser(description='CPU preparation and qualification inventory; never starts a GPU job')
    sub=p.add_subparsers(dest='command',required=True)
    plan=sub.add_parser('plan');plan.add_argument('--out',type=Path,required=True)
    prepare=sub.add_parser('prepare');prepare.add_argument('--case',required=True);prepare.add_argument('--out',type=Path,required=True)
    doctor=sub.add_parser('doctor');doctor.add_argument('--case');doctor.add_argument('--profile',type=Path)
    sub.add_parser('verify-sources')
    args=p.parse_args();cases=matrix()
    if args.command=='plan':
        args.out.mkdir(parents=True,exist_ok=True)
        dump(args.out/'matrix.json',cases)
        with (args.out/'matrix.csv').open('w',newline='')as stream:
            writer=csv.DictWriter(stream,fieldnames=list(cases[0]));writer.writeheader();writer.writerows(cases)
        print(json.dumps(dict(cases=len(cases),logical_window_hours=sum(c['window_seconds']for c in cases)/3600,
            qualification='A100_NOT_TESTED',out=str(args.out))))
    elif args.command=='prepare':
        case=next((c for c in cases if c['id']==args.case),None)
        if case is None:p.error('Unknown case ID')
        args.out.mkdir(parents=True,exist_ok=False)
        dump(args.out/'CASE.json',case)
        data=workload(case)
        with gzip.open(args.out/'WORKLOAD.json.gz','wt')as stream:json.dump(data,stream,ensure_ascii=False,allow_nan=False)
        dump(args.out/'READINESS.json',dict(status='PREPARED_CPU_ONLY',
            requires=['model/predictor assets','backend build','portable launcher binding','A100 per-profile qualification'],
            GPU_started=False))
        print(json.dumps(dict(case=case['id'],roots=len(data['main']),window_seconds=case['window_seconds'],GPU_started=False)))
    elif args.command=='verify-sources':
        result=source_check();print(json.dumps(result));raise SystemExit(result['gate']!='PASS')
    else:
        result=dict(source_integrity=source_check(),GPU_used=False,portable_full_suite_ready=False,
            pending=['Sarathi adapter and pinned environment','native launcher host-path migration',
                     '30B tokenizer/MoE qualification and predictor policy','70B TP and predictor qualification',
                     'window-cutoff integration of Oracle/ablations','A100 KV/performance/cutoff/cleanup qualification'])
        if args.profile:
            case=next((c for c in cases if c['id']==args.case),None)
            if case is None:p.error('--profile requires a valid --case')
            result['profile']=assess_profile(case,read(args.profile))
        print(json.dumps(result,indent=2))
        raise SystemExit(2 if not result['portable_full_suite_ready'] else 0)

if __name__=='__main__':main()
