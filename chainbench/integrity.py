"""Content inventory for the published checkout, including its checking tools.

The manifest excludes itself; its bytes are bound by the Git commit/tag. This is
change detection against a trusted manifest, not a signature or a substitute for
checking the release commit's identity.
"""
import hashlib
import json
from pathlib import Path

MANIFEST = 'provenance/SOURCE_SHA256.json'
EXCLUDED_ROOTS = {'build','dist','runs','downloads','models'}

def digest(path):
    value=hashlib.sha256()
    with path.open('rb')as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):value.update(chunk)
    return value.hexdigest()

def published_files(root):
    for path in sorted(root.rglob('*')):
        parts=path.relative_to(root).parts
        if any(p in {'.git','.venv','__pycache__','.pytest_cache'}or p.endswith('.egg-info')for p in parts):continue
        if parts[0]in EXCLUDED_ROOTS or parts[:2]==('profiles','local'):continue
        if path.name=='.DS_Store' or path.suffix in {'.pyc','.pyo'}:continue
        if path.relative_to(root).as_posix()==MANIFEST:continue
        if path.is_file()or path.is_symlink():yield path

def manifest_snapshot(root):
    files={}
    for path in published_files(root):
        if path.is_symlink():raise ValueError('Published source symlink: '+str(path.relative_to(root)))
        files[path.relative_to(root).as_posix()]=digest(path)
    return dict(schema='chainbench-release-integrity/v2',algorithm='sha256',
        scope='All published checkout files, including tools, tests, configs, docs and provenance',
        self_excluded=MANIFEST,
        trust='Manifest is not signed; trust the Git release commit/tag. Verification never regenerates hashes.',
        files=files)

def verify_manifest(root):
    try:
        data=json.loads((root/MANIFEST).read_text())
        if data.get('schema')!='chainbench-release-integrity/v2':raise ValueError('Unsupported manifest schema')
        expected=data['files'];actual={p.relative_to(root).as_posix():p for p in published_files(root)}
        if MANIFEST in expected:raise ValueError('Manifest must not hash itself')
        missing=sorted(set(expected)-set(actual));unexpected=sorted(set(actual)-set(expected))
        changed=sorted(name for name in set(expected)&set(actual)
                       if actual[name].is_symlink()or digest(actual[name])!=expected[name])
        bad=missing+unexpected+changed
        return dict(gate='FAIL'if bad else'PASS',files_checked=len(expected),
            bad=bad,missing=missing,unexpected=unexpected,changed=changed)
    except (OSError,ValueError,KeyError,TypeError)as error:
        return dict(gate='FAIL',files_checked=0,bad=[MANIFEST],error=str(error))
