# Supplied acceleration backends

Use these adapters when the user supplies the accelerated Bismark, MethSCAn or
vmrseq releases. The software is external to the portable skill: never bundle
binaries, environments, genome indexes, local registries or study data in it.
The package versions below describe the inspected supplied releases, not upstream
compatibility promises. Package benchmark numbers are not local measurements.

| Backend | Integration | Requirements / boundary |
|---|---|---|
| Bismark `1.2-a800` | Explicit `prepare`, `align`, `selftest`, `info` through `run_accelerated.py` | CPU requires x86-64 AVX2/BMI2. Bundled GPU binary targets sm_80, requires glibc >=2.34 and driver >=R525. Use a compatible allocated GPU and inspect actual device selection. |
| MethSCAn `1.1.0+opt5` | Existing DAG with an explicit `methscan` environment row; standalone CPU/GPU adapter | Isolated Python 3.9–3.11; CPU is native default. CuPy 13 with matching CUDA 11/12 for GPU. Do not change the standard bootstrap environment globally. |
| vmrseq `0.99.5.9000` CPU | `run_vmrseq_cpu.R` on one pooled chromosome | R >=4.5, DESCRIPTION dependencies, OpenMP C compiler; separate VMR method, not a MethSCAn drop-in. |
| vmrseq GPU runtime | `pipeline_gpu.py` via `run_accelerated.py` | CUDA PyTorch, NumPy, h5py, gcc/OpenMP, R + accelerated vmrseq. Require explicit chromosomes and matching input representation. |

## Stage and verify

Find the actual source directory before using it. Unicode format characters can
make visually identical directory names different; inspect with `repr(path)`.
Always quote shell paths. Use Python >=3.9 for the helpers.

```bash
python scripts/bootstrap_acceleration.py stage \
  --source /path/to/supplied-archives --destination /path/to/software/release-0.15.0
python scripts/bootstrap_acceleration.py verify \
  --registry /path/to/software/release-0.15.0/acceleration.json
```

`stage` requires a fresh destination, rejects links/traversal in tar archives,
and records archive and extracted-file SHA-256 values. It stages all three
packages without executing them. A failed staging directory is retained for
inspection; retry in a fresh directory. Registry verification detects changed
packaged files, but is not a signature/authenticity claim or validation of an
installed Python/R environment. JIT caches and generated indexes are not release
files and should not be added to the release inventory.

Generated projects receive these tools under `tools/`; replace `scripts/` with
`tools/` in the examples. They do not depend on an installed skill afterwards.

## MethSCAn installation and existing DAG

```bash
python scripts/bootstrap_acceleration.py install-methscan \
  --registry /path/to/software/release-0.15.0/acceleration.json \
  --python /path/to/python3.11 --prefix /path/to/new/methscan-opt5
# Add --execute to create the isolated venv and install the wheel.
# Add --cuda 11 or --cuda 12 only for a matching GPU deployment.
```

The venv uses copied interpreters so project path resolution cannot follow a
Python symlink back into the base environment. The installer refuses every
existing target prefix, runs `pip check` and
`methscan --version`, and saves the package freeze and provenance/environment
row in the new prefix. The native `--version` reports only `1.1.0`; use the
recorded importlib metadata command to distinguish `1.1.0+opt5`. Network access may be needed for wheel dependencies.
The installer uses binary dependency wheels only, avoiding unplanned source
builds on older cluster systems; absence of a compatible wheel fails clearly.
`install.log` retains resolver/download evidence. Standard pip index/cache
environment settings can select the site package mirror.
It never upgrades an existing shared environment. Preserve the resulting prefix
as immutable while plans use it.

For a **new or idle** project's intake, use the paths printed by the installer:

```yaml
environments:
  # Keep all other environment rows required by the selected routes.
  - stage: methscan
    python: /path/to/new/methscan-opt5/bin/python
    executable: /path/to/new/methscan-opt5/bin/methscan
    version_command: >-
      /path/to/new/methscan-opt5/bin/python -c "from importlib.metadata import version; print('MethSCAn ' + version('methscan'))"
    required: true
```

For an existing idle project, replace only its `methscan` row in
`config/environments.tsv`, retain the five-column schema, revalidate and create a
new plan. Do not modify running projects, frozen executors or old plan identity.
The native optimized CLI defaults to CPU and retains prepare/filter/smooth/scan/
diff/matrix stages. Run a small same-input comparison before production; record
scientific parameters, cell/site order, region boundaries, count matrices and
numerical differences. Installation success does not establish equivalence.

GPU is an explicit standalone invocation in this release:

```bash
python scripts/run_accelerated.py --registry /path/to/release/acceleration.json \
  --tool methscan --python /path/to/methscan-opt5/bin/python --device gpu \
  --execute --evidence /path/to/new/smooth-command.json -- \
  smooth /path/to/prepared --bandwidth 1000
```

The adapter adds `--device` only to smooth/scan/diff and adds `--write-csv` to GPU
smooth for consumers expecting the standard CSV artifacts. Matrix remains the
native CPU command. The supplied CLI has no `--n-gpus` option despite the install
note mentioning one; do not invent it. The merged `gpu-pipeline` is not used by
the DAG: it combines stage outputs and cannot satisfy existing task boundaries
without a separate implementation. GPU allocation and per-pair concurrency must
be explicit; changing the environment executable alone does not allocate a GPU.

## Bismark

```bash
python scripts/run_accelerated.py --registry /path/to/release/acceleration.json \
  --tool bismark --execute --evidence /path/to/new/align-command.json -- \
  align --device cpu --threads 4 --genome /path/to/prepared-genome \
  --pbat -1 /path/to/cell_R1.fastq.gz -2 /path/to/cell_R2.fastq.gz \
  -o /path/to/new/output
```

The adapter prepends its Python interpreter directory to PATH for the bundled
Bowtie2 launcher; use `--python /path/to/python3` before `--` to override it.
Use explicit library mode from the sample protocol; do not infer PBAT from file
names. `--device auto` can fall back to CPU; retain tool logs identifying the
actual backend. The supplied A800 package does not include an sm_90 executable.
Bismark acceleration is not byte-identical to reference Bismark; its README
reports alignment/calling differences and small nondeterministic PE GPU ties.
Evaluate those differences on a representative subset before scientific use.

`prepare` writes indexes. Use a project-owned genome staging directory for a bare
FASTA; never run it on read-only shared references. `--index-dir` relocates the
acceleration index but does not relocate a missing Bismark `Bisulfite_Genome`.
Budget disk/RAM and CPU threads before preparing a full genome. With this
release, bare-FASTA preparation needs `--threads 4` or more: the wrapper passes
`threads / 2` to Bismark `--parallel`, which rejects 1. Reserve at least four
CPUs for that operation; existing prepared Bismark indexes avoid this step. `selftest` creates a temporary genome and output directory; GPU probing can
write package-local probe caches. Run on a writable staged copy in a compute
allocation.

The accelerated five-column `.bedGraph` (`chr pos methylated unmethylated %`) is
**not** ALLC or the six-column Bismark coverage accepted by current conversion
stages. There is no automated FASTQ/BAM-to-indexed-ALLC handoff here. Preserve
strand/context and coordinate evidence when implementing one later; do not
rename or mechanically pass these outputs to the ALLC discovery route.

## vmrseq

Install the supplied source into a **new isolated R library** with an R >=4.5
installation that already provides DESCRIPTION dependencies:

```bash
mkdir /path/to/new/vmrseq-library
/path/to/R/bin/R CMD INSTALL --library=/path/to/new/vmrseq-library \
  /path/to/release/packages/vmrseq_0.99.5.9000.tar.gz
R_LIBS_USER=/path/to/new/vmrseq-library /path/to/R/bin/Rscript --vanilla \
  -e 'library(vmrseq); stopifnot(packageVersion("vmrseq") == "0.99.5.9000"); sessionInfo()'
```

For Conda R, prepend its `bin` directory to PATH so Makeconf finds its compiler.
Do not replace a shared R package. Missing R/Bioconductor dependencies must be
resolved in an isolated environment before claiming readiness.

CPU analysis of an already pooled chromosome:

```bash
python scripts/run_accelerated.py --registry /path/to/release/acceleration.json \
  --tool vmrseq-cpu --rscript /path/to/Rscript --r-library /path/to/vmrseq-library \
  --execute --evidence /path/to/new/cpu-command.json -- \
  /path/to/pool/chr1 /path/to/new/chr1-output 4 1 2000 2000 0.05 5 5
```

Trailing arguments are pool directory, new output directory, threads, seed,
window, max gap, alpha, minimum CR sites, minimum VMR sites. The adapter retains
sites covered in >=3 cells, sets a serial BiocParallel backend with native OpenMP
threads to avoid nested worker pools, and exports the fit RDS, genomic TSV,
parameters and R session. TSV coordinates are 1-based closed, not BED. A zero-VMR
fit exports a header-only table; a failed fit is not a valid zero-VMR result.

GPU analysis of existing pooled HDF5:

```bash
python scripts/run_accelerated.py --registry /path/to/release/acceleration.json \
  --tool vmrseq-gpu --python /path/to/torch-python --rscript /path/to/Rscript \
  --r-library /path/to/vmrseq-library --execute \
  --evidence /path/to/new/gpu-command.json -- \
  /path/to/pool /path/to/new/output --chrs chr1 --readers 4 --seed 1
```

Read the supplied runtime `README.txt` and `pipeline_gpu.py` before using shards,
shared cutoff tables or segmentation; these change the comparison unit. Keep
chromosome grouping, seed and cutoff scope fixed when comparing CPU/GPU. The
adapter passes native arguments and does not claim equivalence for changed
cutoff populations or chromosome grouping.

`poolData` expects `chr,pos,strand,meth_read,total_read`, removes intermediate
methylation, and pools binary values; ALLC has a different column order and must
be converted explicitly. NA-dropped HDF5 uses zero for missing and a tiny positive
value for unmethylated, not conventional zero methylation. Do not feed ordinary
count/fraction matrices directly. No automatic ALLC converter is supplied.

## Execution and evidence

`run_accelerated.py` prints a JSON command plan by default and runs only with
`--execute`. It refuses numerical execution on a Slurm submit host. Reserve
CPU/memory/GPU before use and keep requested threads/readers within allocation.
Use new output directories and capture stdout/stderr in scheduler logs.
`--evidence` records command and exit status; it is **not** scientific output
validation or DAG completion evidence. Validate native outputs and register
verified artifacts in the project's result index. Bismark/vmrseq are standalone
adapters; production DAG integration requires explicit custom tasks with the
existing output/completion contract. No default DAG routes or sample identities
are added by installing this skill.
