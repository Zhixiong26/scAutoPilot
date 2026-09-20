#!/usr/bin/env python3
"""Validate one chunk of a project's ALLC files, inside a Slurm allocation.

`validate_project.py --mode full` splits the ALLC file list into byte-balanced
chunks and submits one of these per chunk. The reason is mechanical: the
per-line ALLC check is plain Python, so the GIL serialises it and a thread pool
makes a whole-file read *slower* than reading the files one at a time. Only
separate processes -- and, for a terabyte of input, separate nodes -- turn that
loop into parallel work.

This is the worker half. It never decides whether the project is valid; it
reports what it observed for exactly the files it was handed, and the submitter
that wrote the manifest is the one that merges and judges.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from hashlib import sha256
from pathlib import Path

# Resolved from this file so the script works from any working directory, the
# same way Scripts/Common/run_task.py locates the project's tools.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from _common import WorkflowError, host_role, write_json  # noqa: E402
from validate_project import validate_allc_record  # noqa: E402


def manifest_digest(path: Path) -> str:
    return sha256(Path(path).read_bytes()).hexdigest()


def resolve_processes(requested: int) -> int:
    """How many processes this chunk may run.

    The submitted value wins; a hand run falls back to the allocation's CPU
    grant, then to a small fixed number. It is never derived from ``cpu_count``
    on a login node, where that number says nothing about what the job was
    given.
    """
    if requested > 0:
        return requested
    for name in ("SLURM_CPUS_PER_TASK", "SCMO_THREADS"):
        value = str(os.environ.get(name) or "").strip()
        if value.isdigit() and int(value) > 0:
            return int(value)
    return max(1, min(4, os.cpu_count() or 1))


def validate_one(job: tuple) -> dict:
    """Validate one file and report its outcome, never raising.

    A file that fails validation is a finding about the data, not a failure of
    this chunk: the chunk's own exit status has to stay clean so the submitter
    can tell "the task crashed" from "the data is bad". Both are reported, and
    the difference matters because only one of them is worth retrying.
    """
    path, context, full = job
    mode = "full" if full else "quick"
    try:
        record = validate_allc_record(Path(path), context, full)
    except (OSError, EOFError, ValueError, WorkflowError) as exc:
        return {"path": path, "records_checked": 0, "mode": mode, "error": str(exc)}
    return {"path": path, "records_checked": record["records_checked"], "mode": mode, "error": None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--processes", type=int, default=0)
    args = parser.parse_args()

    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WorkflowError("cannot read chunk manifest %s: %s" % (args.manifest, exc))
    paths = [str(value) for value in manifest.get("paths") or []]
    if not paths:
        raise WorkflowError("chunk manifest %s lists no files" % args.manifest)
    context = str(manifest.get("context") or "CGN")
    full = bool(manifest.get("full"))

    processes = resolve_processes(args.processes)
    jobs = [(path, context, full) for path in paths]
    outcomes = []
    # Processes, not threads: see the module docstring. `validate_allc_record`
    # holds the GIL for its whole per-line loop, so a pool of threads would
    # serialise the work and add contention on a shared filesystem on top.
    with ProcessPoolExecutor(max_workers=processes) as pool:
        futures = [pool.submit(validate_one, job) for job in jobs]
        for future in as_completed(futures):
            outcomes.append(future.result())
    outcomes.sort(key=lambda item: item["path"])

    write_json(args.out, {
        "schema_version": 1,
        "manifest_sha256": manifest_digest(args.manifest),
        "paths": paths,
        "processes": processes,
        "host_role": host_role(),
        "outcomes": outcomes,
    })
    failed = sum(1 for item in outcomes if item["error"])
    print("chunk %s: %d files, %d failed, %d processes"
          % (manifest.get("chunk", "?"), len(outcomes), failed, processes))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (WorkflowError, OSError, ValueError) as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        raise SystemExit(2)
