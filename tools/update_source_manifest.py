#!/usr/bin/env python3
"""Maintainer-only explicit hash refresh after reviewing the source changes."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from chainbench.core import ROOT,dump
from chainbench.integrity import MANIFEST,manifest_snapshot

if __name__=='__main__':
    data=manifest_snapshot(ROOT)
    dump(ROOT/MANIFEST,data)
    print('Recorded',len(data['files']),'published files; verify the diff before committing.')
