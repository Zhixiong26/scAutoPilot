#!/usr/bin/env python3
"""Dependency-light tests for generation, validation, planning, and scheduling."""

from __future__ import annotations

import gzip
import importlib.util
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# The suite drives local execution end to end, so it declares the host it emulates:
# a single machine with no scheduler to submit to. Without this the same suite would
# refuse to submit on a Slurm login node and pass on a workstation -- one suite, two
# behaviours. Tests that need a different host declare it themselves for one call.
os.environ.setdefault("SCMO_HOST_ROLE", "standalone")

from _common import (LEGACY_RUN_STATE_END, LEGACY_RUN_STATE_START, RUN_KEY_SAFE_RE,
                     RUNLOG_EMPTY, RUNLOG_END, RUNLOG_START, STAGE_CONTEXT_END,
                     STAGE_CONTEXT_START, STAGE_REPORTS, WorkflowError, available_partitions,
                     build_report_text, effective_backend, host_role, host_role_source,
                     load_project, load_samples, load_structured, login_execution_ack,
                     normalize_job_state, parse_walltime_seconds,
                     refresh_run_log, refresh_stage_run_logs, sha256_file, slurm_allocation_id,
                     stage_for_task, submit_host_execution_allowed, write_json,
                     report_run_key, task_is_implemented,
                     validate_recorded_outputs)  # noqa: E402
import bootstrap_environments as environment_bootstrap  # noqa: E402
from bootstrap_environments import bootstrap  # noqa: E402
from init_project import DEFAULT_ANALYSIS, adapt_stage_docs, packaged_notebook  # noqa: E402
from init_project import main as unused_init_main  # noqa: F401,E402
from inspect_resources import choose, enrich_nodes, inspect as inspect_resources, parse_scontrol, parse_sinfo  # noqa: E402
from inspect_run import TERMINAL_BAD, inspect as inspect_run  # noqa: E402
from plan_workflow import make_tasks  # noqa: E402
from submit_workflow import slurm_dependency_argument, slurm_job_state, submit  # noqa: E402
import validate_project as validate_script  # noqa: E402
from validate_project import (allc_cell_id, read_chunk_result, split_allc_chunks, validate,
                              validate_allc_record, wait_for_jobs)  # noqa: E402


# Names that are undefined in the source yet defined at run time: modules get the dunders
# injected by the import system, and a notebook kernel injects the IPython display hooks.
INJECTED_NAMES = frozenset({
    "__file__", "__name__", "__doc__", "__spec__", "__package__", "__builtins__", "__loader__",
    "display", "get_ipython", "In", "Out",
})


def notebook_source(path: Path) -> str:
    """The notebook's code cells as one Python source string, minus its IPython magics.

    Magics are not Python: `%` and `!` lines would be syntax errors, and a `%%` cell magic makes
    the whole cell another language, so those cells are skipped. Scope is preserved because every
    cell lands at the module level of the joined source, which is how a kernel runs them.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    blocks = []
    for cell in payload.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        source = "".join(cell.get("source") or [])
        if source.lstrip().startswith("%%"):
            continue
        blocks.append("\n".join(line for line in source.splitlines()
                                if not line.lstrip().startswith(("%", "!", "?"))))
    return "\n\n".join(blocks)


def undefined_names(source: str, filename: str) -> list:
    """Referenced names that no scope in the module and no builtin ever binds."""
    import builtins
    import symtable

    if not source.strip():
        return []

    def symbols(table):
        return [(name, table.lookup(name)) for name in table.get_identifiers()]

    table = symtable.symtable(source, filename, "exec")
    bound = {name for name, symbol in symbols(table)
             if symbol.is_assigned() or symbol.is_imported() or symbol.is_namespace()}
    known = bound | set(dir(builtins)) | INJECTED_NAMES
    found = []

    def walk(scope):
        for name, symbol in symbols(scope):
            if (symbol.is_referenced() and symbol.is_global() and not symbol.is_parameter()
                    and not symbol.is_assigned() and name not in known):
                found.append("%s: %s" % (scope.get_name() or "module", name))
        for child in scope.get_children():
            walk(child)

    walk(table)
    return sorted(set(found))


class SkillTests(unittest.TestCase):
    def build_inputs(self, root: Path, mode: str = "paired", bad_checksum: bool = False,
                     mutate=None) -> Path:
        data = root / "input"
        rna = data / "rna"
        allc = data / "allc"
        refs = data / "refs"
        rna.mkdir(parents=True)
        allc.mkdir(parents=True)
        refs.mkdir(parents=True)
        (rna / "barcodes.tsv").write_text("AAAC-1\nAAAG-1\n", encoding="utf-8")
        (rna / "features.tsv").write_text("g1\tGENE1\tGene Expression\ng2\tMT-X\tGene Expression\n", encoding="utf-8")
        (rna / "matrix.mtx").write_text("%%MatrixMarket matrix coordinate integer general\n2 2 2\n1 1 3\n2 2 1\n", encoding="utf-8")
        allc_path = allc / "AAAC-1.allc.tsv.gz"
        with gzip.open(str(allc_path), "wt") as handle:
            handle.write("chr1\t1\t+\tCGN\t1\t2\t1\n")
        Path(str(allc_path) + ".tbi").touch()
        chrom = refs / "genome.chrom.sizes"
        chrom.write_text("chr1\t1000\n", encoding="utf-8")
        blacklist = refs / "blacklist.bed"
        blacklist.write_text("chr1\t100\t200\n", encoding="utf-8")
        annotation = data / "annotation.tsv"
        annotation.write_text("cell_id\tcell_type\nS1_AAAC-1\tTypeA\n", encoding="utf-8")
        import hashlib
        digest = hashlib.sha256(chrom.read_bytes()).hexdigest()
        sample = {
            "sample_id": "S1", "condition": "control", "batch": "B1", "include": 1,
            "rna_path": str(rna) if mode in {"rna", "paired"} else "",
            "rna_format": "10x_mtx" if mode in {"rna", "paired"} else "",
            "allc_root": str(allc) if mode in {"allc", "paired"} else "",
            "allc_glob": "*.allc.tsv.gz", "cell_id_prefix": "S1",
        }
        intake = {
            "schema_version": 1, "project_id": "fixture", "organism": "human",
            "references": {
                "genome_id": "fixture-build", "chrom_sizes": str(chrom),
                "chrom_sizes_sha256": "bad" if bad_checksum else digest,
                "blacklist": str(blacklist),
            },
            "samples": [sample],
            "annotation": {"path": str(annotation), "cell_id_column": "cell_id", "cell_type_column": "cell_type"},
            "environments": [{
                "stage": stage, "python": sys.executable,
                "executable": sys.executable, "version_command": sys.executable + " --version", "required": 1,
            } for stage in ("orchestrator", "scanpy_allcools", "methscan", "methylvi")],
            "analysis": {"task_commands": {"scanpy": [
                "/bin/sh", "-c",
                "touch {task_dir}/artifact; printf '%s\\n' '{{\"artifacts\":[\"{task_dir}/artifact\"]}}' > {task_dir}/task_outputs.json",
            ]}},
            "scheduler": {"backend": "local", "local": {"max_threads": 64, "max_memory": "256G"}},
        }
        intake_path = root / "intake.yaml"
        if mutate is not None:
            # One hook instead of a parameter per block: a test that needs a
            # different references or data block edits the dict it was handed
            # rather than duplicating the whole fixture.
            mutate(intake)
        intake_path.write_text(json.dumps(intake), encoding="utf-8")
        return intake_path

    def generate(self, root: Path, mode: str = "paired", bad_checksum: bool = False,
                 mutate=None, init_args: tuple = (), env=None) -> Path:
        intake = self.build_inputs(root, mode, bad_checksum, mutate)
        project = root / "project"
        # Generation runs in a subprocess, which cannot be patched from here, so a
        # test that needs a different generating host declares it through the
        # environment instead.
        child_env = dict(os.environ)
        child_env.update(env or {})
        subprocess.check_call([sys.executable, str(ROOT / "scripts" / "init_project.py"),
                               "--intake", str(intake), "--output", str(project), *init_args],
                              env=child_env)
        return project

    def test_modes_and_route_detection(self):
        expected = {
            "rna": (True, False), "allc": (False, True), "paired": (True, True),
        }
        for mode, flags in expected.items():
            with tempfile.TemporaryDirectory() as temp:
                project = self.generate(Path(temp), mode)
                result = validate(project)
                self.assertEqual(result["status"], "valid")
                self.assertEqual(result["routes"]["scanpy"], flags[0])
                self.assertEqual(result["routes"]["methscan_vmr"], flags[1])
                self.assertEqual(load_project(project)["schema_version"], 2)

    def test_allc_cell_ids_support_common_and_custom_names(self):
        row = {"sample_id": "lung-S11-m1", "cell_id_prefix": "lung-S11-m1",
               "allc_cell_id_regex": "", "allc_cell_id_replacement": ""}
        self.assertEqual(allc_cell_id(Path("AAACCTGAGAAACCAT-1.allc.tsv.gz"), row),
                         "lung-S11-m1_AAACCTGAGAAACCAT-1")
        row.update({"allc_cell_id_regex": r"allc_(?P<cell_id>.+)\.tsv\.gz$"})
        self.assertEqual(allc_cell_id(Path("allc_lung-S11-m1_sc10.tsv.gz"), row),
                         "lung-S11-m1_sc10")

    def test_full_validation_checks_every_allc_and_approved_dmr_labels(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = self.generate(root, "paired")
            allc_root = root / "input/allc"
            second = allc_root / "AAAG-1.allc.tsv.gz"
            with gzip.open(str(second), "wt") as handle:
                handle.write("chr1\t2\t+\tCGN\t0\t2\t1\n")
            Path(str(second) + ".tbi").touch()
            annotation = root / "input/annotation.tsv"
            annotation.write_text("cell_id\tcell_type\nS1_AAAC-1\tTypeA\nS1_AAAG-1\tTypeB\n")
            project_cfg = json.loads((project / "config/project.yaml").read_text())
            project_cfg["annotation"] = {"table": str(annotation), "profile": None,
                                             "review_status": "approved", "cell_id_column": "cell_id",
                                             "cell_type_column": "cell_type"}
            (project / "config/project.yaml").write_text(json.dumps(project_cfg))
            analysis = json.loads((project / "config/analysis.yaml").read_text())
            analysis["analysis"]["methscan"]["min_cells"] = 1
            (project / "config/analysis.yaml").write_text(json.dumps(analysis))
            result = validate(project, mode="full", workers=2)
            self.assertEqual(result["status"], "valid")
            self.assertTrue(result["routes"]["methscan_dmr"])
            self.assertEqual(len(result["allc_validation"]), 2)
            annotation.write_text("cell_id\tcell_type\nS1_AAAC-1\tTypeA\nS1_AAAG-1\tUnassigned\n")
            self.assertFalse(validate(project)["routes"]["methscan_dmr"])

    # --- ALLC full-validation fan-out ---------------------------------------
    #
    # A full ALLC validation reads every file end to end, so it is split into
    # chunks and submitted. These tests run the real chunk worker with the argv
    # the fan-out built and replace only `sbatch` and the queue poll: a fake
    # that produced chunk results in-process would agree with a broken merge,
    # which is the one thing the merge tests exist to catch.

    @staticmethod
    def slurm_scheduler(intake: dict) -> None:
        intake["scheduler"] = {
            "backend": "slurm", "partitions": ["cpu"],
            "validation_parallel": 2, "validation_processes_per_task": 2,
            "profiles": {"validation": {"target": {"cpus": 2, "memory": "8G", "time": "00:10:00"}}},
        }

    def allc_project(self, root: Path, count: int) -> Path:
        project = self.generate(root, "paired", mutate=self.slurm_scheduler)
        allc_root = root / "input" / "allc"
        for index in range(count):
            extra = allc_root / ("cell%03d.allc.tsv.gz" % index)
            with gzip.open(str(extra), "wt") as handle:
                handle.write("chr1\t%d\t+\tCGN\t1\t2\t1\n" % (index + 2))
            Path(str(extra) + ".tbi").touch()
        return project

    def run_fanout(self, project: Path, skip_chunks=(), state: str = "COMPLETED",
                   workers: int = 1, min_files_per_chunk: int = 1) -> tuple:
        """Validate with the fan-out enabled, minus the scheduler.

        Declares a compute host for the call, because the suite runs as a
        standalone machine where submitting would be wrong. `skip_chunks` names
        chunks whose job is reported complete without the worker ever running,
        which is what a job killed after Slurm accepted it looks like.

        The thresholds that decide whether and how finely to split are lowered
        by default so a fixture of a few files still fans out; a caller that
        wants the real per-chunk minimum passes it.
        """
        wrapper = str(project / "Scripts" / "Common" / "run_task.sbatch")
        submitted = []
        real_check_output = subprocess.check_output

        def fake_check_output(command, *args, **kwargs):
            if command[0] != "sbatch":
                return real_check_output(command, *args, **kwargs)
            submitted.append(list(command))
            if int(command[command.index("--job-name") + 1].rsplit("_", 1)[1]) in skip_chunks:
                return b"999\n"
            subprocess.check_call(command[command.index(wrapper) + 1:], stdout=subprocess.DEVNULL)
            return ("9%02d\n" % len(submitted)).encode()

        with mock.patch.dict(os.environ, {"SCMO_HOST_ROLE": "compute"}), \
                mock.patch.object(validate_script, "FANOUT_MIN_FILES", 1), \
                mock.patch.object(validate_script, "FANOUT_MIN_FILES_PER_CHUNK", min_files_per_chunk), \
                mock.patch("subprocess.check_output", fake_check_output), \
                mock.patch.object(validate_script, "slurm_job_state", lambda job_id: state):
            return validate(project, mode="full", workers=workers), submitted

    def test_chunk_split_balances_bytes_and_is_deterministic(self):
        entries = [{"path": "/allc/big.allc.tsv.gz", "size": 90}] + [
            {"path": "/allc/small%d.allc.tsv.gz" % index, "size": 10} for index in range(5)]
        by_path = {item["path"]: item["size"] for item in entries}
        groups = split_allc_chunks(entries, 2)
        self.assertEqual(groups, split_allc_chunks(entries, 2))
        self.assertEqual(sorted(path for group in groups for path in group), sorted(by_path))
        loads = [sum(by_path[path] for path in group) for group in groups]
        # 90 of the 140 bytes are one file, so no split can do better than a
        # heaviest group of 90. Splitting on file count would build a 110-byte
        # group and make the whole fan-out wait on it.
        self.assertEqual(max(loads), 90)

    def test_fanout_merges_chunks_identically_to_the_serial_path(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.allc_project(Path(temp), 5)
            serial = validate(project, mode="full", workers=1)
            fanned, submitted = self.run_fanout(project)
            self.assertGreaterEqual(len(submitted), 2)
            self.assertEqual(fanned["status"], "valid")
            self.assertEqual(fanned["input_signature"], serial["input_signature"])
            self.assertEqual(fanned["allc_fanout"]["chunks"], len(submitted))
            self.assertEqual(fanned["allc_fanout"]["parallel"], 2)
            self.assertEqual(fanned["counts"]["allc_cells"], 6)
            self.assertEqual(len(fanned["allc_validation"]), 6)
            # The parallel result has to be the serial result, or a recorded
            # validation stops telling anyone what was actually read.
            self.assertEqual(json.dumps(fanned["allc_validation"], sort_keys=True),
                             json.dumps(serial["allc_validation"], sort_keys=True))

    def test_a_small_inventory_is_not_split_into_one_file_chunks(self):
        """A chunk is a job, so a chunk holding one file spends longer starting up
        than reading. Six files are one chunk, not six."""
        with tempfile.TemporaryDirectory() as temp:
            project = self.allc_project(Path(temp), 5)
            result, submitted = self.run_fanout(project, min_files_per_chunk=8)
            self.assertEqual(len(submitted), 1)
            self.assertEqual(result["allc_fanout"]["chunks"], 1)
            self.assertEqual(result["status"], "valid")
            self.assertEqual(result["counts"]["allc_cells"], 6)
            self.assertEqual(len(result["allc_validation"]), 6)

    def test_a_missing_chunk_fails_the_validation_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.allc_project(Path(temp), 5)
            result, submitted = self.run_fanout(project, skip_chunks={0})
            self.assertTrue(submitted)
            # The job was accepted and reported complete, so only the merge can
            # notice that its files were never read -- and it must.
            self.assertEqual(result["status"], "invalid")
            self.assertIn("chunk_000", " ".join(result["errors"]))
            self.assertEqual(len(result["allc_validation"]), 5)

    def test_a_chunk_that_accounts_for_fewer_files_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "chunk_000.manifest.json"
            out = root / "chunk_000.out.json"
            write_json(manifest, {"schema_version": 1, "chunk": 0, "paths": ["/a", "/b"]})
            write_json(out, {"schema_version": 1, "manifest_sha256": sha256_file(manifest),
                             "paths": ["/a", "/b"],
                             "outcomes": [{"path": "/a", "records_checked": 1, "mode": "full", "error": None}]})
            records, errors = read_chunk_result(out, manifest, ["/a", "/b"])
            self.assertEqual(records, [])
            self.assertIn("chunk_000 accounted for 1 of its 2 files", " ".join(errors))
            write_json(out, {"schema_version": 1, "manifest_sha256": "0" * 64,
                             "paths": ["/a", "/b"],
                             "outcomes": [{"path": "/a"}, {"path": "/b"}]})
            records, errors = read_chunk_result(out, manifest, ["/a", "/b"])
            self.assertEqual(records, [])
            self.assertIn("different manifest", " ".join(errors))

    def test_chunk_results_are_reused_while_their_manifest_still_matches(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.allc_project(Path(temp), 5)
            first, submitted_first = self.run_fanout(project)
            second, submitted_second = self.run_fanout(project)
            self.assertTrue(submitted_first)
            # A full read of a real project runs for hours, so a rerun after a
            # failure elsewhere must not resubmit a chunk that already finished.
            self.assertEqual(submitted_second, [])
            self.assertEqual(second["allc_fanout"]["reused_chunks"],
                             second["allc_fanout"]["chunks"])
            self.assertEqual(json.dumps(second["allc_validation"], sort_keys=True),
                             json.dumps(first["allc_validation"], sort_keys=True))

    def test_fanout_never_submits_from_a_host_with_no_controller(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.allc_project(Path(temp), 5)
            real_check_output = subprocess.check_output

            def refuse(command, *args, **kwargs):
                if command[0] == "sbatch":
                    raise AssertionError("a standalone host has nothing to submit to")
                return real_check_output(command, *args, **kwargs)

            # No host-role override here: this is the suite's own standalone host,
            # which is the case the fan-out has to leave alone. The project still
            # declares the Slurm backend, so only the role check can be what stops
            # it -- and the files still have to be read, in place.
            with mock.patch.object(validate_script, "FANOUT_MIN_FILES", 1), \
                    mock.patch("subprocess.check_output", refuse):
                result = validate(project, mode="full", workers=2)
            self.assertIsNone(result["allc_fanout"])
            self.assertEqual(result["status"], "valid")
            self.assertEqual(len(result["allc_validation"]), 6)

    def test_skip_full_validation_records_the_skip_and_writes_no_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna")
            plan_command = [sys.executable, str(ROOT / "scripts/plan_workflow.py"),
                            "--project", str(project), "--routes", "auto", "--run-id", "unit"]
            subprocess.check_call(plan_command)
            finished = subprocess.run(
                [sys.executable, str(ROOT / "scripts/submit_workflow.py"),
                 "--project", str(project), "--run-id", "unit", "--skip-full-validation"],
                capture_output=True, text=True)
            self.assertEqual(finished.returncode, 0, finished.stderr)
            plan = json.loads((project / ".workflow/runs/unit/plan.json").read_text(encoding="utf-8"))
            evidence = project / ".workflow/validations" / (plan["input_signature"] + ".full.json")
            # A skip leaves no evidence: a file saying the inputs were read would
            # outlive the run that did not read them, and would be reused by the
            # next submission as if this one had checked them.
            self.assertFalse(evidence.exists())
            self.assertTrue(plan["full_validation_skipped"])
            records = json.loads((project / ".workflow/runs/unit/submissions.json").read_text(encoding="utf-8"))
            self.assertTrue(records)
            self.assertTrue(all(item["full_validation_skipped"] for item in records))
            self.assertIn("skipping the full input validation", finished.stderr)
            # The skip is a fact about one submission, not a property of the
            # project: the next run without the flag validates and records it.
            subprocess.check_call(plan_command[:-1] + ["later"])
            subprocess.check_call([sys.executable, str(ROOT / "scripts/submit_workflow.py"),
                                   "--project", str(project), "--run-id", "later"])
            later = json.loads((project / ".workflow/runs/later/plan.json").read_text(encoding="utf-8"))
            self.assertFalse(later["full_validation_skipped"])
            self.assertTrue(evidence.is_file())
            self.assertEqual(json.loads(evidence.read_text(encoding="utf-8"))["status"], "valid")

    def test_inspection_reports_what_the_full_validation_actually_read(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna")
            subprocess.check_call([sys.executable, str(ROOT / "scripts/plan_workflow.py"),
                                   "--project", str(project), "--routes", "auto", "--run-id", "planned"])
            summary = inspect_run(project, "planned")
            self.assertEqual(summary["full_validation"]["evidence"], "absent")
            self.assertFalse(summary["full_validation"]["skipped"])
            subprocess.check_call([sys.executable, str(ROOT / "scripts/plan_workflow.py"),
                                   "--project", str(project), "--routes", "auto", "--run-id", "unit"])
            subprocess.check_call([sys.executable, str(ROOT / "scripts/submit_workflow.py"),
                                   "--project", str(project), "--run-id", "unit"])
            summary = inspect_run(project, "unit")
            # An rna-only project reads no ALLC file, so a valid full validation
            # here covers nothing methylation-related. That has to be visible, or
            # "the inputs were validated" reads the same on any project.
            self.assertEqual(summary["full_validation"]["evidence"], "valid")
            self.assertEqual(summary["full_validation"]["allc_cells"], 0)
            self.assertFalse(summary["full_validation"]["skipped"])

    def test_waiting_for_jobs_does_not_return_on_a_queued_state(self):
        # A job observed as PENDING has been observed, not finished. Returning
        # there merges a fan-out whose chunks are still in the queue, so it is
        # the difference between a validation and a race.
        polls = []

        def observed(job_id):
            polls.append(job_id)
            return ["PENDING", "RUNNING", "COMPLETED"][len(polls) - 1]

        with mock.patch.object(validate_script, "slurm_job_state", observed), \
                mock.patch.object(validate_script, "JOB_POLL_SECONDS", 0):
            states = wait_for_jobs(["1"], timeout=60)
        self.assertEqual(states, {"1": "COMPLETED"})
        # Three reads: two queue states that must not end the wait, and the one
        # that does. Reading a state is not the same as the job having finished.
        self.assertEqual(len(polls), 3)

    def test_a_cancelled_job_ends_the_wait(self):
        # The literal strings the cluster returns: sacct decorates a cancelled
        # state with the account that cancelled it, and a queue column truncates
        # with a trailing +. Left undecorated, neither equals CANCELLED, so a
        # killed job reads as one still running and the wait runs to its
        # deadline for a worker that will never write anything.
        self.assertEqual(normalize_job_state("CANCELLED by 1111"), "CANCELLED")
        self.assertEqual(normalize_job_state("CANCELLED+"), "CANCELLED")
        self.assertEqual(normalize_job_state("completed"), "COMPLETED")

        def fake_check_output(command, *args, **kwargs):
            # A job that was cancelled has left the queue; only accounting has it.
            if command[0] == "squeue":
                return b""
            return b"CANCELLED by 1111\n"

        with mock.patch("subprocess.check_output", fake_check_output):
            self.assertEqual(validate_script.slurm_job_state("1111"), "CANCELLED")
            with mock.patch.object(validate_script, "JOB_POLL_SECONDS", 0):
                self.assertEqual(wait_for_jobs(["1111"], timeout=0), {"1111": "CANCELLED"})

    def test_waiting_for_jobs_gives_up_on_a_job_no_queue_knows(self):
        with mock.patch.object(validate_script, "slurm_job_state", lambda job_id: ""), \
                mock.patch.object(validate_script, "LOST_JOB_GRACE_SECONDS", 0), \
                mock.patch.object(validate_script, "JOB_POLL_SECONDS", 0):
            self.assertEqual(wait_for_jobs(["1"], timeout=60), {"1": "MISSING"})

    def test_waiting_for_jobs_reports_a_deadline_as_a_timeout(self):
        with mock.patch.object(validate_script, "slurm_job_state", lambda job_id: "RUNNING"), \
                mock.patch.object(validate_script, "JOB_POLL_SECONDS", 0):
            self.assertEqual(wait_for_jobs(["1"], timeout=0), {"1": "TIMEOUT"})

    def test_validation_reads_inputs_in_processes_not_threads(self):
        for relative in ("scripts/validate_project.py",
                         "assets/project-template/Scripts/Common/validate_allc_chunk.py"):
            source = (ROOT / relative).read_text(encoding="utf-8")
            # The per-line check holds the GIL for its whole loop: a thread pool
            # measured 2.3x slower than reading the files one at a time, so this
            # is a correctness-of-design assertion, not a style preference.
            self.assertNotIn("ThreadPoolExecutor", source)
            self.assertIn("ProcessPoolExecutor", source)

    def test_job_time_limits_parse_the_way_slurm_reads_them(self):
        self.assertEqual(parse_walltime_seconds("30"), 30 * 60)
        self.assertEqual(parse_walltime_seconds("10:30"), 10 * 60 + 30)
        self.assertEqual(parse_walltime_seconds("04:00:00"), 4 * 3600)
        self.assertEqual(parse_walltime_seconds("1-00:00:00"), 86400)
        self.assertEqual(parse_walltime_seconds("2-03:04:05"), 2 * 86400 + 3 * 3600 + 4 * 60 + 5)
        for bad in ("", "4h", "1:2:3:4", "tomorrow"):
            with self.assertRaises(WorkflowError):
                parse_walltime_seconds(bad)

    def test_bad_checksum_and_duplicate_sample(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "paired", bad_checksum=True)
            self.assertEqual(validate(project)["status"], "invalid")
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna")
            samples = project / "config" / "samples.tsv"
            lines = samples.read_text().splitlines()
            samples.write_text("\n".join(lines + [lines[1]]) + "\n")
            with self.assertRaises(WorkflowError):
                validate(project)

    def test_duplicate_cell_id_and_missing_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = self.generate(root, "paired")
            second = root / "input" / "allc-second"
            second.mkdir()
            source = root / "input" / "allc" / "AAAC-1.allc.tsv.gz"
            shutil.copy2(str(source), str(second / source.name))
            (second / (source.name + ".tbi")).touch()
            samples = project / "config" / "samples.tsv"
            with samples.open("a", encoding="utf-8") as handle:
                handle.write("S2\tcontrol\tB2\t1\t\t\t%s\t*.allc.tsv.gz\tS1\n" % second)
            result = validate(project)
            self.assertEqual(result["status"], "invalid")
            self.assertIn("ALLC-derived cell IDs", " ".join(result["errors"]))
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna")
            environments = project / "config" / "environments.tsv"
            environments.write_text(
                "stage\tpython\texecutable\tversion_command\trequired\n"
                "orchestrator\t/missing/python\t/missing/python\t\t1\n",
                encoding="utf-8",
            )
            result = validate(project)
            self.assertEqual(result["status"], "invalid")
            self.assertIn("required executable is absent", " ".join(result["errors"]))

    def test_environment_bootstrap_plans_isolated_prefixes(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "allc")
            self.assertTrue((project / "tools/bootstrap_environments.py").is_file())
            self.assertTrue((project / "environment-specs/analysis-core.yaml").is_file())
            environments = project / "config" / "environments.tsv"
            environments.write_text(
                "stage\tpython\texecutable\tversion_command\trequired\n",
                encoding="utf-8",
            )
            result = bootstrap(project, execute=False, discover=False)
            self.assertEqual(result["status"], "planned")
            self.assertEqual(result["required_profiles"], ["analysis_core", "methscan", "methylvi"])
            self.assertTrue(all(item["action"] == "create" for item in result["actions"]))
            self.assertTrue(all("/.environments/" in item["prefix"] for item in result["actions"]))

    def test_allcools_environment_declares_and_probes_late_runtime_dependencies(self):
        spec = (ROOT / "assets/project-template/environment-specs/analysis-core.yaml").read_text(
            encoding="utf-8"
        )
        runner = (ROOT / "assets/project-template/Scripts/Methylvi/allcools/run.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("zarr<3", spec)
        self.assertIn("dask-core<2025", spec)
        self.assertIn("openTSNE==1.0.2", spec)
        self.assertIn("imbalanced-learn==0.12.4", spec)
        probe = "".join(environment_bootstrap.PROFILES["analysis_core"]["check"])
        self.assertIn("dask", probe)
        self.assertIn("openTSNE", probe)
        self.assertIn("imblearn", probe)
        self.assertIn("zarr", probe)
        self.assertIn("dask", runner)
        self.assertIn("ALLCools.clustering", runner)
        self.assertIn("openTSNE", runner)
        self.assertIn("imblearn", runner)
        self.assertIn("zarr", runner)

    def test_allcools_runtime_compatibility_guards_are_packaged(self):
        cluster = (
            ROOT
            / "assets/project-template/Scripts/Methylvi/allcools/02_cluster_allcools.py"
        ).read_text(encoding="utf-8")
        compat = (
            ROOT
            / "assets/project-template/Scripts/Methylvi/allcools/allcools_compat.py"
        ).read_text(encoding="utf-8")
        self.assertIn("normalize_feature_coordinate_dims", cluster)
        self.assertIn("ensure_sparse_compatible_score_dtype", cluster)
        self.assertIn("_consensus_module._leiden_runner = leiden_runner_cells_by_runs", cluster)
        self.assertIn("return pd.DataFrame(columns)", compat)

    def test_vmr_route_treats_complete_as_a_marker_not_a_data_file(self):
        runner = (ROOT / "assets/project-template/Scripts/Methylvi/vmr/run.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('require_marker "$VMR_METHSCAN_RUN_DIR/smooth.COMPLETE"', runner)
        self.assertNotIn('require_file "$VMR_METHSCAN_RUN_DIR/smooth.COMPLETE"', runner)

    def test_vmr_parent_worker_receives_the_methylation_context(self):
        builder = (
            ROOT / "assets/project-template/Scripts/Methylvi/vmr/02_build_vmr_methylvi_input.py"
        ).read_text(encoding="utf-8")
        self.assertIn("init_worker(lookup, len(regions), mc_prefix)", builder)
        self.assertNotIn("init_worker(lookup, len(regions))\n", builder)

    def test_task_adapter_exports_complete_methylvi_training_environment(self):
        adapter = (
            ROOT / "assets/project-template/Scripts/Common/task_adapter.py"
        ).read_text(encoding="utf-8")
        for variable in (
            "SCMO_BATCH_KEY", "SCMO_CELLTYPE_KEY", "SCMO_SUPERVISED_TARGET_KEY",
            "SCMO_SUPERVISED_TARGET_WEIGHTS", "SCMO_SUPERVISED_NEIGHBORS",
            "SCMO_SUPERVISED_MIN_DIST",
        ):
            self.assertIn('"%s"' % variable, adapter)

    def test_environment_bootstrap_execute_updates_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "allc")
            environments = project / "config" / "environments.tsv"
            environments.write_text(
                "stage\tpython\texecutable\tversion_command\trequired\n",
                encoding="utf-8",
            )

            def verified(prefix, profile, timeout=180):
                return {
                    "profile": profile, "prefix": str(prefix), "valid": True,
                    "version": profile + " test", "command": [str(prefix / "bin/python")],
                }

            with mock.patch.object(environment_bootstrap, "find_manager", return_value="/bin/true"), \
                    mock.patch.object(environment_bootstrap, "check_prefix", side_effect=verified), \
                    mock.patch.object(environment_bootstrap.subprocess, "check_call") as create:
                result = bootstrap(project, execute=True, discover=False)
            self.assertEqual(result["status"], "complete")
            self.assertEqual(create.call_count, 3)
            rows = environments.read_text(encoding="utf-8")
            for stage in ("orchestrator", "scanpy_allcools", "methscan", "methylvi"):
                self.assertIn(stage, rows)
            self.assertTrue((project / ".workflow/environment-bootstrap/result.json").is_file())
            self.assertTrue((project / "Scripts/Environment/Report.md").is_file())

    def test_plan_dry_run_and_local_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna")
            subprocess.check_call([sys.executable, str(ROOT / "scripts" / "plan_workflow.py"), "--project", str(project), "--routes", "auto", "--run-id", "unit"])
            subprocess.check_call([sys.executable, str(ROOT / "scripts" / "submit_workflow.py"), "--project", str(project), "--run-id", "unit"])
            code = subprocess.call([sys.executable, str(ROOT / "scripts" / "inspect_run.py"), "--project", str(project), "--run-id", "unit"])
            self.assertEqual(code, 0)
            self.assertTrue((project / ".workflow/runs/unit/workflow.COMPLETE").is_file())
            artifact = project / ".workflow/runs/unit/tasks/scanpy/artifact"
            artifact.unlink()
            self.assertNotEqual(inspect_run(project, "unit")["status"], "complete")
            subprocess.check_call([sys.executable, str(ROOT / "scripts" / "submit_workflow.py"), "--project", str(project), "--run-id", "unit"])
            resumed = json.loads((project / ".workflow/runs/unit/submissions.json").read_text())
            self.assertTrue((project / ".workflow/runs/unit/tasks/scanpy/artifact").is_file())
            self.assertTrue(any(item.get("resumed") for item in resumed))

    def test_inspect_never_completes_a_partial_plan_or_marker_only_task(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            run_dir = project / ".workflow/runs/partial"
            run_dir.mkdir(parents=True)
            tasks = [{"id": "task_%d" % index, "parameters": {}} for index in range(10)]
            (run_dir / "plan.json").write_text(json.dumps({
                "input_signature": "input", "code_signature": "code", "tasks": tasks,
            }))
            (run_dir / "submissions.json").write_text(json.dumps([{
                "task": "task_0", "job_id": "local_task_0", "status": "complete",
            }]))
            marker_dir = run_dir / "tasks/task_0"
            marker_dir.mkdir(parents=True)
            (marker_dir / "task.COMPLETE").touch()
            result = inspect_run(project, "partial")
            self.assertNotEqual(result["status"], "complete")
            self.assertEqual(len(result["tasks"]), 10)
            self.assertFalse((run_dir / "workflow.COMPLETE").exists())

    def test_explicit_downstream_routes_have_closed_dependencies(self):
        analysis = {"methscan": {"vmr_thresholds": [0.02]}, "methylvi": {"feature_targets": [10000]}}
        routes = {
            "scanpy": False, "methscan_vmr": False, "methscan_dmr": False,
            "allcools": False, "methylvi_allcools": True,
            "methylvi_vmr": False, "methylvi_vmr_dmr": False,
        }
        tasks = make_tasks(routes, analysis)
        identifiers = {item["id"] for item in tasks}
        self.assertIn("allcools_features", identifiers)
        self.assertIn("methylvi_allcools_10000", identifiers)
        self.assertTrue(all(set(item["dependencies"]).issubset(identifiers) for item in tasks))
        for route in routes:
            selected = {name: name == route for name in routes}
            planned = make_tasks(selected, analysis)
            known = {item["id"] for item in planned}
            self.assertTrue(known)
            self.assertTrue(all(set(item["dependencies"]).issubset(known) for item in planned))
            by_id = {item["id"]: item for item in planned}
            if "allcools_features" in by_id:
                self.assertIn("methscan_filter", by_id)
                self.assertEqual(by_id["allcools_features"]["dependencies"], ["methscan_filter"])
                if route == "allcools":
                    self.assertNotIn("methscan_smooth", by_id)
                    self.assertFalse(any(name.startswith("methscan_vmr_") for name in by_id))
        names = list(routes)
        for size in range(1, len(names) + 1):
            for selected_names in itertools.combinations(names, size):
                selected = {name: name in selected_names for name in names}
                planned = make_tasks(selected, analysis)
                by_id = {item["id"]: item for item in planned}
                self.assertTrue(all(task_is_implemented(item["id"], {}) for item in planned))
                if "allcools_features" in by_id:
                    self.assertIn("methscan_filter", by_id)
                    self.assertIn("methscan_filter", by_id["allcools_features"]["dependencies"])

    def test_scanpy_subset_does_not_require_unused_methylation_environments(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "paired")
            environments = project / "config/environments.tsv"
            lines = environments.read_text(encoding="utf-8").splitlines()
            kept = [lines[0]] + [line for line in lines[1:]
                                 if line.split("\t", 1)[0] in {"orchestrator", "scanpy_allcools"}]
            environments.write_text("\n".join(kept) + "\n", encoding="utf-8")
            project_cfg_path = project / "config/project.yaml"
            project_cfg = json.loads(project_cfg_path.read_text())
            project_cfg["references"] = {}
            project_cfg_path.write_text(json.dumps(project_cfg))
            for index in (Path(temp) / "input/allc").glob("*.tbi"):
                index.unlink()
            subprocess.check_call([
                sys.executable, str(ROOT / "scripts/plan_workflow.py"), "--project", str(project),
                "--routes", "scanpy", "--run-id", "scanpy-only",
            ])
            plan = json.loads((project / ".workflow/runs/scanpy-only/plan.json").read_text())
            self.assertEqual([item["id"] for item in plan["tasks"]], ["scanpy", "workflow_summary"])

    def test_methscan_vmr_subset_does_not_require_methylvi_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "allc")
            environments = project / "config/environments.tsv"
            lines = environments.read_text(encoding="utf-8").splitlines()
            environments.write_text("\n".join(
                [lines[0]] + [line for line in lines[1:] if line.split("\t", 1)[0] != "methylvi"]
            ) + "\n", encoding="utf-8")
            subprocess.check_call([
                sys.executable, str(ROOT / "scripts/plan_workflow.py"), "--project", str(project),
                "--routes", "methscan_vmr", "--run-id", "vmr-only",
            ])
            plan = json.loads((project / ".workflow/runs/vmr-only/plan.json").read_text())
            self.assertIn("methscan_filter", {item["id"] for item in plan["tasks"]})
            required = {stage for item in plan["tasks"] for stage in item["required_environments"]}
            self.assertNotIn("methylvi", required)

    def test_invalid_empty_feature_lists_are_configuration_errors(self):
        with self.assertRaisesRegex(WorkflowError, "vmr_thresholds must be a non-empty list"):
            make_tasks({"methylvi_vmr_dmr": True}, {
                "methscan": {"vmr_thresholds": []}, "methylvi": {"feature_targets": [10000]},
            })
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "paired")
            analysis_path = project / "config/analysis.yaml"
            analysis = json.loads(analysis_path.read_text())
            analysis["analysis"]["methscan"]["vmr_thresholds"] = []
            analysis["analysis"]["methylvi"]["feature_targets"] = []
            analysis_path.write_text(json.dumps(analysis))
            result = validate(project)
            self.assertEqual(result["status"], "invalid")
            self.assertIn("vmr_thresholds must be a non-empty list", " ".join(result["errors"]))
            self.assertIn("feature_targets must be a non-empty list", " ".join(result["errors"]))

    def test_short_scanpy_palette_is_rejected_before_submission(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna")
            analysis_path = project / "config/analysis.yaml"
            analysis = json.loads(analysis_path.read_text())
            analysis["analysis"]["scanpy"]["sample_palette"] = []
            analysis_path.write_text(json.dumps(analysis))
            result = validate(project, selected_routes={"scanpy"})
            self.assertEqual(result["status"], "invalid")
            self.assertIn("sample_palette", " ".join(result["errors"]))

    def test_task_registry_and_output_evidence_fail_closed(self):
        self.assertTrue(task_is_implemented("methylvi_vmr_0.02_10000", {}))
        self.assertTrue(task_is_implemented("future_task", {"future_*": ["/bin/true"]}))
        self.assertFalse(task_is_implemented("future_task", {}))
        self.assertFalse(validate_recorded_outputs([])[0])
        with tempfile.TemporaryDirectory() as temp:
            evidence = Path(temp) / "task_outputs.json"
            evidence.write_text('{"artifacts": []}\n')
            self.assertFalse(validate_recorded_outputs([evidence])[0])
            evidence.write_text('{"artifacts": ["relative.txt"]}\n')
            self.assertFalse(validate_recorded_outputs([evidence])[0])

    def test_interactive_notebook_is_outside_execution_signature(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna")
            before = validate(project)
            notebook = project / "Scripts/Scanpy/Notebooks/scanpy_workflow.ipynb"
            payload = json.loads(notebook.read_text())
            payload["metadata"]["review_note"] = "does not affect executable workflow"
            notebook.write_text(json.dumps(payload))
            after = validate(project)
            self.assertEqual(before["code_signature"], after["code_signature"])
            self.assertEqual(before["input_signature"], after["input_signature"])

    def test_notebook_source_is_inside_execution_signature(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna")
            before = validate(project)
            notebook = project / "Scripts/Scanpy/Notebooks/scanpy_workflow.ipynb"
            payload = json.loads(notebook.read_text())
            code_cell = next(cell for cell in payload["cells"] if cell.get("cell_type") == "code")
            code_cell["source"] = list(code_cell.get("source", [])) + ["\nEXECUTABLE_CHANGE = True\n"]
            notebook.write_text(json.dumps(payload))
            after = validate(project)
            self.assertNotEqual(before["code_signature"], after["code_signature"])
            self.assertNotEqual(before["input_signature"], after["input_signature"])

    def test_override_records_child_exit_code_before_evidence_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna")
            analysis_path = project / "config/analysis.yaml"
            analysis = json.loads(analysis_path.read_text())
            analysis["analysis"]["task_commands"] = {
                "scanpy": ["/bin/sh", "-c", "echo override-succeeded"],
            }
            analysis_path.write_text(json.dumps(analysis))
            subprocess.check_call([
                sys.executable, str(ROOT / "scripts/plan_workflow.py"), "--project", str(project),
                "--routes", "scanpy", "--run-id", "override",
            ])
            code = subprocess.call([
                sys.executable, str(project / "Scripts/Common/run_task.py"), "--project", str(project),
                "--run-id", "override", "--task", "scanpy",
            ])
            self.assertEqual(code, 1)
            status = json.loads((project / ".workflow/runs/override/tasks/scanpy/task_status.json").read_text())
            self.assertEqual(status["process_return_code"], 0)
            self.assertEqual(status["return_code"], 1)
            self.assertEqual(status["failure_stage"], "output_validation")

    def test_template_copy_excludes_caches(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna")
            self.assertFalse(any(path.name == "__pycache__" for path in project.rglob("__pycache__")))
            self.assertFalse(any(project.rglob("*.pyc")))
            self.assertFalse((project / "Config").exists())

    def test_slurm_wrappers_carry_no_site_hardcoding(self):
        """Standalone wrappers are allowed, but site policy lives in scheduler profiles.

        A wrapper may be run directly for exploration, smoke testing, or recovery, so it
        must resolve resources the same way the managed DAG does. Any static resource or
        absolute site path here would make a generated project node-specific.
        """
        forbidden = (
            "#SBATCH --partition", "#SBATCH --nodelist", "#SBATCH --account",
            "#SBATCH --qos", "#SBATCH --reservation", "#SBATCH --gres",
            "#SBATCH --mem", "#SBATCH --cpus-per-task", "#SBATCH --time",
            "#SBATCH --constraint", "/home/", "/scratch/",
        )
        templates = ROOT / "assets/project-template/Scripts"
        wrappers = sorted(templates.glob("**/*.sbatch"))
        self.assertTrue(wrappers, "the packaged Slurm wrappers disappeared")
        for wrapper in wrappers:
            body = wrapper.read_text()
            for token in forbidden:
                self.assertNotIn(
                    token, body,
                    "%s hardcodes site policy (%r); use a scheduler profile" % (
                        wrapper.relative_to(ROOT), token),
                )

    def test_terminal_slurm_failures_are_not_reported_in_progress(self):
        for state in ("BOOT_FAIL", "DEADLINE", "REVOKED", "SPECIAL_EXIT"):
            self.assertIn(state, TERMINAL_BAD)

    def test_context_and_nonhuman_contigs_are_configuration_driven(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            allc = root / "cell.allc.tsv.gz"
            with gzip.open(str(allc), "wt") as handle:
                handle.write("1\t1\t+\tCHN\t0\t2\t1\n")
            checked = validate_allc_record(allc, context="CHN", full=True)
            self.assertEqual(checked["records_checked"], 1)
            chrom = root / "genome.sizes"
            chrom.write_text("1\t1000\n")
            blacklist = root / "blacklist.bed"
            blacklist.write_text("")
            dmr = root / "dmr.tsv"
            dmr.write_text("1\t10\t20\tx\tx\tx\tx\t0.1\t0.6\tgroup_A\t0.001\tx\n")
            summary = root / "summary.tsv"
            summary.write_text(
                "status\tdmr_file\tcell_type_a\tcell_type_b\tcomparison\n"
                "complete\t%s\tTypeA\tTypeB\tA_vs_B\n" % dmr
            )
            output = root / "out"
            subprocess.check_call([
                sys.executable, str(ROOT / "assets/project-template/Scripts/Methylvi/vmr_dmr/01_prepare_all_unique_pooled_dmrs.py"),
                "--pairwise-summary", str(summary), "--blacklist", str(blacklist),
                "--chrom-sizes", str(chrom), "--output-dir", str(output), "--sort-threads", "1",
            ])
            self.assertTrue((output / "all_unique_hypo_DMRs.merged.bed").is_file())

    def test_slurm_requires_explicit_partition_allow_list(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna")
            scheduler = json.loads((project / "config/scheduler.yaml").read_text())
            scheduler["backend"] = "slurm"
            scheduler["partitions"] = []
            (project / "config/scheduler.yaml").write_text(json.dumps(scheduler))
            result = validate(project)
            self.assertEqual(result["status"], "invalid")
            self.assertIn("partitions", " ".join(result["errors"]))

    # --- where a task may execute ----------------------------------------------

    def test_host_role_classification_is_injectable(self):
        """Every classification is decided from injected facts, never from the test host."""
        with tempfile.TemporaryDirectory() as temp:
            up = Path(temp) / "up.txt"
            up.write_text("Slurmctld(primary) at ctl01 is UP\n", encoding="utf-8")
            down = Path(temp) / "down.txt"
            down.write_text("Slurmctld(primary) at ctl01 is DOWN\n", encoding="utf-8")
            self.assertEqual(host_role(environ={"SLURM_JOB_ID": "41"}), "compute")
            self.assertEqual(host_role(environ={"SLURM_JOBID": "41"}), "compute")
            self.assertEqual(host_role(environ={}, reachable=True), "submit")
            self.assertEqual(host_role(environ={}, reachable=False), "standalone")
            self.assertEqual(host_role(environ={}, scontrol_file=up), "submit")
            # A controller that answers but is DOWN refuses every submission, so a
            # probe that read only the exit status would call this host a submit
            # host and refuse work that has nowhere else to go.
            self.assertEqual(host_role(environ={}, scontrol_file=down), "standalone")
            self.assertEqual(slurm_allocation_id({"SLURM_JOB_ID": "41"}), "41")
            self.assertEqual(slurm_allocation_id({"SLURM_JOB_ID": "  "}), "")
            with self.assertRaises(WorkflowError):
                host_role(environ={"SCMO_HOST_ROLE": "nonsense"})
            self.assertEqual(host_role_source({"SCMO_HOST_ROLE": "submit"}), "declared")
            self.assertEqual(host_role_source({}), "observed")

    def test_available_partitions_reads_sinfo_and_drops_the_default_star(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Path(temp) / "sinfo.txt"
            fixture.write_text("cpu*\nfat\ncpu\n\n", encoding="utf-8")
            self.assertEqual(available_partitions(fixture), ["cpu", "fat"])

    def test_effective_backend_promotes_local_on_a_submit_host(self):
        scheduler = {"backend": "local"}
        self.assertEqual(effective_backend(scheduler, "r1", environ={"SCMO_HOST_ROLE": "standalone"}),
                         ("local", "declared"))
        self.assertEqual(effective_backend(scheduler, "r1", environ={"SCMO_HOST_ROLE": "submit"}),
                         ("slurm", "promoted-from-local"))
        # In an allocation the local executor is itself on a compute node, which is
        # where the work was supposed to go, so local stays legitimate.
        self.assertEqual(effective_backend(scheduler, "r1", environ={"SLURM_JOB_ID": "9"}),
                         ("local", "declared"))
        acked = {"SCMO_HOST_ROLE": "submit", "SCMO_LOGIN_EXECUTION_ACK": "r1"}
        self.assertEqual(effective_backend(scheduler, "r1", environ=acked), ("local", "declared"))
        # The acknowledgement names one run, so it cannot cover the next one.
        self.assertEqual(effective_backend(scheduler, "r2", environ=acked), ("slurm", "promoted-from-local"))
        self.assertFalse(submit_host_execution_allowed("r2", environ=acked))
        self.assertFalse(submit_host_execution_allowed("r1", environ={"SCMO_HOST_ROLE": "submit"}))
        self.assertTrue(submit_host_execution_allowed("r1", environ={"SCMO_HOST_ROLE": "compute"}))
        self.assertEqual(login_execution_ack(acked), "r1")
        self.assertEqual(login_execution_ack({"SCMO_LOGIN_EXECUTION_ACK": "  "}), "")

    def test_generated_backend_follows_the_generating_host(self):
        def drop_backend(intake):
            # The fixture declares `backend: local`, and a declaration wins, so the
            # generated default is only observable once it is withdrawn.
            intake["scheduler"].pop("backend", None)

        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp) / "submit-host", "rna", mutate=drop_backend,
                                    env={"SCMO_HOST_ROLE": "submit"})
            scheduler = json.loads((project / "config/scheduler.yaml").read_text())
            self.assertEqual(scheduler["backend"], "slurm")
            self.assertIsInstance(scheduler["partitions"], list)
            report = (project / "Report.md").read_text(encoding="utf-8")
            self.assertIn("generating host", report)
            self.assertIn("Slurm submit host", report)
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp) / "standalone", "rna", mutate=drop_backend,
                                    env={"SCMO_HOST_ROLE": "standalone"})
            self.assertEqual(json.loads((project / "config/scheduler.yaml").read_text())["backend"], "local")
            self.assertIn("No Slurm controller answered", (project / "Report.md").read_text(encoding="utf-8"))

    def test_a_declared_backend_the_host_cannot_honour_is_kept_and_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna", env={"SCMO_HOST_ROLE": "submit"})
            # The fixture declares local; the declaration is the operator's, so it
            # stands in the config, and the report is where the conflict is visible.
            self.assertEqual(json.loads((project / "config/scheduler.yaml").read_text())["backend"], "local")
            self.assertIn("cannot honour", (project / "Report.md").read_text(encoding="utf-8"))

    def test_local_validation_warns_on_a_login_node_without_changing_the_signature(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna")
            with mock.patch.dict(os.environ, {"SCMO_HOST_ROLE": "submit"}):
                on_submit = validate(project)
            with mock.patch.dict(os.environ, {"SCMO_HOST_ROLE": "standalone"}):
                on_standalone = validate(project)
            # A warning, not an error: planning and a dry run change nothing, and a
            # read-only preflight has to stay usable from a host that is not the one
            # the work will run on.
            self.assertEqual(on_submit["status"], "valid")
            self.assertEqual(on_submit["host_role"], "submit")
            self.assertIn("submit host", " ".join(on_submit["warnings"]))
            self.assertEqual(on_standalone["warnings"], [])
            # The host is provenance, not input: a signature that moved with it would
            # orphan every recorded full validation and block a signed plan.
            self.assertEqual(on_submit["input_signature"], on_standalone["input_signature"])

    def test_submit_promotes_a_local_project_to_slurm_on_a_login_node(self):
        def declare_partitions(intake):
            intake["scheduler"]["partitions"] = ["cpu"]

        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna", mutate=declare_partitions)
            subprocess.check_call([sys.executable, str(ROOT / "scripts" / "plan_workflow.py"),
                                   "--project", str(project), "--routes", "auto", "--run-id", "unit"])
            with mock.patch.dict(os.environ, {"SCMO_HOST_ROLE": "submit"}):
                result = submit(project, "unit", dry_run=True)
            self.assertEqual(result["status"], "dry_run")
            self.assertEqual(result["backend_effective"], "slurm")
            self.assertEqual(result["backend_source"], "promoted-from-local")
            records = json.loads((project / ".workflow/runs/unit/submissions.json").read_text())
            scanpy = [item for item in records if item["task"] == "scanpy"][0]
            self.assertEqual(scanpy["backend_declared"], "local")
            self.assertEqual(scanpy["backend_effective"], "slurm")
            self.assertEqual(scanpy["host_role"], "submit")
            self.assertFalse(scanpy["login_execution"])
            # Nothing ran: a promotion that silently executed locally would leave a
            # local_ job id behind, which is what the deployed evidence looked like.
            self.assertFalse(scanpy["job_id"].startswith("local_"))

    def test_promotion_on_a_login_node_says_which_partitions_exist(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna")
            subprocess.check_call([sys.executable, str(ROOT / "scripts" / "plan_workflow.py"),
                                   "--project", str(project), "--routes", "auto", "--run-id", "unit"])
            with mock.patch.dict(os.environ, {"SCMO_HOST_ROLE": "submit"}):
                with self.assertRaises(WorkflowError) as caught:
                    submit(project, "unit", dry_run=True)
            # A promotion that needs a partition allow-list has to say so, and say
            # what the cluster offers, rather than reporting the bare Slurm message.
            message = str(caught.exception)
            self.assertIn("promoted to Slurm", message)
            self.assertIn("partitions", message)

    def test_resource_snapshot_records_the_host_role(self):
        fixtures = ROOT / "tests" / "fixtures"

        def declare_partitions(intake):
            intake["scheduler"]["partitions"] = ["cpu"]

        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna", mutate=declare_partitions)
            snapshot = inspect_resources(project, "scanpy")
            self.assertEqual(snapshot["host_role"], "standalone")
            self.assertEqual(snapshot["backend"], "local")
            self.assertEqual(snapshot["nodes"], [])
            # On a submit host the local branch is not taken, so the snapshot can no
            # longer report a resource check that never queried the cluster.
            with mock.patch.dict(os.environ, {"SCMO_HOST_ROLE": "submit"}):
                promoted = inspect_resources(project, "scanpy", sinfo_file=fixtures / "sinfo.txt",
                                             scontrol_file=fixtures / "scontrol.txt",
                                             squeue_file=fixtures / "squeue.txt")
            self.assertEqual(promoted["host_role"], "submit")
            self.assertEqual(promoted["backend"], "slurm")
            self.assertEqual(promoted["backend_source"], "promoted-from-local")
            self.assertTrue(promoted["nodes"])

    def test_run_task_refuses_a_login_node_before_writing_any_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna")
            command = [sys.executable, str(project / "Scripts/Common/run_task.py"),
                       "--project", str(project), "--run-id", "unit", "--task", "scanpy"]
            refused = subprocess.run(command, env=dict(os.environ, SCMO_HOST_ROLE="submit"),
                                     capture_output=True, text=True)
            self.assertEqual(refused.returncode, 2)
            self.assertIn("submit host", refused.stderr)
            # Refused before it read a plan or made the task directory: a refusal is
            # a precondition failure, and a status file here would read as a real try.
            self.assertFalse((project / ".workflow/runs/unit/tasks/scanpy").exists())
            # The acknowledgement is scoped to one run, and this is a different one.
            mismatched = subprocess.run(command, capture_output=True, text=True, env=dict(
                os.environ, SCMO_HOST_ROLE="submit", SCMO_LOGIN_EXECUTION_ACK="another-run"))
            self.assertEqual(mismatched.returncode, 2)
            self.assertIn("submit host", mismatched.stderr)
            acknowledged = subprocess.run(command, capture_output=True, text=True, env=dict(
                os.environ, SCMO_HOST_ROLE="submit", SCMO_LOGIN_EXECUTION_ACK="unit"))
            self.assertNotIn("submit host", acknowledged.stderr)

    def test_task_adapter_refuses_a_login_node(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna")
            refused = subprocess.run(
                [sys.executable, str(project / "Scripts/Common/task_adapter.py"),
                 "--project", str(project), "--run-id", "unit", "--task", "scanpy",
                 "--task-dir", str(project / ".workflow/runs/unit/tasks/scanpy")],
                env=dict(os.environ, SCMO_HOST_ROLE="submit"), capture_output=True, text=True)
            # A separate entry point, not a copy of run_task.py's guard: without it a
            # hand call here runs a whole stage unchecked.
            self.assertEqual(refused.returncode, 2)
            self.assertIn("submit host", refused.stderr)

    def test_a_local_run_records_the_host_it_ran_on(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna")
            subprocess.check_call([sys.executable, str(ROOT / "scripts" / "plan_workflow.py"),
                                   "--project", str(project), "--routes", "auto", "--run-id", "unit"])
            subprocess.check_call([sys.executable, str(ROOT / "scripts" / "submit_workflow.py"),
                                   "--project", str(project), "--run-id", "unit"])
            records = json.loads((project / ".workflow/runs/unit/submissions.json").read_text())
            scanpy = [item for item in records if item["task"] == "scanpy"][0]
            self.assertEqual(scanpy["host_role"], "standalone")
            self.assertEqual(scanpy["host_role_source"], "declared")
            self.assertEqual(scanpy["backend_declared"], scanpy["backend_effective"])
            self.assertFalse(scanpy["login_execution"])
            status = json.loads((project / ".workflow/runs/unit/tasks/scanpy/task_status.json").read_text())
            self.assertEqual(status["host_role"], "standalone")
            self.assertEqual(status["slurm_job_id"], "")

    def test_inspection_reports_a_login_node_run_and_says_the_role_is_unrecorded(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna")
            plan = {"input_signature": "sig", "code_signature": "code",
                    "result_dir": str(project / "Results" / "runs" / "legacy"),
                    "tasks": [{"id": "scanpy", "profile": "scanpy", "dependencies": [], "parameters": {}}]}
            run_dir = project / ".workflow" / "runs" / "legacy"
            run_dir.mkdir(parents=True)
            (run_dir / "plan.json").write_text(json.dumps(plan))
            # A pre-fix record: it has a synthesized local id and no host role,
            # which is exactly what the deployed runs looked like.
            (run_dir / "submissions.json").write_text(json.dumps(
                [{"task": "scanpy", "status": "complete", "job_id": "local_scanpy"}]))
            summary = inspect_run(project, "legacy")
            self.assertEqual(summary["login_execution_tasks"], ["scanpy"])
            row = summary["tasks"][0]
            self.assertTrue(row["executed_on_login_node"])
            self.assertEqual(row["submitted_from_host_role"], "unrecorded")

    def test_inspection_does_not_call_a_standalone_local_run_a_violation(self):
        """With no controller there is no compute node, so local is correct there."""
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna")
            plan = {"input_signature": "sig", "code_signature": "code",
                    "result_dir": str(project / "Results" / "runs" / "solo"),
                    "tasks": [{"id": "scanpy", "profile": "scanpy", "dependencies": [], "parameters": {}}]}
            run_dir = project / ".workflow" / "runs" / "solo"
            run_dir.mkdir(parents=True)
            (run_dir / "plan.json").write_text(json.dumps(plan))
            (run_dir / "submissions.json").write_text(json.dumps([
                {"task": "scanpy", "status": "complete", "job_id": "local_scanpy",
                 "host_role": "standalone", "backend_effective": "local"}]))
            summary = inspect_run(project, "solo")
            self.assertEqual(summary["login_execution_tasks"], [])
            self.assertFalse(summary["tasks"][0]["executed_on_login_node"])
            self.assertEqual(summary["tasks"][0]["submitted_from_host_role"], "standalone")

    def test_inspection_separates_the_host_that_ran_a_task_from_the_one_that_submitted_it(self):
        """The two roles differ on a healthy run, so one field cannot carry both."""
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna")
            plan = {"input_signature": "sig", "code_signature": "code",
                    "result_dir": str(project / "Results" / "runs" / "split"),
                    "tasks": [{"id": "scanpy", "profile": "scanpy", "dependencies": [], "parameters": {}}]}
            run_dir = project / ".workflow" / "runs" / "split"
            run_dir.mkdir(parents=True)
            (run_dir / "plan.json").write_text(json.dumps(plan))
            (run_dir / "submissions.json").write_text(json.dumps([
                {"task": "scanpy", "status": "submitted", "job_id": "4242", "host_role": "submit"}]))
            task_dir = run_dir / "tasks" / "scanpy"
            task_dir.mkdir(parents=True)
            (task_dir / "task_status.json").write_text(json.dumps(
                {"status": "failed", "host_role": "compute", "return_code": 1}))
            row = inspect_run(project, "split")["tasks"][0]
            self.assertEqual(row["submitted_from_host_role"], "submit")
            self.assertEqual(row["executed_on_host_role"], "compute")
            self.assertFalse(row["executed_on_login_node"])

    def test_host_policy_is_stated_where_its_reader_will_find_it(self):
        """This skill's reader is an agent, so the documented rule is part of the guard."""
        execution = (ROOT / "references/execution.md").read_text(encoding="utf-8")
        self.assertIn("## Host roles", execution)
        self.assertIn("A planned task is never executed on a submit host", execution)
        # The claim that the two backends were equivalent is what made a login node
        # look like a supported place to run a full analysis.
        self.assertNotIn("The local backend applies the same resource floors", execution)
        self.assertIn("Never execute a planned task on a Slurm submit host",
                      (ROOT / "SKILL.md").read_text(encoding="utf-8"))
        for path in ("Scripts/Methylvi/allcools/run.sh", "Scripts/Methylvi/vmr/run.sh"):
            script = (ROOT / "assets/project-template" / path).read_text(encoding="utf-8")
            self.assertIn("is a Slurm submit host (login node)", script)

    def test_slurm_reserved_and_observed_memory_are_distinct(self):
        fixtures = ROOT / "tests" / "fixtures"
        nodes = enrich_nodes(
            parse_sinfo((fixtures / "sinfo.txt").read_text()),
            parse_scontrol((fixtures / "scontrol.txt").read_text()), 4096,
        )
        node = [item for item in nodes if item["name"] == "node-a"][0]
        self.assertEqual(node["schedulable_memory_mb"], 83904)
        self.assertEqual(node["observed_free_memory_mb"], 70000)
        scheduler = {"partitions": ["cpu"], "allow_nodes": [], "exclude_nodes": []}
        profile = {"floor": {"cpus": 4, "memory": "16G"}, "target": {"cpus": 16, "memory": "64G", "time": "01:00:00"}, "ceiling": {"cpus": 24, "memory": "96G"}}
        recommendation = choose(nodes, scheduler, profile)
        self.assertEqual(recommendation["reference_node"], "node-a")
        too_large = {"floor": {"cpus": 30, "memory": "100G"}, "target": {"cpus": 32, "memory": "120G"}, "ceiling": {"cpus": 64, "memory": "256G"}}
        with self.assertRaises(WorkflowError):
            choose(nodes, scheduler, too_large)
        self.assertEqual([item for item in nodes if item["name"] == "node-c"][0]["state"], "down")

    # --- root README/Report: filled once at generation, appended per run -------

    def record_run(self, project: Path, run_id: str, when: str, tasks, signature: str = "sig",
                   task_names=None) -> Path:
        """Write the run_summary.json that inspect_run.py leaves behind.

        Recording evidence directly keeps these tests to the documentation
        contract; executing a real run is covered by the plan/submit tests.
        `task_names` names the tasks with real workflow ids so the per-stage
        routing can be exercised; the default names belong to no stage.
        """
        run_dir = project / ".workflow" / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        names = list(task_names) if task_names else ["task_%d" % index for index in range(len(tasks))]
        rows = [{"task": name, "job_id": "", "state": state,
                 "complete_marker": bool(valid), "evidence_valid": bool(valid),
                 "evidence_error": None, "resource_usage": None}
                for name, (state, valid) in zip(names, tasks)]
        if rows and all(row["evidence_valid"] for row in rows):
            status = "complete"
        elif any(row["state"] in TERMINAL_BAD for row in rows):
            status = "failed"
        else:
            status = "planned"
        path = run_dir / "run_summary.json"
        path.write_text(json.dumps({
            "schema_version": 1, "run_id": run_id, "status": status, "checked_at": when,
            "tasks": rows, "input_signature": signature,
        }), encoding="utf-8")
        return path

    def install_report(self, project: Path, text: str) -> None:
        (project / "Report.md").write_text(text, encoding="utf-8")

    def test_generated_readme_uses_real_project_facts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = self.generate(root, "paired")
            readme = (project / "README.md").read_text(encoding="utf-8")
            for fact in ("fixture", "human", "fixture-build", "S1", "control", "2000", "0.8",
                         str(root / "input/refs/genome.chrom.sizes")):
                self.assertIn(fact, readme)
            # Every section is filled, in both languages, and no format placeholder
            # survived the rewrite.
            for heading in ("### 项目", "### 样本", "### 关键分析参数", "### Project",
                            "### Samples", "### Key analysis parameters"):
                self.assertIn(heading, readme)
            self.assertNotIn("{0}", readme)
            self.assertIn("never rewritten with runtime state", readme)
            self.assertIn("永不写入运行时状态", readme)

    def test_generated_report_region_is_canonical(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "paired")
            report = project / "Report.md"
            text = report.read_text(encoding="utf-8")
            self.assertEqual(text.count(RUNLOG_START), 1)
            self.assertEqual(text.count(RUNLOG_END), 1)
            self.assertLess(text.index(RUNLOG_START), text.index(RUNLOG_END))
            self.assertIn(RUNLOG_EMPTY, text)
            # Canonical from the first byte: refreshing an untouched project is a
            # no-op rather than a rewrite.
            before = report.read_bytes()
            self.assertFalse(refresh_run_log(project)["written"])
            self.assertEqual(report.read_bytes(), before)

    def test_readme_is_frozen_after_inspection(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna")
            readme = project / "README.md"
            before = readme.read_bytes()
            subprocess.check_call([sys.executable, str(ROOT / "scripts/plan_workflow.py"),
                                   "--project", str(project), "--routes", "auto", "--run-id", "unit"])
            subprocess.check_call([sys.executable, str(ROOT / "scripts/submit_workflow.py"),
                                   "--project", str(project), "--run-id", "unit"])
            subprocess.check_call([sys.executable, str(ROOT / "scripts/inspect_run.py"),
                                   "--project", str(project), "--run-id", "unit"])
            subprocess.check_call([sys.executable, str(ROOT / "scripts/update_report.py"),
                                   "--project", str(project)])
            self.assertEqual(readme.read_bytes(), before)
            self.assertIn("### `unit`", (project / "Report.md").read_text(encoding="utf-8"))

    def test_reinspection_upserts_one_record_and_rebuild_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna")
            for run_id in ("unit", "second"):
                subprocess.check_call([sys.executable, str(ROOT / "scripts/plan_workflow.py"),
                                       "--project", str(project), "--routes", "auto", "--run-id", run_id])
                subprocess.check_call([sys.executable, str(ROOT / "scripts/submit_workflow.py"),
                                       "--project", str(project), "--run-id", run_id])
            subprocess.check_call([sys.executable, str(ROOT / "scripts/inspect_run.py"),
                                   "--project", str(project), "--run-id", "unit"])
            report = project / "Report.md"
            once = report.read_text(encoding="utf-8")
            self.assertEqual(once.count("<!-- SCMO-RUN:unit:START -->"), 1)
            self.assertEqual(once.count("<!-- SCMO-RUN:second:START -->"), 0)
            subprocess.check_call([sys.executable, str(ROOT / "scripts/inspect_run.py"),
                                   "--project", str(project), "--run-id", "unit"])
            self.assertEqual(report.read_text(encoding="utf-8").count("<!-- SCMO-RUN:unit:START -->"), 1)
            subprocess.check_call([sys.executable, str(ROOT / "scripts/inspect_run.py"),
                                   "--project", str(project), "--run-id", "second"])
            inspected = report.read_bytes()
            # The rebuild path and the automatic path are one renderer, so both
            # reproduce the file inspection left behind, byte for byte.
            subprocess.check_call([sys.executable, str(ROOT / "scripts/update_report.py"),
                                   "--project", str(project), "--run-id", "unit"])
            self.assertEqual(report.read_bytes(), inspected)
            subprocess.check_call([sys.executable, str(ROOT / "scripts/update_report.py"),
                                   "--project", str(project)])
            self.assertEqual(report.read_bytes(), inspected)

    def test_report_log_survives_pruned_run_dirs(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "paired")
            self.record_run(project, "unit", "2026-09-19T08:00:00+00:00", [("complete", True)])
            self.record_run(project, "second", "2026-09-20T08:00:00+00:00", [("complete", True)])
            refresh_run_log(project)
            (project / ".workflow/runs/unit/run_summary.json").unlink()
            self.record_run(project, "third", "2026-09-21T08:00:00+00:00", [("complete", True)])
            refresh_run_log(project)
            text = (project / "Report.md").read_text(encoding="utf-8")
            # The record is the log's, not the run directory's: pruning the
            # evidence must not erase the history that cited it.
            self.assertEqual(text.count("<!-- SCMO-RUN:unit:START -->"), 1)
            for run_id in ("unit", "second", "third"):
                self.assertIn("### `%s`" % run_id, text)
            unit = text[text.index("<!-- SCMO-RUN:unit:START -->"):text.index("<!-- SCMO-RUN:unit:END -->")]
            self.assertIn("1/1 complete", unit)

    def test_run_record_counts_follow_validated_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "paired")
            self.record_run(project, "mixed", "2026-09-19T08:00:00+00:00", [
                ("complete", True),      # validated evidence
                ("FAILED", False),       # terminal failure
                ("not_submitted", False),  # never ran
                ("complete", False),     # scheduler says complete, evidence does not
            ])
            refresh_run_log(project)
            text = (project / "Report.md").read_text(encoding="utf-8")
            record = text[text.index("<!-- SCMO-RUN:mixed:START -->"):text.index("<!-- SCMO-RUN:mixed:END -->")]
            self.assertIn("1/4 complete, 1 failed, 2 unfinished", record)
            self.assertIn("### `mixed` — failed", record)

    def test_report_log_repairs_malformed_markers(self):
        record = build_report_text("", [{
            "run_id": "unit", "status": "complete", "checked_at": "2026-09-19T08:00:00+00:00",
            "tasks": [{"evidence_valid": True, "state": "complete"}], "input_signature": "sig",
        }])
        cases = {
            "legacy run-state region":
                "# Report\n\n" + LEGACY_RUN_STATE_START + "\n### `old`\n\n- legacy body\n" + LEGACY_RUN_STATE_END + "\n",
            "orphan END": "# Report\n\n" + RUNLOG_END + "\n",
            "orphan START": "# Report\n\n" + RUNLOG_START + "\n",
            "END before START": "# Report\n\n" + RUNLOG_END + "\n" + RUNLOG_START + "\n",
            "section missing END":
                "# Report\n\n" + RUNLOG_START + "\n<!-- SCMO-RUN:r9:START -->\n### `r9` — x\n" + RUNLOG_END + "\n",
            "orphan section END":
                "# Report\n\n" + RUNLOG_START + "\n<!-- SCMO-RUN:ghost:END -->\n" + RUNLOG_END + "\n",
            "duplicated region": "# Report\n\n" + record + "\n\n" + record + "\n",
        }
        for name, text in cases.items():
            with self.subTest(name):
                with tempfile.TemporaryDirectory() as temp:
                    project = self.generate(Path(temp), "paired")
                    self.install_report(project, text)
                    self.record_run(project, "unit", "2026-09-19T08:00:00+00:00", [("complete", True)])
                    refresh_run_log(project)
                    first = (project / "Report.md").read_text(encoding="utf-8")
                    # The re-render repairs whatever it parsed, in one pass: a
                    # second refresh has nothing left to change.
                    self.assertFalse(refresh_run_log(project)["written"])
                    self.assertEqual((project / "Report.md").read_text(encoding="utf-8"), first)
                    self.assertLess(first.index(RUNLOG_START), first.index(RUNLOG_END))
                    # One record per run inside the region, never a duplicate pair
                    # of markers. Residue outside the region is the caller's text
                    # and is preserved verbatim rather than deleted, so a
                    # duplicated region shows up there and is not counted here.
                    region = first[first.index(RUNLOG_START):first.index(RUNLOG_END)]
                    self.assertEqual(region.count("<!-- SCMO-RUN:unit:START -->"), 1)
                    self.assertEqual(region.count("<!-- SCMO-RUN:unit:END -->"), 1)
                    self.assertEqual(region.count("### `unit`"), 1)
                    self.assertIn("1/1 complete", region)
        duplicated = cases["duplicated region"]
        repaired = build_report_text(duplicated, [])
        self.assertEqual(repaired.count("<!-- SCMO-RUN:unit:START -->"), 2)
        self.assertTrue(repaired.endswith(record))
        legacy = cases["legacy run-state region"]
        repaired = build_report_text(legacy, [])
        self.assertNotIn(LEGACY_RUN_STATE_START, repaired)
        self.assertIn("legacy body", repaired)

    def test_report_run_key_is_marker_safe(self):
        keys = [report_run_key(value) for value in ("a-->b", "a b", "运行1", "a:b")]
        for key in keys:
            self.assertTrue(RUN_KEY_SAFE_RE.match(key), key)
            self.assertNotIn("-->", key)
        self.assertEqual(len(set(keys)), len(keys))
        self.assertEqual(report_run_key("run_001"), "run_001")
        self.assertEqual(report_run_key("a-->b"), report_run_key("a-->b"))
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "paired")
            self.record_run(project, "a-->b", "2026-09-19T08:00:00+00:00", [("complete", True)])
            refresh_run_log(project)
            text = (project / "Report.md").read_text(encoding="utf-8")
            # The record keeps the real id in its body; only the marker key is
            # replaced, so the region can never be broken by an unsafe id.
            self.assertIn("### `a-->b`", text)
            self.assertEqual(text.count(RUNLOG_START), 1)
            self.assertEqual(text.count(RUNLOG_END), 1)
            self.assertEqual(text.count("<!-- SCMO-RUN:%s:START -->" % report_run_key("a-->b")), 1)

    def test_update_report_cli_and_run_id_is_optional(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "paired")
            self.record_run(project, "unit", "2026-09-19T08:00:00+00:00", [("complete", True)])
            report_cli = [sys.executable, str(ROOT / "scripts/update_report.py"), "--project", str(project)]
            self.assertEqual(subprocess.call(report_cli), 0)
            self.assertEqual(subprocess.call(report_cli + ["--run-id", "unit"]), 0)
            self.assertEqual(subprocess.call(report_cli + ["--run-id", "nope"]), 2)
            self.assertEqual(subprocess.call([sys.executable, str(project / "workflow.py"), "report"]), 0)

    def test_module_docs_are_bound_to_the_project_and_their_logs_track_it(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna")
            module_docs = [path for path in sorted((project / "Scripts").rglob("*.md"))]
            self.assertTrue(module_docs)
            # Generation binds every stage document to this project exactly once.
            for path in module_docs:
                text = path.read_text(encoding="utf-8")
                self.assertEqual(text.count(STAGE_CONTEXT_START), 1, str(path))
                self.assertEqual(text.count(STAGE_CONTEXT_END), 1, str(path))
                self.assertNotIn("Notebooks/<notebook>.ipynb", text, str(path))
            self.assertEqual(module_docs[0].read_text(encoding="utf-8").count(STAGE_CONTEXT_START), 1)
            subprocess.check_call([sys.executable, str(ROOT / "scripts/plan_workflow.py"),
                                   "--project", str(project), "--routes", "auto", "--run-id", "unit"])
            subprocess.check_call([sys.executable, str(ROOT / "scripts/submit_workflow.py"),
                                   "--project", str(project), "--run-id", "unit"])
            subprocess.check_call([sys.executable, str(ROOT / "scripts/inspect_run.py"),
                                   "--project", str(project), "--run-id", "unit"])
            subprocess.check_call([sys.executable, str(ROOT / "scripts/update_report.py"),
                                   "--project", str(project)])
            scanpy = project / "Scripts" / "Scanpy" / "Report.md"
            methscan = project / "Scripts" / "Methscan" / "Report.md"
            readme = project / "Scripts" / "Scanpy" / "README.md"
            # The stage this run touched recorded it; an RNA-only run leaves the
            # methylation stages alone rather than padding them with a record
            # that says nothing about them.
            self.assertIn("<!-- SCMO-RUN:unit:START -->", scanpy.read_text(encoding="utf-8"))
            self.assertNotIn("<!-- SCMO-RUN:unit:START -->", methscan.read_text(encoding="utf-8"))
            # The stage README is generated-once text and no run rewrites it.
            self.assertIn(STAGE_CONTEXT_START, readme.read_text(encoding="utf-8"))
            before = readme.read_bytes()
            subprocess.check_call([sys.executable, str(ROOT / "scripts/update_report.py"),
                                   "--project", str(project)])
            self.assertEqual(readme.read_bytes(), before)
            # The stage record and the root record are the same run: one corpus of
            # summaries rendered twice, so they cannot disagree about it.
            root = (project / "Report.md").read_text(encoding="utf-8")
            for text in (root, scanpy.read_text(encoding="utf-8")):
                self.assertIn("<!-- SCMO-RUN:unit:START -->", text)
                self.assertIn("`unit` — complete", text)

    def test_stage_routing_names_every_task_that_has_a_home(self):
        expected = {
            "scanpy": "Scanpy",
            "methscan_select_convert": "Methscan", "methscan_prepare": "Methscan",
            "methscan_filter": "Methscan", "methscan_smooth": "Methscan",
            "methscan_pairwise_dmr": "Methscan", "methscan_hypo_heatmaps": "Methscan",
            "methscan_pooled_dmr": "Methscan",
            "methscan_vmr_0.05": "Methscan",
            "allcools_features": "Methylvi/allcools",
            "methylvi_allcools_1000": "Methylvi/allcools",
            "methylvi_vmr_features_0.05": "Methylvi",
            "methylvi_vmr_0.05_1000": "Methylvi",
            "pooled_dmr_prepare": "Methylvi/vmr_dmr", "pooled_dmr_counts": "Methylvi/vmr_dmr",
            "methylvi_vmr_dmr_0.05_1000": "Methylvi/vmr_dmr",
        }
        for task_id, stage in expected.items():
            self.assertEqual(stage_for_task(task_id), stage, task_id)
        # The run-level summary is unowned: it would otherwise appear in every
        # stage log as though each stage had run it.
        for task_id in ("workflow_summary", "task_0", "", None):
            self.assertIsNone(stage_for_task(task_id), repr(task_id))
        # Prefix order: the DMR trainers must not fall through to the broader
        # `methylvi_vmr_` prefix, which would file them under the wrong report.
        self.assertEqual(stage_for_task("methylvi_vmr_dmr_0.01_2000"), "Methylvi/vmr_dmr")

    def test_every_dag_task_has_a_stage_or_is_deliberately_unowned(self):
        """No task may fall outside every stage log by omission.

        The per-stage routing is an explicit table rather than a guess, so a task
        added to the DAG without a stage would simply vanish from every stage
        Report while the run still claims to have performed it. Enumerating the
        DAG's own output here makes that a test failure instead of a silent gap.
        """
        # The run-level summary is the one task that belongs to no stage: it
        # summarises the whole run, and every stage log showing it would read as
        # though each stage had run it.
        UNOWNED = {"workflow_summary"}
        routes = {"scanpy": True, "methscan_vmr": True, "methscan_dmr": True, "allcools": True,
                  "methylvi_allcools": True, "methylvi_vmr": True, "methylvi_vmr_dmr": True}
        tasks = make_tasks(routes, json.loads(json.dumps(DEFAULT_ANALYSIS)))
        self.assertTrue(tasks)
        known = {stage for stage, _ in STAGE_REPORTS}
        for item in tasks:
            stage = stage_for_task(item["id"])
            if item["id"] in UNOWNED:
                self.assertIsNone(stage, item["id"])
            else:
                self.assertIn(stage, known, "%s has no stage report" % item["id"])

    def test_stage_log_counts_only_its_own_tasks(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "paired")
            self.record_run(
                project, "unit", "2026-09-19T08:00:00+00:00",
                [("complete", True), ("complete", True), ("complete", True)],
                task_names=["scanpy", "methscan_prepare", "workflow_summary"],
            )
            outcome = refresh_stage_run_logs(project)
            by_stage = {row["stage"]: row for row in outcome["stages"]}
            self.assertTrue(by_stage["Scanpy"]["written"])
            scanpy = (project / "Scripts" / "Scanpy" / "Report.md").read_text(encoding="utf-8")
            methscan = (project / "Scripts" / "Methscan" / "Report.md").read_text(encoding="utf-8")
            # One task each, not the run's three: the stage view is filtered, and
            # the unowned summary task appears in neither.
            self.assertIn("- Tasks / 任务：1/1 complete, 0 failed, 0 unfinished", scanpy)
            self.assertIn("- Tasks / 任务：1/1 complete, 0 failed, 0 unfinished", methscan)
            self.assertNotIn("workflow_summary", scanpy)
            self.assertNotIn("workflow_summary", methscan)

    def test_stage_log_carries_the_stage_verdict_not_the_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "paired")
            # The run as a whole is unfinished, but Scanpy itself is complete;
            # reporting the run's status in the Scanpy report would let it read
            # `complete` while its own task failed, or the reverse here.
            self.record_run(
                project, "unit", "2026-09-19T08:00:00+00:00",
                [("complete", True), ("PENDING", False)],
                task_names=["scanpy", "methscan_prepare"],
            )
            refresh_stage_run_logs(project)
            scanpy = (project / "Scripts" / "Scanpy" / "Report.md").read_text(encoding="utf-8")
            methscan = (project / "Scripts" / "Methscan" / "Report.md").read_text(encoding="utf-8")
            self.assertIn("`unit` — complete", scanpy)
            self.assertIn("`unit` — unfinished", methscan)

    def test_stage_context_block_binds_the_documents_to_the_project(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "paired")
            readme = (project / "Scripts" / "Scanpy" / "README.md").read_text(encoding="utf-8")
            # What generation knows about this project, and the entry it ships.
            self.assertIn("`fixture`", readme)
            self.assertIn("`S1`", readme)
            self.assertIn("`Notebooks/scanpy_workflow.ipynb`", readme)
            # And what it deliberately does not claim: the template's own worked
            # numbers stay labelled as the reference project's, because rewriting
            # them into statements about this project would invent evidence.
            self.assertIn("belong to the reference project", readme)
            # Re-running generation over an existing tree is a no-op, so a
            # half-generated project converges instead of accumulating banners.
            before = readme.encode("utf-8")
            adapt_stage_docs(project, "fixture", "human", "fixture-build", ["S1", "S2"],
                             packaged_notebook(project))
            self.assertEqual(readme.encode("utf-8"), before)

    def test_environment_report_keeps_the_generated_regions_across_a_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "paired")
            report = project / "Scripts" / "Environment" / "Report.md"
            self.assertIn(STAGE_CONTEXT_START, report.read_text(encoding="utf-8"))
            # This report is a whole-file snapshot of provisioning state, so the
            # context block has to survive the rewrite rather than be clobbered.
            environment_bootstrap.write_environment_report(project, {
                "status": "ok", "mode": "discover", "manager": "conda",
                "created_at": "2026-09-20T00:00:00+00:00",
                "actions": [{"profile": "orchestrator", "action": "reuse", "prefix": "/envs/x"}],
            })
            text = report.read_text(encoding="utf-8")
            self.assertEqual(text.count(STAGE_CONTEXT_START), 1)
            self.assertIn("`orchestrator`", text)

    def test_sample_include_agrees_with_loader(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            intake = self.build_inputs(root, "paired")
            payload = json.loads(intake.read_text(encoding="utf-8"))
            payload["samples"][0]["include"] = "TRUE"
            intake.write_text(json.dumps(payload), encoding="utf-8")
            project = root / "project"
            subprocess.check_call([sys.executable, str(ROOT / "scripts/init_project.py"),
                                   "--intake", str(intake), "--output", str(project)])
            # The README must show the same verdict the loader reaches, so an
            # unusual spelling such as "TRUE" cannot make the two disagree.
            readme = (project / "README.md").read_text(encoding="utf-8")
            rows = [line for line in readme.splitlines() if line.startswith("| S1 |")]
            self.assertEqual(len(rows), 2, readme)  # one row per language half
            for row in rows:
                self.assertIn("| yes |", row)
            samples = load_samples(project)
            self.assertEqual(len(samples), 1)
            self.assertTrue(samples[0]["include"])

    # --- declared input data: linked into Data/, never read from elsewhere ------

    def shared_data(self, root: Path) -> Path:
        """A stand-in for storage outside the project: the data the intake points at."""
        shared = root / "shared"
        for name in ("Matrix", "ALLCools"):
            (shared / name).mkdir(parents=True)
            (shared / name / "sample.dat").write_text(name, encoding="utf-8")
        return shared

    def test_declared_data_sources_are_linked_into_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shared = self.shared_data(root)
            project = self.generate(root, "paired", mutate=lambda intake: intake.update(
                {"data": {"sources": [{"name": "Matrix", "path": str(shared / "Matrix")}]}}))
            link = project / "Data" / "Matrix"
            self.assertTrue(link.is_symlink(), "declared sources must be linked, not copied")
            self.assertEqual(link.resolve(), (shared / "Matrix").resolve())
            self.assertEqual((link / "sample.dat").read_text(encoding="utf-8"), "Matrix")
            # The declaration is carried into the project so the link can be
            # rebuilt later, and so the input signature covers where data came from.
            self.assertEqual(load_project(project)["data"]["sources"][0]["target"], str(shared / "Matrix"))
            for document in ("README.md", "Report.md"):
                text = (project / document).read_text(encoding="utf-8")
                self.assertIn(str(shared / "Matrix"), text, document)
                self.assertIn("Matrix", text, document)
            # A reachable entry passes validation and is recorded as such, so the
            # failure modes below are about reachability and not about the check.
            result = validate(project, require_paths=True, mode="quick")
            self.assertEqual([entry["state"] for entry in result["data"]], ["ready"])
            self.assertFalse([error for error in result["errors"] if "Data/Matrix" in error], result["errors"])
            # Planning is read-only; applying an already-correct plan changes nothing.
            plan = subprocess.run([sys.executable, str(project / "tools" / "link_data.py"),
                                   "--project", str(project)], capture_output=True, text=True)
            self.assertIn("0 of 1 entries need work", plan.stdout)
            before = link.resolve()
            subprocess.check_call([sys.executable, str(project / "tools" / "link_data.py"),
                                   "--project", str(project), "--execute"])
            self.assertEqual(link.resolve(), before)

    def test_data_url_source_stays_pending_until_fetched_and_verified(self):
        """A url source is declared by generation and materialized only by the tool."""
        import functools
        import hashlib
        import http.server
        import threading

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = root / "serve" / "features.bin"
            payload.parent.mkdir(parents=True)
            payload.write_bytes(bytes(range(256)) * 4096)
            digest = hashlib.sha256(payload.read_bytes()).hexdigest()

            class Quiet(http.server.SimpleHTTPRequestHandler):
                def log_message(self, *args):
                    pass

            server = http.server.ThreadingHTTPServer(
                ("127.0.0.1", 0), functools.partial(Quiet, directory=str(payload.parent)))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            url = "http://127.0.0.1:%d/features.bin" % server.server_address[1]

            def declare(sha: str):
                return lambda intake: intake.update(
                    {"data": {"sources": [{"name": "features", "url": url, "sha256": sha}]}})

            project = self.generate(root, "rna", mutate=declare(digest))
            destination = project / "Data" / "features"
            self.assertFalse(destination.exists(), "generation must not transfer a url source")
            self.assertIn("pending", (project / "Report.md").read_text(encoding="utf-8"))
            subprocess.check_call([sys.executable, str(project / "tools" / "link_data.py"),
                                   "--project", str(project), "--execute"])
            self.assertEqual(destination.read_bytes(), payload.read_bytes())

            # A digest mismatch is refused and leaves nothing behind: a partial file
            # under the final name would be read as data by every later stage.
            broken = self.generate(root / "second", "rna", mutate=declare("0" * 64))
            result = subprocess.run([sys.executable, str(broken / "tools" / "link_data.py"),
                                     "--project", str(broken), "--execute"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("sha256", result.stderr)
            self.assertEqual(sorted((broken / "Data").glob("*")), [])

    def test_link_data_refuses_to_clobber_an_entry_it_did_not_create(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shared = self.shared_data(root)
            project = self.generate(root, "paired", mutate=lambda intake: intake.update(
                {"data": {"sources": [{"name": "Matrix", "path": str(shared / "Matrix")}]}}))
            link = project / "Data" / "Matrix"
            link.unlink()
            link.write_text("someone else's data\n", encoding="utf-8")
            result = subprocess.run([sys.executable, str(project / "tools" / "link_data.py"),
                                     "--project", str(project), "--execute"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stdout)
            self.assertIn("move it aside", result.stderr)
            self.assertEqual(link.read_text(encoding="utf-8"), "someone else's data\n")

    def test_bundled_references_apply_only_to_human_hg38_methylation_projects(self):
        """The bundled files are hg38: inheriting them anywhere else is silently wrong."""
        # applied, and for each refusal: is the reason worth stating in the Report?
        cases = (
            ("human-allc", "paired", {}, True, False),
            ("human-rna-only", "rna", {}, False, False),
            ("mouse-allc", "paired", {"organism": "mouse"}, False, True),
            ("grch37-allc", "paired", {"references_genome": "GRCh37"}, False, True),
        )
        for label, mode, overrides, expected, warned in cases:
            with self.subTest(label):
                with tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)

                    def mutate(intake, overrides=overrides):
                        intake.pop("references", None)
                        for key, value in overrides.items():
                            if key == "references_genome":
                                intake["references"] = {"genome_id": value}
                            else:
                                intake[key] = value

                    project = self.generate(root, mode, mutate=mutate)
                    references = load_project(project)["references"]
                    if expected:
                        self.assertEqual(references["chrom_sizes"], "Supplementary/hg38.canonical.chrom.sizes")
                        self.assertEqual(references["blacklist"], "Supplementary/ENCFF356LFX_GRCh38_blacklist.bed.gz")
                        self.assertEqual(references["blacklist_md5"], "393688b4f06c9ce26165d47433dd8c37")
                        self.assertEqual(references["genome_id"], "GRCh38")
                        # The bundled files are really there, or the default is a dead path.
                        for key in ("chrom_sizes", "blacklist"):
                            self.assertTrue((project / references[key]).is_file(), key)
                        note = (project / "Report.md").read_text(encoding="utf-8")
                        self.assertIn("references.chrom_sizes", note)
                        self.assertIn("Bundled references", note)
                        # The README states genome_id as a project fact, so the
                        # Report has to say generation inferred it. An
                        # undeclared genome reaching the config unannounced
                        # would read as something the user declared.
                        self.assertIn("references.genome_id` records `GRCh38", note)
                    else:
                        self.assertNotIn("chrom_sizes", references)
                        self.assertNotIn("blacklist", references)
                        # Whatever the reason, the Report must never claim the
                        # bundled file is in use; when the reason is a genome or
                        # organism that cannot use hg38, it says so.
                        note = (project / "Report.md").read_text(encoding="utf-8")
                        self.assertNotIn("hg38.canonical.chrom.sizes", note)
                        self.assertEqual("no bundled genome references were applied" in note, warned, note)

    def test_validation_reports_data_entries_that_are_missing_or_dangling(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            absent = root / "elsewhere" / "Raw"
            project = self.generate(root, "rna", mutate=lambda intake: intake.update(
                {"data": {"sources": [{"name": "Raw", "path": str(absent)}]}}))
            # The link exists but its target does not, which is what a path visible
            # only from the execution context looks like from here. The link must be
            # exactly the declared one, so "correctly shaped" cannot pass as usable.
            self.assertTrue((project / "Data" / "Raw").is_symlink())
            self.assertFalse((project / "Data" / "Raw").exists())
            result = validate(project, require_paths=True, mode="quick")
            self.assertEqual(result["status"], "invalid")
            self.assertTrue(any("Data/Raw" in error and "link_data.py" in error for error in result["errors"]),
                            result["errors"])
            self.assertEqual([entry["state"] for entry in result["data"]], ["dangling"])
            (project / "Data" / "Raw").unlink()
            result = validate(project, require_paths=True, mode="quick")
            self.assertEqual([entry["state"] for entry in result["data"]], ["dangling"])
            self.assertEqual(result["status"], "invalid")
            # With paths unrequired the same project is structurally fine: this is
            # the mode for checking a configuration on a host that cannot see the data.
            self.assertEqual(validate(project, require_paths=False, mode="quick")["status"], "valid")

    def test_slurm_resume_distinguishes_active_terminal_and_unknown_jobs(self):
        with mock.patch("submit_workflow.subprocess.check_output", return_value=b"RUNNING\n"):
            self.assertEqual(slurm_job_state("101"), "RUNNING")
        with mock.patch("submit_workflow.subprocess.check_output", side_effect=[b"", b"FAILED|\n"]):
            self.assertEqual(slurm_job_state("102"), "FAILED")
        with mock.patch("submit_workflow.subprocess.check_output", side_effect=[b"", b""]):
            with self.assertRaises(WorkflowError):
                slurm_job_state("103")

    def test_slurm_throttle_wait_does_not_become_a_scientific_dependency(self):
        self.assertEqual(
            slurm_dependency_argument(["11", "12"], ["21"]),
            "afterok:11:12,afterany:21",
        )
        self.assertEqual(slurm_dependency_argument([], ["21"]), "afterany:21")
        self.assertEqual(slurm_dependency_argument(["11"], []), "afterok:11")
        self.assertEqual(slurm_dependency_argument([], []), "")

    def test_allc_discovery_preserves_the_visible_data_index_pair(self):
        """Resolving only a data symlink can separate it from its paired .tbi."""
        script = ROOT / "assets/project-template/Scripts/Methscan/01_select_scanpy_cells.py"
        spec = importlib.util.spec_from_file_location("select_scanpy_cells_test", script)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "archive"
            visible = root / "visible"
            archive.mkdir()
            visible.mkdir()
            data_target = archive / "archive-object.gz"
            index_target = archive / "unrelated-index-name.tbi"
            data_target.write_bytes(b"allc")
            index_target.write_bytes(b"index")
            data_link = visible / "cell_allc.gz"
            index_link = visible / "cell_allc.gz.tbi"
            data_link.symlink_to(data_target)
            index_link.symlink_to(index_target)

            rows = module.discover_allcs([{
                "sample_id": "S1", "allc_root": str(visible),
                "allc_glob": "*_allc.gz", "cell_id_prefix": "S1",
            }])
            self.assertEqual(len(rows), 1)
            self.assertEqual(Path(rows[0]["source_path"]), data_link.absolute())
            self.assertEqual(Path(rows[0]["source_index"]), index_link.absolute())
            self.assertTrue(Path(rows[0]["source_path"] + ".tbi").is_file())

    def test_vmr_scan_view_records_and_excludes_empty_smoothed_chromosomes(self):
        script = ROOT / "assets/project-template/Scripts/Methscan/03_prepare_vmr_input.py"
        spec = importlib.util.spec_from_file_location("prepare_vmr_input_test", script)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "filtered"
            smooth = source / "smoothed"
            smooth.mkdir(parents=True)
            (source / "column_header.txt").write_text("cell_1\n", encoding="utf-8")
            for chrom in ("chr1", "chrEmpty"):
                (source / (chrom + ".npz")).write_bytes(b"non-empty sparse matrix placeholder")
            (smooth / "chr1.csv").write_text("0.1\n", encoding="utf-8")
            (smooth / "chrEmpty.csv").write_bytes(b"")

            view = root / "view"
            manifest = module.build_view(source, view)
            self.assertEqual(manifest["included_chromosomes"], ["chr1"])
            self.assertEqual(manifest["excluded_chromosomes"], [{
                "chromosome": "chrEmpty", "reason": "empty_smoothed_values",
            }])
            self.assertTrue((view / "chr1.npz").is_symlink())
            self.assertFalse((view / "chrEmpty.npz").exists())
            self.assertIn("chrEmpty\tempty_smoothed_values",
                          (view / "excluded_chromosomes.tsv").read_text(encoding="utf-8"))
            self.assertTrue((source / "chrEmpty.npz").is_file(), "source data must remain untouched")

    def test_candidate_marker_panel_keys_match_leiden_categories(self):
        source = notebook_source(
            ROOT / "assets/project-template/Scripts/Scanpy/Notebooks/scanpy_workflow.ipynb"
        )
        self.assertIn("data_driven_panels[str(cluster)]", source)
        self.assertNotIn("data_driven_panels[f'cluster_{cluster}']", source)


    def test_recorded_annotation_profile_review_round_trip(self):
        """The documented review loop has to be runnable: worksheet, edit, record, then load."""
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "paired")
            run_id, clusters = "review_1", {"0": ["AT1"] * 6, "1": ["AT2"] * 4, "2": ["Macrophage"] * 4 + ["Ciliated"] * 2}
            self.write_annotation_handoff(project, run_id, clusters)
            analysis_path = project / "config/project.yaml"
            config = json.loads(analysis_path.read_text())
            config["annotation"]["profile"] = "config/annotation.yaml"
            analysis_path.write_text(json.dumps(config))

            worksheet = Path(temp) / "review.tsv"
            tool = [sys.executable, str(project / "tools" / "record_annotation_review.py"),
                    "--project", str(project), "--run-id", run_id]
            self.assertEqual(subprocess.call(tool + ["--worksheet", str(worksheet)]), 0)
            rows = [line.split("\t") for line in worksheet.read_text().splitlines()]
            self.assertEqual(rows[0], ["cluster", "proposed_cell_type", "cells", "cell_type",
                                       "confidence", "evidence"])
            # Every cluster is present and pre-filled with its own majority label, so a reviewer
            # only has to correct what is wrong.
            self.assertEqual([(row[0], row[3]) for row in rows[1:]],
                             [("0", "AT1"), ("1", "AT2"), ("2", "Macrophage")])

            # A review that leaves the run's own placeholder in place is not a review.
            self.assertEqual(subprocess.call(tool + ["--mapping", str(worksheet)]), 0)
            (project / "config/annotation.yaml").unlink()
            worksheet.write_text(worksheet.read_text().replace("\tMacrophage\t", "\trequires_review\t"))
            self.assertEqual(subprocess.call(tool + ["--mapping", str(worksheet)]), 2)
            self.assertFalse((project / "config/annotation.yaml").exists())
            worksheet.write_text(worksheet.read_text().replace("\trequires_review\t", "\tMacrophage\t"))

            self.assertEqual(subprocess.call(tool + ["--mapping", str(worksheet)]), 0)
            recorded = load_structured(project / "config/annotation.yaml")
            self.assertEqual(recorded["expected_clusters"], ["0", "1", "2"])
            # The runner's own loader is the contract for the file's shape.
            sys.path.insert(0, str(project / "Scripts/Scanpy"))
            try:
                from run_scanpy_notebook import load_annotation_profile  # noqa: E402
                mapping, signature = load_annotation_profile(project, config["annotation"])
            finally:
                sys.path.remove(str(project / "Scripts/Scanpy"))
            self.assertEqual(mapping, {"0": "AT1", "1": "AT2", "2": "Macrophage"})
            self.assertEqual(signature, "signature-review_1")

    def test_scheduler_profiles_must_be_monotonic(self):
        """A floor above its target asks for more than the job will ever request.

        The `dmr` floor once sat below the parallelism its own stage declares, which is the same
        mistake in the other direction: a profile that cannot mean what its author intended.
        """
        with tempfile.TemporaryDirectory() as temp:
            project = self.generate(Path(temp), "rna")
            result = validate(project)
            self.assertEqual(result["status"], "valid")
            self.assertEqual([error for error in result["errors"] if "resource profile" in error], [])

            path = project / "config/scheduler.yaml"
            scheduler = json.loads(path.read_text())
            scheduler["profiles"]["plot"]["floor"]["cpus"] = 32
            scheduler["profiles"]["serial"]["target"]["memory"] = "1G"
            scheduler["profiles"]["summary"]["ceiling"]["memory"] = "junk"
            path.write_text(json.dumps(scheduler))

            errors = validate(project)["errors"]
            self.assertTrue(any("profile plot must satisfy floor <= target <= ceiling for cpus" in error
                                for error in errors), errors)
            self.assertTrue(any("profile serial must satisfy floor <= target <= ceiling for memory" in error
                                for error in errors), errors)
            self.assertTrue(any("profile summary has an unreadable cpus/memory value" in error
                                for error in errors), errors)

    def write_annotation_handoff(self, project: Path, run_id: str, clusters) -> None:
        """Fabricate the handoff task_adapter.publish_annotation leaves behind for a run."""
        result = project / "Results" / "runs" / run_id
        result.mkdir(parents=True)
        lines = ["cell_id\tcell_type\tleiden"]
        for cluster, labels in clusters.items():
            for index, label in enumerate(labels):
                lines.append("S1_C%s_%d\t%s\t%s" % (cluster, index, label, cluster))
        (result / "annotation.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (result / "annotation_status.json").write_text(json.dumps({
            "run_kind": "candidate", "annotation_key": "cell_type",
            "analysis_signature": "signature-%s" % run_id,
        }))
        run_dir = project / ".workflow" / "runs" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "plan.json").write_text(json.dumps({"run_id": run_id, "result_dir": str(result)}))

    def test_shipped_scripts_have_no_undefined_names(self):
        """Both released blockers were a name bound in one scope and used in another.

        `symtable` resolves scopes exactly as the compiler does, so walking it reports that class
        of NameError for every shipped script -- including the ones no test can execute without a
        cluster -- before anything is submitted. It is deliberately not an execution test and not
        an ordering analysis: a name shadowed by a later local assignment, or only declared through
        a `global` statement, is outside what it can see.
        """
        shipped = sorted((ROOT / "assets" / "project-template").rglob("*.py")) \
            + sorted((ROOT / "assets" / "project-template").rglob("*.ipynb")) \
            + sorted((ROOT / "scripts").glob("*.py"))
        self.assertTrue(len(shipped) > 30, "expected the packaged scripts to be discoverable")
        problems = []
        for path in shipped:
            source = notebook_source(path) if path.suffix == ".ipynb" else path.read_text(encoding="utf-8")
            problems.extend("%s: %s" % (path.relative_to(ROOT), item)
                            for item in undefined_names(source, str(path)))
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
