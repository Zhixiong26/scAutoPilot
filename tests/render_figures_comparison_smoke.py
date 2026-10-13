#!/usr/bin/env python3
"""Render synthetic batch fixtures on a compute node; preserve files for review."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_figures_comparison import SourceAdapterTests
from figures_comparison_evidence import sha, validate_manifest
import figures_comparison as renderer
from _common import submit_host_execution_allowed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not submit_host_execution_allowed('figure-smoke'):
        raise RuntimeError('render smoke requires compute allocation or standalone host')
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    fixture = SourceAdapterTests()
    fixture.setUp()
    fixture.root = root
    try:
        run_dir, result, plan, spec = fixture.populate(('scanpy', 'methylvi_allcools'))
        output = renderer.run(root, 'test')
        manifest = output / 'delivery_manifest.json'
        before = sha(manifest)
        renderer.run(root, 'test')
        if before != sha(manifest):
            raise AssertionError('resume modified delivery')
        data = validate_manifest(manifest)
        report = {'status': 'passed', 'slurm_job_id': os.environ.get('SLURM_JOB_ID'),
                  'manifest': str(manifest), 'panels': len(data['panels']),
                  'atlases': len(data['figures']), 'resume_preserves_manifest': True}
        (root/'smoke_report.json').write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(report, indent=2))
    finally:
        fixture.temp.cleanup()


if __name__ == '__main__':
    main()
