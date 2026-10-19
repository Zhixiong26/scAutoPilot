#!/usr/bin/env python3
"""Build or execute explicit acceleration commands; does not submit DAG tasks."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from bootstrap_acceleration import load_registry, digest
from _common import HOST_ROLE_SUBMIT, host_role


def build_command(a, extra):
    root, record = load_registry(a.registry)
    if extra[:1] == ['--']:
        extra = extra[1:]
    if not extra:
        raise ValueError('supply native tool arguments after --')
    if a.tool == 'bismark':
        return [str(root / record['bismark']), *extra]
    if a.tool == 'methscan':
        if not a.python:
            raise ValueError('MethSCAn requires --python from the isolated accelerated environment')
        # cli.py defines cli(), without a python -m entry point.
        command = [str(a.python), '-c', 'from methscan.cli import cli; cli()', *extra]
        if extra[0] in {'smooth', 'scan', 'diff'}:
            if any(x == '--device' or x.startswith('--device=') for x in extra):
                raise ValueError('set --device on this adapter, before --')
            command += ['--device', a.device]
            # The existing DAG checks smoothed/*.csv. Keep that artifact contract.
            if extra[0] == 'smooth' and a.device == 'gpu' and '--write-csv' not in extra:
                command.append('--write-csv')
        return command
    if a.tool == 'vmrseq-gpu':
        if not (a.python and a.rscript and a.r_library):
            raise ValueError('vmrseq-gpu requires --python, --rscript and --r-library')
        return [str(a.python), str(root / record['vmrseq_gpu']), *extra,
                '--rscript', str(a.rscript), '--r-lib', str(a.r_library)]
    if a.tool == 'vmrseq-cpu':
        if not (a.rscript and a.r_library):
            raise ValueError('vmrseq-cpu requires --rscript and --r-library')
        return [str(a.rscript), '--vanilla', str(Path(__file__).with_name('run_vmrseq_cpu.R')), *extra]
    raise ValueError('unknown acceleration tool')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--registry', type=Path, required=True)
    p.add_argument('--tool', choices=['bismark', 'methscan', 'vmrseq-cpu', 'vmrseq-gpu'], required=True)
    p.add_argument('--python', type=Path); p.add_argument('--rscript', type=Path)
    p.add_argument('--r-library', type=Path)
    p.add_argument('--device', choices=['cpu', 'gpu'], default='cpu', help='MethSCAn device')
    p.add_argument('--execute', action='store_true')
    p.add_argument('--evidence', type=Path, help='new JSON command/exit record; not DAG completion evidence')
    p.add_argument('arguments', nargs=argparse.REMAINDER)
    a = p.parse_args()
    command = build_command(a, a.arguments)
    evidence = {'schema_version': 1, 'tool': a.tool, 'command': command,
                'registry': str(a.registry.resolve()), 'registry_sha256': digest(a.registry), 'execute': a.execute,
                'status': 'planned', 'dag_completion': False}
    if not a.execute:
        print(json.dumps(evidence, indent=2)); return
    if host_role() == HOST_ROLE_SUBMIT:
        raise ValueError('run acceleration on a compute allocation, not a Slurm submit host')
    if a.tool == 'methscan':
        code = "from importlib.metadata import version; print(version('methscan'))"
        version = subprocess.check_output([str(a.python), '-c', code], text=True).strip()
        if version != '1.1.0+opt5':
            raise ValueError('expected accelerated MethSCAn 1.1.0+opt5, found ' + version)
        evidence['package_version'] = version
    if a.evidence and a.evidence.exists():
        raise ValueError('evidence already exists; choose a new path')
    env = os.environ.copy()
    if a.tool == 'bismark':
        # The bundled Bowtie2 launcher needs python3 on compute-node PATH.
        interpreter = a.python or Path(sys.executable)
        env['PATH'] = str(interpreter.absolute().parent) + os.pathsep + env.get('PATH', '')
    if a.r_library:
        env['R_LIBS_USER'] = str(a.r_library.resolve())
    if a.evidence:
        a.evidence.parent.mkdir(parents=True, exist_ok=True)
        a.evidence.write_text(json.dumps(evidence, indent=2) + '\n')
    try:
        result = subprocess.run(command, env=env)
        evidence.update(status='exited', returncode=result.returncode)
    except OSError as e:
        evidence.update(status='launch_failed', error=str(e), returncode=127)
    if a.evidence:
        a.evidence.write_text(json.dumps(evidence, indent=2) + '\n')
    sys.exit(evidence['returncode'])


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as e:
        sys.exit(str(e))
