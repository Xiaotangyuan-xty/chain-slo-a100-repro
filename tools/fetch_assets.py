#!/usr/bin/env python3
"""Explicit official downloads; tokens are read by huggingface_hub, never printed.

The QRF files are pickle/joblib data. Verify their pinned hash before loading.
Model downloads need --revision with an immutable HF commit. Gated Llama models
require the user's accepted Meta license and local HF authentication.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chainbench.core import ROOT, read, sha, dump

def main():
    p=argparse.ArgumentParser();p.add_argument('kind',choices=['qrf','model'])
    p.add_argument('--model',choices=['llama8','qwen14','qwen30','llama70'])
    p.add_argument('--revision');p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();assets=read(ROOT/'configs/assets.json')
    from huggingface_hub import hf_hub_download, snapshot_download
    args.out.mkdir(parents=True,exist_ok=True)
    if args.kind=='qrf':
        for name,spec in assets['qrf'].items():
            downloaded=Path(hf_hub_download(assets['predictor_repository'],name,
                revision=assets['predictor_revision']))
            if downloaded.stat().st_size!=spec['bytes'] or sha(downloaded)!=spec['sha256']:
                raise RuntimeError('Official predictor hash mismatch: '+name)
            target=args.out/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(downloaded,target)
        print('Verified four official predictor files at pinned revision.')
    else:
        if not args.model or not re.fullmatch('[0-9a-f]{40}',args.revision or ''):
            p.error('model requires --model and immutable 40-hex --revision')
        spec=assets['models'][args.model]
        snapshot_download(spec['repository'],revision=args.revision,local_dir=args.out,
                          ignore_patterns=['*.bin','*.pt','*.pth','*.gguf','*.h5','*.msgpack'])
        files={}
        for f in sorted(args.out.rglob('*')):
            if f.is_file()and '.cache' not in f.relative_to(args.out).parts:
                name=str(f.relative_to(args.out));files[name]=dict(bytes=f.stat().st_size,sha256=sha(f))
        index=args.out/'model.safetensors.index.json'
        if not index.is_file():raise RuntimeError('Sharded BF16 safetensors index missing')
        for shard in set(read(index)['weight_map'].values()):
            if shard not in files or files[shard]['bytes']<=0:raise RuntimeError('Missing shard '+shard)
        mismatch=[name for name,expected in spec.get('files',{}).items() if files.get(name)!=expected]
        dump(args.out/'ASSET_RECEIPT.json',dict(model=args.model,repository=spec['repository'],
            revision=args.revision,files=files,historical_snapshot_matches=not mismatch,
            historical_mismatch_files=mismatch,qualification='DOWNLOAD_VERIFIED_NOT_GPU_QUALIFIED'))
        if mismatch:
            raise RuntimeError('Downloaded snapshot differs from historical hashes; receipt retained; requalify before comparison')
        print('Downloaded and hashed model snapshot; no GPU load performed.')

if __name__=='__main__':main()
