#!/usr/bin/env python3
"""CPU publication checks: syntax, source hashes, secret markers and file sizes."""
import ast
import gzip
import json
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chainbench.core import ROOT, source_check, dump

def main():
    bad=[];syntax=[];total=0;files=[]
    patterns=[re.compile(rb'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----'),
              re.compile(rb'gh[pousr]_[A-Za-z0-9]{30,}'),
              re.compile(rb'github_pat_[A-Za-z0-9_]{30,}'),
              re.compile(rb'hf_[A-Za-z0-9]{30,}')]
    for f in sorted(ROOT.rglob('*')):
        parts=f.relative_to(ROOT).parts
        if not f.is_file() or any(s in parts for s in ['.git','.venv','__pycache__']):continue
        if parts[0]in ['build','dist','runs','downloads','models']:continue
        if f.name.endswith('.egg-info') or any(x.endswith('.egg-info')for x in f.parts):continue
        data=f.read_bytes();name=str(f.relative_to(ROOT));total+=len(data);files.append(name)
        if len(data)>20_000_000:bad.append((name,'file >20MB'))
        scan_data=gzip.decompress(data)if f.suffix=='.gz'else data
        if any(p.search(scan_data)for p in patterns):bad.append((name,'credential marker'))
        if f.suffix in {'.pkl','.safetensors','.so','.pem','.key'}:bad.append((name,'excluded asset or credential file type'))
        if f.suffix=='.py':
            try:ast.parse(data,filename=name)
            except SyntaxError as exc:syntax.append((name,str(exc)))
    source=source_check()
    report=dict(gate='PASS'if not bad and not syntax and source['gate']=='PASS'else'FAIL',
        files=len(files),bytes=total,source_integrity=source,syntax_errors=syntax,
        publish_scan_findings=bad,GPU_used=False,
        limits='Pattern scan and CPU checks; no model execution or A100 validation.')
    print(json.dumps(report,indent=2))
    raise SystemExit(report['gate']!='PASS')
if __name__=='__main__':main()
