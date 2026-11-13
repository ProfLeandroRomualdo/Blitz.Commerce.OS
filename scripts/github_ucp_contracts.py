"""Fetch official UCP *tagged commit* via GitHub and preserve provenance.

Intended for CI with network. Nothing runs against arbitrary agent-supplied URLs.
Official UCP source is staged outside the application runtime.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
VERSION = '2026-08-25'
TAG = 'v2026-08-25'
COMMIT = 'cd78fb38e819de77d9b527d110476eccb876f1bd'
REPO = 'https://github.com/Universal-Commerce-Protocol/ucp.git'
OUT = ROOT / 'contracts' / VERSION / 'github'


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def snapshot(checkout: Path) -> dict:
    """Only accept the exact reviewed upstream commit, not branch HEAD."""
    sha = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
    if sha != COMMIT:
        raise ValueError(f'Incorrect upstream revision: expected {COMMIT}, got {sha}')
    source = checkout / 'source'
    if not (source / 'schemas').is_dir():
        raise ValueError('Official checkout missing source/schemas')
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / 'source').mkdir(parents=True)
    artifacts = {}
    for path in sorted(source.rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(source).as_posix()
        if path.is_symlink() or len(relative) > 240:
            raise ValueError(f'Unapproved upstream source entry: {relative}')
        data = path.read_bytes()
        if len(data) > 5_000_000:
            raise ValueError('Oversized upstream source: ' + relative)
        target = OUT / 'source' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        artifacts['source/' + relative] = sha256(data)
    if not artifacts:
        raise ValueError('No upstream source files')
    manifest = {'repository': REPO, 'tag': TAG, 'commit': COMMIT, 'files': artifacts}
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    return manifest


def verify() -> dict:
    manifest = json.loads((OUT / 'manifest.json').read_text())
    if manifest['repository'] != REPO or manifest['tag'] != TAG or manifest['commit'] != COMMIT:
        raise ValueError('Official UCP source provenance mismatch')
    actual = {'source/' + p.relative_to(OUT / 'source').as_posix() for p in (OUT / 'source').rglob('*') if p.is_file()}
    if actual != set(manifest['files']):
        raise ValueError('UCP source file set mismatch')
    for path, checksum in manifest['files'].items():
        if not re.fullmatch(r'source/[A-Za-z0-9_./-]+', path) or '..' in path.split('/'):
            raise ValueError('Invalid path in official manifest')
        if sha256((OUT / path).read_bytes()) != checksum:
            raise ValueError(f'Official UCP source changed: {path}')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--checkout', type=Path, help='Path to clone at exactly the locked commit')
    group.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    manifest = snapshot(args.checkout) if args.checkout else verify()
    print(f'OFFICIAL UCP {manifest["tag"]} {manifest["commit"]}: {len(manifest["files"])} files verified')

if __name__ == '__main__':
    main()
