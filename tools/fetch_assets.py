#!/usr/bin/env python3
"""Explicit official downloads; tokens are read by huggingface_hub, never printed.

The QRF files are pickle/joblib data. Verify their pinned hash before loading.
Model downloads need --revision with an immutable HF commit. Gated Llama models
require the user's accepted Meta license and local HF authentication.
"""
import argparse
import fnmatch
import json
from pathlib import Path
import re
import shutil
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chainbench.core import ROOT, read, sha, dump

RECEIPT = 'ASSET_RECEIPT.json'
IGNORED_DOWNLOAD_PATTERNS = ['*.bin','*.pt','*.pth','*.gguf','*.h5','*.msgpack']

def model_inventory(directory,*,hashes=True):
    """Inventory payload only; never hash a receipt into its own replacement."""
    files={}
    for f in sorted(directory.rglob('*')):
        parts=f.relative_to(directory).parts
        if parts== (RECEIPT,) or parts[:2]==('.cache','huggingface'):
            continue
        if f.is_symlink():raise RuntimeError('Symlink in model output: '+str(f.relative_to(directory)))
        if f.is_file():
            files[str(f.relative_to(directory))]=dict(bytes=f.stat().st_size,sha256=sha(f))if hashes else None
    return files

def check_existing_receipt(directory,model,repository,revision):
    receipt=directory/RECEIPT
    if receipt.exists():
        old=read(receipt)
        if (old.get('model'),old.get('repository'),old.get('revision')) != (model,repository,revision):
            raise RuntimeError('Output directory receipt belongs to another model/revision; use a separate directory')

def download_model(model,revision,directory,spec,api,snapshot_download):
    check_existing_receipt(directory,model,spec['repository'],revision)
    # The pinned remote file list is authoritative even when historical hashes
    # cover only a subset of files, or are unavailable for a new model.
    expected=set(api.list_repo_files(repo_id=spec['repository'],revision=revision))
    expected={name for name in expected
              if not any(fnmatch.fnmatch(name,pattern) for pattern in IGNORED_DOWNLOAD_PATTERNS)}
    if 'model.safetensors.index.json'not in expected:
        raise RuntimeError('Pinned repository lacks a sharded BF16 safetensors index')
    for name in expected:
        path=Path(name)
        if path.is_absolute() or '..' in path.parts or name==RECEIPT or path.parts[:2]==('.cache','huggingface'):
            raise RuntimeError('Invalid or reserved remote model filename: '+name)
    extras=set(model_inventory(directory,hashes=False))-expected
    if extras:raise RuntimeError('Unexpected existing payload files: '+', '.join(sorted(extras)))
    snapshot_download(spec['repository'],revision=revision,local_dir=directory,
                      allow_patterns=sorted(expected))
    files=model_inventory(directory)
    missing=expected-set(files);extras=set(files)-expected
    if missing or extras:
        raise RuntimeError('Snapshot file set mismatch: '+json.dumps(dict(missing=sorted(missing),extra=sorted(extras))))
    index=directory/'model.safetensors.index.json'
    if not index.is_file():raise RuntimeError('Sharded BF16 safetensors index missing')
    for shard in set(read(index)['weight_map'].values()):
        if shard not in files or files[shard]['bytes']<=0:raise RuntimeError('Missing shard '+shard)
    historical=spec.get('files',{})
    mismatch=[name for name,expected_file in historical.items() if files.get(name)!=expected_file]
    receipt=dict(schema='chainbench-model-asset-receipt/v2',model=model,repository=spec['repository'],
        revision=revision,files=files,expected_payload_files=sorted(expected),
        historical_snapshot_matches=(not mismatch)if historical else None,
        historical_mismatch_files=mismatch,
        qualification='HISTORICAL_SNAPSHOT_MISMATCH'if mismatch else'DOWNLOAD_VERIFIED_NOT_GPU_QUALIFIED')
    dump(directory/RECEIPT,receipt)
    if mismatch:
        raise RuntimeError('Downloaded snapshot differs from historical hashes; receipt retained; requalify before comparison')
    return receipt

def main():
    p=argparse.ArgumentParser();p.add_argument('kind',choices=['qrf','model'])
    p.add_argument('--model',choices=['llama8','qwen14','qwen30','llama70'])
    p.add_argument('--revision');p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();assets=read(ROOT/'configs/assets.json')
    from huggingface_hub import HfApi, hf_hub_download, snapshot_download
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
        download_model(args.model,args.revision,args.out,assets['models'][args.model],HfApi(),snapshot_download)
        print('Downloaded and hashed model snapshot; no GPU load performed.')

if __name__=='__main__':main()
