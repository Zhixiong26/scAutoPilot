#!/usr/bin/env python3
"""Stage user-supplied acceleration releases and provision isolated MethSCAn."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def unpack_tar(archive, destination):
    """Only regular files/directories; never follow archive links or traversal."""
    destination = Path(destination).resolve()
    members = archive.getmembers()
    for m in members:
        target = (destination / m.name).resolve()
        if not target.is_relative_to(destination) or not (m.isfile() or m.isdir()):
            raise ValueError('unsafe archive member: ' + m.name)
    for m in members:
        target = destination / m.name
        if m.isdir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(m) as src, target.open('xb') as dst:
                shutil.copyfileobj(src, dst)
            target.chmod(0o755 if m.mode & 0o111 else 0o644)


def save(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def stage(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    bismark = list(source.glob('bismark-acc-*.tar.gz'))
    combined = list(source.glob('methscan-vmrseq-packages-*.zip'))
    if len(bismark) != 1 or len(combined) != 1:
        raise ValueError('source must contain exactly one Bismark tar.gz and one MethSCAn/vmrseq zip')
    if destination.exists():
        raise ValueError('destination already exists; use a fresh versioned destination')
    destination.mkdir(parents=True)
    with tarfile.open(bismark[0]) as t:
        unpack_tar(t, destination / 'bismark')
    entries = list((destination / 'bismark').glob('*/bismark-acc'))
    if len(entries) != 1:
        raise ValueError('Bismark archive has no unique entry point')
    with zipfile.ZipFile(combined[0]) as z:
        expected = ('INSTALL.txt', 'methscan-1.1.0+opt5-py3-none-any.whl',
                    'methscan-1.1.0+opt5.tar.gz', 'vmrseq_0.99.5.9000.tar.gz',
                    'vmrseq-gpu-runtime.tar.gz')
        packages = destination / 'packages'; packages.mkdir()
        for name in expected:
            (packages / name).write_bytes(z.read(name))
        with tarfile.open(packages / 'vmrseq-gpu-runtime.tar.gz') as t:
            unpack_tar(t, destination / 'vmrseq-gpu')
    inventory = {str(p.relative_to(destination)): digest(p)
                 for p in sorted(destination.rglob('*')) if p.is_file()}
    record = {'schema_version': 1, 'root': str(destination),
              'sources': [{'path': str(p), 'sha256': digest(p)} for p in (bismark[0], combined[0])],
              'files': inventory,
              'bismark': str(entries[0].relative_to(destination)),
              'methscan_wheel': 'packages/methscan-1.1.0+opt5-py3-none-any.whl',
              'vmrseq_source': 'packages/vmrseq_0.99.5.9000.tar.gz',
              'vmrseq_gpu': 'vmrseq-gpu/pipeline_gpu.py'}
    save(destination / 'acceleration.json', record)
    return destination / 'acceleration.json'


def load_registry(path, verify=True):
    path = Path(path).resolve()
    record = json.loads(path.read_text(encoding='utf-8'))
    if record.get('schema_version') != 1:
        raise ValueError('unsupported acceleration registry')
    root = path.parent
    if verify:
        for name, expected in record['files'].items():
            p = (root / name).resolve()
            if not p.is_relative_to(root) or not p.is_file() or digest(p) != expected:
                raise ValueError('acceleration file missing or changed: ' + name)
    return root, record


def install_methscan(registry, python, prefix, cuda=None):
    root, record = load_registry(registry)
    version = json.loads(subprocess.check_output([str(python), '-c',
                         'import sys,json; print(json.dumps(list(sys.version_info[:2])))'], text=True))
    if version[0] != 3 or not 9 <= version[1] <= 11:
        raise ValueError('this release requires a Python 3.9–3.11 provisioning interpreter')
    prefix = Path(prefix).resolve()
    if prefix.exists():
        raise ValueError('refusing to install into an existing environment: ' + str(prefix))
    subprocess.run([str(python), '-m', 'venv', '--copies', str(prefix)], check=True)
    exe = prefix / 'bin/python'
    packages = [str(root / record['methscan_wheel'])]
    if cuda:
        packages.append('cupy-cuda%sx>=13,<14' % cuda)
    with (prefix / 'install.log').open('w') as log:
        subprocess.run([str(exe), '-m', 'pip', 'install', '--only-binary=:all:', *packages],
                       check=True, stdout=log, stderr=subprocess.STDOUT)
    subprocess.run([str(exe), '-m', 'pip', 'check'], check=True)
    subprocess.run([str(prefix / 'bin/methscan'), '--version'], check=True)
    with (prefix / 'requirements.lock.txt').open('w') as lock:
        subprocess.run([str(exe), '-m', 'pip', 'freeze'], check=True, stdout=lock)
    version_code = "from importlib.metadata import version; print('MethSCAn ' + version('methscan'))"
    version = subprocess.check_output([str(exe), '-c', version_code], text=True).strip()
    if version != 'MethSCAn 1.1.0+opt5':
        raise ValueError('unexpected installed package version: ' + version)
    env = {'stage': 'methscan', 'python': str(exe),
           'executable': str(prefix / 'bin/methscan'),
           'version_command': __import__('shlex').join([str(exe), '-c', version_code]),
           'required': 'true', 'package_version': version, 'wheel_sha256': digest(root / record['methscan_wheel']),
           'cuda_extra': cuda}
    save(prefix / 'scautopilot-acceleration.json', env)
    return env


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    s = sub.add_parser('stage'); s.add_argument('--source', type=Path, required=True)
    s.add_argument('--destination', type=Path, required=True)
    v = sub.add_parser('verify'); v.add_argument('--registry', type=Path, required=True)
    i = sub.add_parser('install-methscan'); i.add_argument('--registry', type=Path, required=True)
    i.add_argument('--python', type=Path, required=True); i.add_argument('--prefix', type=Path, required=True)
    i.add_argument('--cuda', choices=['11', '12']); i.add_argument('--execute', action='store_true')
    a = p.parse_args()
    if a.command == 'stage':
        print(stage(a.source, a.destination))
    elif a.command == 'verify':
        root, r = load_registry(a.registry); print(json.dumps({'root': str(root), 'verified_files': len(r['files'])}))
    elif a.execute:
        print(json.dumps(install_methscan(a.registry, a.python, a.prefix, a.cuda), indent=2))
    else:
        load_registry(a.registry)
        print(json.dumps({'action': 'create isolated venv and install local wheel',
                          'python': str(a.python), 'prefix': str(a.prefix), 'cuda': a.cuda,
                          'execute': False}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as e:
        sys.exit(str(e))
