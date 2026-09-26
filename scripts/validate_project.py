#!/usr/bin/env python3
"""Read-only quick/full preflight for inputs, references, environments, and routes."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import re
import shlex
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from _common import (
    HOST_ROLE_STANDALONE, HOST_ROLE_SUBMIT, TERMINAL_BAD_STATES, WorkflowError,
    effective_backend, host_role, host_role_source, load_environments, load_project, load_samples,
    notebook_cells_digest,
    parse_memory_mb, parse_walltime_seconds, plan_data_sources, project_files, resolve_path,
    normalize_job_state, sha256_file, signature, stored_data_sources, write_json,
)


# Importing torch/scvi on a cold shared filesystem routinely takes longer than
# 30 seconds even when the environment is healthy.  This probe is a preflight,
# not an interactive request; allow enough time to distinguish cold start from
# a broken command while still bounding a hung version check.
VERSION_CHECK_TIMEOUT_SECONDS = 120


# --- ALLC fan-out ------------------------------------------------------------
#
# The per-file ALLC check is a whole-file read in plain Python, so its cost is
# per-line and its parallelism has to be processes on compute nodes. A measured
# run on a real project: one 18 MB file takes 5.5 s in full mode (4.9M lines),
# and reading four files through a 4-thread pool took 2.3x *longer* than reading
# them one after another, because the GIL serialises the loop. For tens of
# thousands of files the difference is hours against days.
#
# Processes do scale: 32 of them (8 chunks x 4) read a 3,232-file, 132 GB sample
# in 23 minutes at 3.0 MB/s each, against 3.2 MB/s for one process reading
# alone, so the shared mount was not the limit at that width and the speedup was
# the concurrency. Threads are the thing to avoid here, not concurrency.
#
# Discovery stays here. Only the per-file work is distributed, because
# `allc_inventory` and `allc_cell_ids` are inputs to `input_signature`, and a
# signature computed from a different enumeration on a different host could not
# be compared against the one planning recorded.

# Below this many files the fan-out costs more than it saves: submitting and
# polling jobs is slower than reading a handful of files in place.
FANOUT_MIN_FILES = 32
# The inventory is split into four waves' worth of chunks so that a wide project
# cannot flood the queue, but never so finely that a chunk holds a file or two:
# each chunk is a job with its own allocation and startup, and one that reads a
# single file spends longer starting than reading.
FANOUT_WAVES = 4
FANOUT_MIN_FILES_PER_CHUNK = 8
FANOUT_DIRECTORY = "allc-fanout"
JOB_POLL_SECONDS = 15
# A job Slurm has accepted can briefly be in neither the queue nor accounting.
# After this long in neither, it is reported missing instead of being waited on
# until the deadline, so a lost job surfaces in minutes rather than hours.
LOST_JOB_GRACE_SECONDS = 300
JOB_TERMINAL_GOOD = {"COMPLETED", "completed"}
JOB_TERMINAL_LOST = {"MISSING", "TIMEOUT"}


def slurm_job_state(job_id: str) -> str:
    """The state of one job, or "" when neither the queue nor accounting knows it."""
    try:
        queued = subprocess.check_output(
            ["squeue", "-h", "-j", str(job_id), "-o", "%T"], stderr=subprocess.STDOUT,
        ).decode("utf-8").strip().splitlines()
    except (OSError, subprocess.SubprocessError):
        return ""
    if queued:
        return normalize_job_state(queued[0])
    try:
        history = subprocess.check_output(
            ["sacct", "-n", "-X", "-j", str(job_id), "--format=State", "--parsable2"],
            stderr=subprocess.STDOUT,
        ).decode("utf-8").strip().splitlines()
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in history:
        state = normalize_job_state(line.split("|", 1)[0])
        if state:
            return state
    return ""


def job_settled(state: str) -> bool:
    """True when a scheduler state means the job will not change on its own."""
    return state in TERMINAL_BAD_STATES or state in JOB_TERMINAL_GOOD or state in JOB_TERMINAL_LOST


def wait_for_jobs(job_ids: list, timeout: float) -> dict:
    """Poll until every job is terminal, and report what each one became.

    A job that has been observed in a queue state is not finished, however
    recently its state was read. Only a settled state ends the wait, or a
    submission would be merged while its chunks were still queued.
    """
    states = {job_id: "" for job_id in job_ids}
    missing_since = {}
    deadline = time.monotonic() + timeout
    while True:
        for job_id in job_ids:
            if job_settled(states[job_id]):
                continue
            observed = slurm_job_state(job_id)
            if observed:
                states[job_id] = observed
                missing_since.pop(job_id, None)
            # A job neither queued nor in accounting is not settled either; it is
            # given a grace period before being called missing.
            elif time.monotonic() - missing_since.setdefault(job_id, time.monotonic()) > LOST_JOB_GRACE_SECONDS:
                states[job_id] = "MISSING"
        pending = [job_id for job_id in job_ids if not job_settled(states[job_id])]
        if not pending:
            return states
        if time.monotonic() > deadline:
            for job_id in pending:
                states[job_id] = "TIMEOUT"
            return states
        time.sleep(JOB_POLL_SECONDS)


def split_allc_chunks(entries: list, chunks: int) -> list:
    """Byte-balanced, deterministic split of ALLC paths into `chunks` groups.

    Longest-processing-time first: the largest file left goes to the lightest
    group. File sizes span two orders of magnitude in a real project (median
    16 MB against a 488 MB maximum), so splitting on file count would hand one
    chunk several times the work of another and the whole fan-out would wait on
    that one chunk. Ties resolve on the path, so the same inventory always
    produces the same split and a chunk result stays comparable across runs.
    """
    groups = [[] for _ in range(max(1, chunks))]
    loads = [0] * len(groups)
    for entry in sorted(entries, key=lambda item: (-int(item.get("size") or 0), str(item["path"]))):
        index = loads.index(min(loads))
        groups[index].append(str(entry["path"]))
        loads[index] += int(entry.get("size") or 0)
    for group in groups:
        group.sort()
    return [group for group in groups if group]


def chunk_label(manifest_path: Path) -> str:
    """The chunk an error is about, named the way the files on disk are named."""
    return Path(manifest_path).name.split(".", 1)[0]


def read_chunk_result(out_path: Path, manifest_path: Path, expected: list) -> tuple:
    """Read one chunk's result, or explain why it cannot be trusted.

    Fail closed. A chunk that is missing, unreadable, built from a different
    manifest, or does not account for exactly the files it was handed is an
    error -- never a smaller set of validated files that still reads as valid.
    The whole point of validating inputs is that a partial check must not pass
    for a complete one.
    """
    if not out_path.is_file():
        return [], ["ALLC chunk %s produced no result file: %s" % (chunk_label(manifest_path), out_path)]
    try:
        payload = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [], ["ALLC chunk %s has an unreadable result: %s" % (chunk_label(manifest_path), exc)]
    expected_digest = sha256_file(manifest_path)
    if str(payload.get("manifest_sha256") or "") != expected_digest:
        return [], ["ALLC chunk %s was built from a different manifest than the one on disk; "
                    "its result cannot be attributed to this input set" % chunk_label(manifest_path)]
    reported = [str(value) for value in payload.get("paths") or []]
    if sorted(reported) != sorted(expected):
        return [], ["ALLC chunk %s reported %d files where the manifest listed %d"
                    % (chunk_label(manifest_path), len(reported), len(expected))]
    outcomes = payload.get("outcomes") or []
    seen = [str(item.get("path") or "") for item in outcomes]
    if sorted(seen) != sorted(expected):
        return [], ["ALLC chunk %s accounted for %d of its %d files"
                    % (chunk_label(manifest_path), len(seen), len(expected))]
    records, chunk_errors = [], []
    for item in outcomes:
        if item.get("error"):
            chunk_errors.append(str(item["error"]))
        else:
            records.append({"path": item["path"], "records_checked": item.get("records_checked", 0),
                            "mode": item.get("mode", "full")})
    return records, chunk_errors


def fanout_partition(scheduler: dict) -> str:
    """The partition a chunk job would go to, or "" when the project names none.

    A profile-level partition wins, so one project can send its reads somewhere
    other than its analysis; otherwise the first allowed partition is used. The
    fan-out submits the whole set to one partition rather than spreading it, so
    every chunk is queued under the same admission rules.
    """
    profiles = scheduler.get("profiles") or {}
    profile = profiles.get("validation") or profiles.get("default") or {}
    named = str(profile.get("partition") or "").strip()
    if named:
        return named
    partitions = [str(value) for value in scheduler.get("partitions") or []]
    return partitions[0] if partitions else ""


def fanout_allc_validation(root: Path, entries: list, context: str, scheduler: dict,
                           python: str) -> tuple:
    """Validate every ALLC file through chunks submitted to compute nodes.

    Returns `(records, errors, note)`. Chunk tasks run in waves rather than all
    at once so a wide project cannot flood the queue, and a chunk whose result
    is on disk and still matches its manifest is reused instead of resubmitted,
    because a full read of a real project takes hours and a single failed chunk
    should not cost the whole run.
    """
    profiles = scheduler.get("profiles") or {}
    profile = profiles.get("validation") or profiles.get("default") or {}
    target = profile.get("target") or {}
    partition = fanout_partition(scheduler)
    parallel = max(1, int(scheduler.get("validation_parallel") or 8))
    processes = max(1, int(scheduler.get("validation_processes_per_task") or 4))
    # Derived, not configured: the number of chunks changes how evenly the work
    # is spread and how much a failed chunk costs to redo, but it is not a
    # resource budget, and a knob nobody writes is a knob that silently does
    # nothing. What a caller sizes is the concurrency above.
    per_chunk_files = (len(entries) + FANOUT_MIN_FILES_PER_CHUNK - 1) // FANOUT_MIN_FILES_PER_CHUNK
    chunk_count = max(1, min(parallel * FANOUT_WAVES, per_chunk_files))
    # The allocation has to cover the processes this chunk will actually start,
    # so a raised `validation_processes_per_task` cannot end up running eight
    # workers on the four cores the profile happens to name.
    cores = max(processes, int(target.get("cpus") or 0))
    walltime = parse_walltime_seconds(target.get("time") or "04:00:00")

    wrapper = root / "Scripts" / "Common" / "run_task.sbatch"
    chunk_script = root / "Scripts" / "Common" / "validate_allc_chunk.py"
    for required in (wrapper, chunk_script):
        if not required.is_file():
            return [], ["ALLC fan-out needs %s, which this project does not have" % required], {}

    groups = split_allc_chunks(entries, chunk_count)
    chunk_root = root / ".workflow" / "validations" / FANOUT_DIRECTORY
    logs = chunk_root / "logs"
    logs.mkdir(parents=True, exist_ok=True)

    manifests, outs, sbatch_lines, job_ids, reused = [], [], [], [], 0
    for index, paths in enumerate(groups):
        manifest = chunk_root / ("chunk_%03d.manifest.json" % index)
        out = chunk_root / ("chunk_%03d.out.json" % index)
        write_json(manifest, {"schema_version": 1, "chunk": index, "context": context,
                              "full": True, "paths": paths})
        manifests.append(manifest)
        outs.append(out)

    def submit(index: int) -> str:
        manifest, out = manifests[index], outs[index]
        command = [
            "sbatch", "--parsable", "--job-name", "scmo_validate_%03d" % index,
            "--partition", partition,
            "--cpus-per-task", str(cores),
            "--mem", str(target.get("memory") or "8G"),
            "--time", str(target.get("time") or "04:00:00"),
            "--output", str(logs / ("chunk_%03d_%%j.out" % index)),
            "--error", str(logs / ("chunk_%03d_%%j.err" % index)),
            str(wrapper), python, str(chunk_script),
            "--project", str(root), "--manifest", str(manifest), "--out", str(out),
            "--processes", str(processes),
        ]
        output = subprocess.check_output(command, cwd=str(root), stderr=subprocess.STDOUT)
        sbatch_lines.append(command)
        return output.decode("utf-8").strip().split(";", 1)[0]

    # One wave of chunks may legitimately run for its whole submitted limit, so
    # the overall deadline is that limit per wave plus slack. A fixed total would
    # time out a healthy run whenever the waves add up to more than it, which for
    # a project sized like this one they do. Jobs that are actually lost are
    # caught by the much shorter grace in `wait_for_jobs`, not by this.
    waves = (len(manifests) + parallel - 1) // parallel
    deadline = time.monotonic() + max(3600.0, walltime * waves * 1.5)
    for start in range(0, len(manifests), parallel):
        wave, wave_ids = [], []
        for index in range(start, min(start + parallel, len(manifests))):
            expected_digest = sha256_file(manifests[index])
            if outs[index].is_file():
                try:
                    cached = json.loads(outs[index].read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    cached = {}
                if str(cached.get("manifest_sha256") or "") == expected_digest:
                    reused += 1
                    continue
            job_id = submit(index)
            job_ids.append(job_id)
            wave_ids.append(job_id)
            wave.append(index)
        if wave_ids:
            remaining = max(1.0, deadline - time.monotonic())
            states = wait_for_jobs(wave_ids, remaining)
            bad = ["chunk %03d (%s)" % (index, states[job_id])
                   for index, job_id in zip(wave, wave_ids)
                   if states[job_id] not in JOB_TERMINAL_GOOD]
            if bad:
                return [], ["ALLC validation chunk(s) did not complete: %s" % ", ".join(bad)], {}

    records, errors = [], []
    for index, (manifest, out) in enumerate(zip(manifests, outs)):
        specs = json.loads(manifest.read_text(encoding="utf-8"))
        chunk_records, chunk_errors = read_chunk_result(out, manifest, specs["paths"])
        records.extend(chunk_records)
        errors.extend(chunk_errors)

    note = {"chunks": len(groups), "parallel": parallel, "processes_per_chunk": processes,
            "reused_chunks": reused, "job_ids": job_ids, "sbatch": sbatch_lines}
    return records, errors, note


def context_matches(observed: str, expected: str) -> bool:
    observed, expected = observed.upper(), expected.upper()
    return observed.startswith(expected[:-1]) if expected.endswith("N") else observed == expected


def validate_allc_record(path: Path, context: str = "CGN", full: bool = False) -> dict:
    opener = gzip.open if path.name.endswith(".gz") else open
    saw_context, records, current_chrom, last_position, seen_chroms = False, 0, None, None, set()
    with opener(str(path), "rt") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 6:
                raise WorkflowError("%s:%d has fewer than 6 ALLC columns" % (path, line_number))
            try:
                position, mc, cov = int(fields[1]), int(fields[4]), int(fields[5])
            except ValueError:
                if line_number == 1:
                    continue
                raise WorkflowError("%s:%d has invalid integer fields" % (path, line_number))
            if position < 1 or mc < 0 or cov < 0 or mc > cov:
                raise WorkflowError("%s:%d has invalid ALLC counts" % (path, line_number))
            if full:
                if fields[0] != current_chrom:
                    if fields[0] in seen_chroms:
                        raise WorkflowError("%s:%d repeats a completed chromosome block" % (path, line_number))
                    seen_chroms.add(fields[0])
                    current_chrom, last_position = fields[0], None
                if last_position is not None and position < last_position:
                    raise WorkflowError("%s:%d is not coordinate sorted" % (path, line_number))
                last_position = position
            saw_context = saw_context or context_matches(fields[3], context)
            records += 1
            if not full and records >= 100 and saw_context:
                break
    if not saw_context:
        raise WorkflowError("ALLC preflight found no %s context in checked records: %s" % (context, path))
    return {"path": str(path.resolve()), "records_checked": records,
            "mode": "full" if full else "quick"}


def allc_cell_id(path: Path, row: dict) -> str:
    regex = row.get("allc_cell_id_regex", "").strip()
    replacement = row.get("allc_cell_id_replacement", "")
    if regex:
        match = re.search(regex, path.name)
        if not match:
            raise WorkflowError("ALLC filename does not match configured cell-ID regex: %s" % path)
        value = match.expand(replacement) if replacement else (match.groupdict().get("cell_id") or match.group(0))
    else:
        value = path.name
        for suffix in (".allc.tsv.gz", "_allc.gz", ".allc.gz"):
            if value.endswith(suffix):
                value = value[:-len(suffix)]
                break
    if not value:
        raise WorkflowError("ALLC filename produced an empty cell ID: %s" % path)
    prefix = row["cell_id_prefix"]
    return value if not prefix or value.startswith(prefix + "_") else prefix + "_" + value


def validate(project: Path, require_paths: bool = True, mode: str = "quick", workers: int = 1,
             required_stages: set[str] | None = None,
             selected_routes: set[str] | None = None) -> dict:
    if mode not in {"quick", "full"}:
        raise WorkflowError("validation mode must be quick or full")
    files = project_files(project)
    cfg = load_project(project)
    samples = load_samples(project, require_paths=require_paths)
    active = [row for row in samples if row["include"]]
    errors, warnings = [], []
    if int(cfg.get("schema_version", 1)) == 1:
        warnings.append("schema v1 is deprecated; migrate the project configuration to schema v2")
    all_rna_samples = [row for row in active if row["rna_path"]]
    all_allc_samples = [row for row in active if row["allc_root"]]
    use_rna = selected_routes is None or "scanpy" in selected_routes
    use_allc = selected_routes is None or bool(selected_routes - {"scanpy"})
    rna_samples = all_rna_samples if use_rna else []
    allc_samples = all_allc_samples if use_allc else []
    if use_rna:
        palette = cfg.get("analysis", {}).get("scanpy", {}).get("sample_palette", [])
        if not isinstance(palette, list) or len(palette) < len(all_rna_samples):
            errors.append(
                "analysis.scanpy.sample_palette must provide at least %d colours for %d RNA samples"
                % (len(all_rna_samples), len(all_rna_samples))
            )
    allc_inventory, allc_cell_ids, validation_jobs = [], [], []
    context = str(cfg.get("analysis", {}).get("allcools", {}).get("mc_context", "CGN"))
    thresholds = cfg.get("analysis", {}).get("methscan", {}).get("vmr_thresholds", [0.01, 0.02, 0.05])
    needs_thresholds = selected_routes is None or bool(selected_routes & {
        "methscan_vmr", "methscan_dmr", "methylvi_vmr", "methylvi_vmr_dmr",
    })
    if needs_thresholds and (not isinstance(thresholds, list) or not thresholds):
        errors.append("analysis.methscan.vmr_thresholds must be a non-empty list")
    elif needs_thresholds:
        try:
            numeric_thresholds = [float(value) for value in thresholds]
            if any(value <= 0 or value > 1 for value in numeric_thresholds):
                errors.append("analysis.methscan.vmr_thresholds values must satisfy 0 < value <= 1")
            if len(set(numeric_thresholds)) != len(numeric_thresholds):
                errors.append("analysis.methscan.vmr_thresholds values must be unique")
        except (TypeError, ValueError):
            errors.append("analysis.methscan.vmr_thresholds values must be numeric")
    feature_targets = cfg.get("analysis", {}).get("methylvi", {}).get("feature_targets", [10000, 30000])
    needs_features = selected_routes is None or bool(selected_routes & {
        "allcools", "methylvi_allcools", "methylvi_vmr", "methylvi_vmr_dmr",
    })
    if needs_features and (not isinstance(feature_targets, list) or not feature_targets):
        errors.append("analysis.methylvi.feature_targets must be a non-empty list")
    elif needs_features:
        valid_targets = all(isinstance(value, int) and not isinstance(value, bool) and value > 0
                            for value in feature_targets)
        if not valid_targets:
            errors.append("analysis.methylvi.feature_targets values must be positive integers")
        elif len(set(feature_targets)) != len(feature_targets):
            errors.append("analysis.methylvi.feature_targets values must be unique")
    for row in allc_samples:
        root = Path(row["allc_root"])
        pattern = row["allc_glob"].strip() or "**/*.allc.tsv.gz"
        paths = sorted(path for path in root.glob(pattern) if path.is_file()) if root.exists() else []
        if require_paths and not paths:
            errors.append("sample %s has no ALLC matching %s" % (row["sample_id"], pattern))
        for path in paths:
            if not Path(str(path) + ".tbi").is_file():
                errors.append("indexed ALLC is missing .tbi: %s" % path)
            try:
                allc_cell_ids.append(allc_cell_id(path, row))
            except WorkflowError as exc:
                errors.append(str(exc))
            stat = path.stat()
            allc_inventory.append({"path": str(path.resolve()), "size": stat.st_size,
                                   "mtime_ns": stat.st_mtime_ns, "sample_id": row["sample_id"]})
            if require_paths:
                validation_jobs.append(path)
    # Read here rather than later because the fan-out needs the orchestrator
    # interpreter, and so does the environment check further down.
    environment_rows = load_environments(project)
    scheduler = cfg.get("scheduler") or {}
    allc_validation, fanout_note = [], {}
    if validation_jobs:
        orchestrator = next((row for row in environment_rows if row["stage"].strip() == "orchestrator"), None)
        fanout_python = resolve_path(files["root"], orchestrator["python"]) if orchestrator else None
        root_scripts = files["root"] / "Scripts" / "Common"
        backend_effective, _ = effective_backend(scheduler)
        # The fan-out is for the case it was written for: a full read of a real
        # project's ALLC files, on a host that has somewhere to submit it. Every
        # other case -- a small project, a machine with no controller, an
        # incomplete template, a project that names no partition -- reads in
        # place, because submitting jobs would cost more than the work or could
        # not be done at all. An empty partition would reach `sbatch --partition`
        # as an empty argument and fail there, after the work had been promised.
        if (mode == "full" and len(validation_jobs) >= FANOUT_MIN_FILES
                and backend_effective == "slurm"
                and host_role() != HOST_ROLE_STANDALONE
                and fanout_partition(scheduler)
                and (root_scripts / "run_task.sbatch").is_file()
                and (root_scripts / "validate_allc_chunk.py").is_file()
                and fanout_python is not None and fanout_python.is_file()):
            allc_validation, fanout_errors, fanout_note = fanout_allc_validation(
                files["root"], allc_inventory, context, scheduler, str(fanout_python))
            errors.extend(fanout_errors)
        else:
            # Processes rather than threads: the per-line check holds the GIL for
            # its whole loop, so a thread pool serialises the work and adds
            # contention on a shared filesystem on top of that.
            with ProcessPoolExecutor(max_workers=max(1, workers)) as pool:
                futures = {pool.submit(validate_allc_record, path, context, mode == "full"): path
                           for path in validation_jobs}
                for future in as_completed(futures):
                    try:
                        allc_validation.append(future.result())
                    except (OSError, EOFError, ValueError, WorkflowError) as exc:
                        errors.append(str(exc))
    if len(set(allc_cell_ids)) != len(allc_cell_ids):
        errors.append("ALLC-derived cell IDs must be unique across included samples")

    # Declared inputs are checked where they will be read, not where they were
    # declared: a link that resolves on the login host and dangles on the compute
    # host is the failure this catches, and it names the link rather than the stage.
    data_plans = plan_data_sources(files["root"], stored_data_sources(cfg))
    data_validation = []
    for plan in data_plans:
        entry = {"name": plan["name"], "destination": plan["destination"],
                 "state": plan["state"], "origin": plan["url"] or plan["target"]}
        if plan["state"] == "conflict":
            errors.append("Data/%s exists but is not the entry data.sources declares (%s)"
                          % (plan["name"], entry["origin"]))
        elif plan["state"] == "dangling" and require_paths:
            errors.append("Data/%s does not resolve: %s is not reachable from here, so every stage would "
                          "fail on it. Run `python tools/link_data.py --project . --execute` where both are "
                          "visible, or validate from the execution context" % (plan["name"], entry["origin"]))
        elif plan["state"] == "download" and require_paths:
            errors.append("Data/%s is declared as a download and has not been fetched; run "
                          "`python tools/link_data.py --project . --execute`" % plan["name"])
        elif plan["state"] == "present" and mode == "full":
            # Deferred to full mode: the digest is the only thing that can tell a
            # finished transfer from a truncated one, and it reads the whole file.
            observed = sha256_file(Path(plan["destination"]))
            if observed.lower() != plan["sha256"]:
                errors.append("Data/%s has sha256 %s, not the declared %s"
                              % (plan["name"], observed, plan["sha256"]))
            entry["sha256"] = observed
        data_validation.append(entry)

    references = cfg.get("references") or {}
    reference_hashes = {}
    for key in ("chrom_sizes", "blacklist", "tss_bed"):
        value = references.get(key)
        if not value:
            continue
        path = resolve_path(files["root"], value)
        if require_paths and (path is None or not path.is_file()):
            errors.append("reference %s does not exist: %s" % (key, path))
        elif path and path.is_file():
            reference_hashes[key] = sha256_file(path)
            expected = references.get(key + "_sha256")
            if expected and expected.lower() != reference_hashes[key].lower():
                errors.append("reference checksum mismatch for %s" % key)
    if allc_samples:
        for key in ("chrom_sizes", "blacklist"):
            if not references.get(key):
                errors.append("methylation routes require reference %s" % key)

    annotation = cfg.get("annotation") or {}
    legacy = annotation.get("path")
    if legacy and not annotation.get("table"):
        warnings.append("annotation.path is deprecated; migrate it to annotation.table")
    annotation_path = resolve_path(files["root"], annotation.get("table") or legacy)
    annotation_profile = resolve_path(files["root"], annotation.get("profile"))
    if annotation_path and require_paths and not annotation_path.is_file():
        errors.append("annotation does not exist: %s" % annotation_path)
    if annotation_profile and require_paths and not annotation_profile.is_file():
        errors.append("annotation profile does not exist: %s" % annotation_profile)
    annotation_available = bool(annotation_path and (annotation_path.is_file() or not require_paths))
    annotation_rows, annotation_hash = [], None
    cell_column = annotation.get("cell_id_column", "cell_id")
    type_column = annotation.get("cell_type_column", "cell_type")
    if annotation_path and annotation_path.is_file():
        annotation_hash = sha256_file(annotation_path)
        with annotation_path.open("r", encoding="utf-8", newline="") as handle:
            annotation_rows = list(csv.DictReader(handle, delimiter="\t"))
        if not annotation_rows or cell_column not in annotation_rows[0] or type_column not in annotation_rows[0]:
            errors.append("annotation must contain %s and %s" % (cell_column, type_column))
        elif len({row[cell_column] for row in annotation_rows}) != len(annotation_rows):
            errors.append("annotation cell IDs must be unique")
        elif any(not row[cell_column].strip() or not row[type_column].strip() for row in annotation_rows):
            errors.append("annotation cell IDs and cell types must be non-empty")

    env_results = []
    if required_stages is None:
        required_stages = {"orchestrator", "scanpy_allcools"}
        if allc_samples:
            required_stages.update({"methscan", "methylvi"})
    for env in environment_rows:
        declared_required = env["required"].strip().lower() in {"1", "true", "yes"}
        required = env["stage"].strip() in required_stages
        executable = resolve_path(files["root"], env["executable"])
        python = resolve_path(files["root"], env["python"])
        item = {"stage": env["stage"], "required": required, "declared_required": declared_required,
                "python": str(python) if python else "",
                "executable": str(executable) if executable else ""}
        if required and require_paths and (python is None or not python.is_file()):
            errors.append("required Python is absent for %s: %s" % (env["stage"], python))
        if required and require_paths and (executable is None or not executable.is_file()):
            errors.append("required executable is absent for %s: %s" % (env["stage"], executable))
            item["status"] = "missing"
        else:
            item["status"] = "present" if executable and executable.exists() else "optional_absent"
        if required and env["version_command"].strip() and item["status"] == "present":
            try:
                output = subprocess.check_output(
                    shlex.split(env["version_command"]),
                    stderr=subprocess.STDOUT,
                    timeout=VERSION_CHECK_TIMEOUT_SECONDS,
                )
                item["version"] = output.decode("utf-8", "replace").strip().splitlines()[0]
            except (OSError, subprocess.SubprocessError) as exc:
                errors.append("version check failed for %s: %s" % (env["stage"], exc))
        env_results.append(item)
    declared_stages = {row["stage"].strip() for row in environment_rows}
    missing_stages = sorted(required_stages - declared_stages)
    if missing_stages:
        errors.append("required environment stages are absent: %s; run tools/bootstrap_environments.py --project PROJECT --execute" % ", ".join(missing_stages))

    backend = scheduler.get("backend", "local")
    if backend not in {"local", "slurm"}:
        errors.append("scheduler.backend must be local or slurm")
    if backend == "slurm" and not scheduler.get("partitions"):
        errors.append("Slurm backend requires a non-empty scheduler.partitions allow-list")
    # A warning, not an error. Planning and a dry run change nothing on disk, and
    # a read-only preflight has to stay usable from a host that is not the one the
    # work will run on -- the same reason --allow-missing-paths exists. The guard
    # that decides is at execution, where the task would actually start.
    role = host_role()
    if backend == "local" and role == HOST_ROLE_SUBMIT:
        warnings.append("scheduler.backend is local but this host is a Slurm submit host (login node): "
                        "submission promotes this run to Slurm, and a task executed here directly "
                        "would run on the login node. Use backend slurm, or run inside an allocation.")
    elif backend == "slurm" and role == HOST_ROLE_STANDALONE:
        warnings.append("scheduler.backend is slurm but no Slurm controller answers from this host: "
                        "compute resources cannot be inspected here, and submission will fail.")
    profiles = scheduler.get("profiles") or {}
    required_profiles = {"scanpy", "io_builder", "serial", "methscan_branch", "dmr",
                         "dmr_prepare", "feature_builder", "trainer", "plot", "summary"}
    for name in sorted(required_profiles):
        profile = profiles.get(name) or profiles.get("default")
        if not profile or any(level not in profile for level in ("floor", "target", "ceiling")):
            errors.append("scheduler resource profile %s lacks floor/target/ceiling" % name)
    for name, profile in sorted(profiles.items()):
        # A profile that is not monotonic cannot mean what its author intended: inspect_resources
        # clamps the target down to the ceiling and refuses any node below the floor, so a floor
        # above the target asks for more than the job will ever request. The `dmr` floor once sat
        # below the parallelism its own stage declares -- the same class of mistake -- so the
        # ordering is checked here rather than discovered as a failed task on a busy node.
        if not isinstance(profile, dict) or any(level not in profile for level in ("floor", "target", "ceiling")):
            continue  # already reported above when the profile is one of the required ones
        levels = ("floor", "target", "ceiling")
        try:
            cpus = {level: int(profile[level]["cpus"]) for level in levels}
            memory = {level: parse_memory_mb(profile[level]["memory"]) for level in levels}
        except (KeyError, TypeError, ValueError, WorkflowError) as exc:
            errors.append("scheduler resource profile %s has an unreadable cpus/memory value: %s"
                          % (name, exc))
            continue
        for field, values in (("cpus", cpus), ("memory", memory)):
            if not values["floor"] <= values["target"] <= values["ceiling"]:
                errors.append(
                    "scheduler resource profile %s must satisfy floor <= target <= ceiling for %s; "
                    "it declares %s"
                    % (name, field, " <= ".join(str(values[level]) for level in levels)))

    minimum = int(cfg.get("analysis", {}).get("methscan", {}).get("min_cells", 6))
    selected_annotation = annotation_rows
    if allc_cell_ids and annotation_rows and cell_column in annotation_rows[0] and type_column in annotation_rows[0]:
        allc_set = set(allc_cell_ids)
        selected_annotation = [row for row in annotation_rows if row[cell_column] in allc_set]
        if not selected_annotation:
            warnings.append("annotation contains no cell IDs matching included ALLC inputs")
    annotated_types = {}
    for row in selected_annotation:
        label = row.get(type_column, "").strip()
        if label:
            annotated_types[label] = annotated_types.get(label, 0) + 1
    eligible_types = {label: count for label, count in annotated_types.items() if count >= minimum}
    forbidden = sorted(set(annotated_types) & {"NA", "Unassigned", "requires_review"})
    approved = annotation.get("review_status", "unreviewed") == "approved"
    dmr_ready = bool(allc_samples and annotation_available and approved and len(eligible_types) >= 2 and not forbidden)
    if allc_samples and annotation_available and not dmr_ready:
        warnings.append("cell-type DMR routes require approved annotation, no placeholder labels, and at least two cell types with >= %d matching cells" % minimum)
    routes = {
        "scanpy": bool(all_rna_samples), "methscan_vmr": bool(all_allc_samples), "methscan_dmr": dmr_ready,
        "allcools": bool(all_allc_samples), "methylvi_allcools": bool(all_allc_samples),
        "methylvi_vmr": bool(all_allc_samples), "methylvi_vmr_dmr": dmr_ready,
    }
    if allc_samples and not annotation_available:
        warnings.append("cell-type DMR routes are disabled until an annotation table is provided")

    rna_inventory = []
    for row in rna_samples:
        path = Path(row["rna_path"])
        stat = path.stat()
        rna_inventory.append({"path": str(path.resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    code_hashes, code_suffixes = {}, {".py", ".sh", ".sbatch"}
    for code_root in (files["root"] / "Scripts", files["root"] / "tools"):
        if code_root.exists():
            for path in sorted(item for item in code_root.rglob("*") if item.is_file() and item.suffix in code_suffixes):
                code_hashes[str(path.relative_to(files["root"]))] = sha256_file(path)
            # Notebooks are executable inputs, but outputs, execution counts and
            # review metadata are not. Hash only cell type/source so a code-cell
            # edit invalidates a frozen plan without making normal execution do so.
            for path in sorted(code_root.rglob("*.ipynb")):
                code_hashes[str(path.relative_to(files["root"]))] = notebook_cells_digest(path)
    spec_root = files["root"] / "environment-specs"
    if spec_root.exists():
        for path in sorted(spec_root.glob("*.yaml")):
            code_hashes[str(path.relative_to(files["root"]))] = sha256_file(path)
    workflow_entry = files["root"] / "workflow.py"
    if workflow_entry.is_file():
        code_hashes[str(workflow_entry.relative_to(files["root"]))] = sha256_file(workflow_entry)
    code_signature = signature(code_hashes)
    payload = {
        "status": "invalid" if errors else "valid", "schema_version": 2,
        "project": str(files["root"]), "validation_mode": mode,
        "selected_routes": sorted(selected_routes) if selected_routes is not None else None,
        "counts": {"samples": len(active), "rna_samples": len(rna_samples),
                   "allc_samples": len(allc_samples), "allc_cells": len(allc_inventory)},
        "routes": routes, "references": reference_hashes, "environments": env_results,
        "allc_validation": sorted(allc_validation, key=lambda item: item["path"]),
        # Recorded so a reader can see where each input actually came from. Not
        # signed: the declared sources are already part of the input signature, and
        # a link's transient state would otherwise churn that signature for nothing.
        "data": data_validation,
        "code_signature": code_signature, "errors": errors, "warnings": warnings,
        # Which host ran this check. Provenance, like `data` above, and for the
        # same reason kept out of the signature below: a signature that changed
        # with the validating host would orphan every recorded full validation
        # and trip the pre-submit "input signature changed after planning" check.
        "host_role": role, "host_role_source": host_role_source(),
        # How the ALLC check was carried out, when it was distributed. Provenance
        # like the two fields above and out of the signature for the same reason:
        # a project validated in one wave instead of four read exactly the same
        # files, and evidence that stopped matching when the queue was busy would
        # be worthless.
        "allc_fanout": fanout_note or None,
    }
    payload["input_signature"] = signature({
        "project": {key: value for key, value in cfg.items() if key not in {"project_root", "config_files"}},
        "samples": active, "rna_inventory": rna_inventory, "allc_inventory": allc_inventory,
        "allc_cell_ids": allc_cell_ids, "annotation_sha256": annotation_hash,
        "code_signature": code_signature, "references": reference_hashes,
        "environments": env_results, "routes": routes,
    })
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--allow-missing-paths", action="store_true")
    parser.add_argument("--mode", choices=("quick", "full"), default="quick")
    parser.add_argument("--workers", type=int, default=max(1, min(8, os.cpu_count() or 1)))
    args = parser.parse_args()
    result = validate(args.project, require_paths=not args.allow_missing_paths,
                      mode=args.mode, workers=args.workers)
    if args.json_out:
        write_json(args.json_out, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "valid" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (WorkflowError, OSError, ValueError) as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        raise SystemExit(2)
