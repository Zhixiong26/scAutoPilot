# Methylome software benchmark: performance and output equivalence

Use for comparisons of MethSCAn/reference versus an accelerated release and/or
vmrseq/reference versus an accelerated release. Read [acceleration deployment](acceleration.md)
first. This is a protocol for an explicit custom DAG, not a packaged full-cohort
benchmark runner. Supplied package benchmark claims are not local measurements.

## Freeze what “complete” means

Declare cohort/cell mask, chromosomes, data scale, method versions, model stages,
repetitions, CPU/GPU budgets and output acceptance before running. Distinguish
VMR discovery/matrix generation from optional clustering, annotation or biological
validation. A small-subset pilot does not finish a requested full-cohort benchmark.
An atlas benchmark is not automatically a disease-DMR or FASTQ alignment benchmark.

Use the same cells, chromosome universe, coordinate conversion and input ordering
within each reference/accelerated pair. Different methods may have different
native estimands and required formats; retain their input semantics rather than
forcing one method's features into the other. Enumerate selected raw ALLCs with
adjacent indexes and validate them on compute nodes. Record shared conversion
separately from native software processing.

Verify strand/context and CpG dyad conversion against native raw counts. Do not
use an unvalidated reference-site shortcut. Native vmrseq NA-dropped storage uses
zero for missing and a tiny positive value for unmethylated; a floating tolerance
alone must not equate those states. Retain raw integer counts separately from
binary states and discarded intermediate methylation.

## Version, parameter and resource controls

Pin source releases/commits, installed package hashes, interpreters and dependencies.
Prefer matched dependency environments; retain deployment differences as measured
confounders when matching is not feasible. A verified isolated copy of a pure-Python
reference package can be run with a compatible shared dependency set, with provenance;
do not silently patch its implementation. An unknown acceleration patch-base commit
limits attribution even when versions and outputs are known.

Record explicit arguments and relevant implicit defaults: smoothing/window size,
region thresholds, coverage/cell filters, rounding, weighting, seed, backend and
storage representation. MethSCAn variance fraction is not a P value. Validate
actual CLI defaults/output files rather than assuming documentation matches a build.
Some optimized smooth implementations emit compact NPZ while the reference emits
CSV. Compare their logical values without calling unlike serialized bytes identical.
Additional CSV export changes the timing boundary and must be stated.

Check chromosome grouping semantics. MethSCAn scan can derive a threshold from its
largest chromosome; independently scanning each chromosome changes that population.
For vmrseq, chromosome-by-chromosome fits and one pooled cutoff population are
separate designs. Never silently shard a global estimator to meet memory limits.

Match resource budgets and record actual parallel use. Allocating eight CPUs to a
serial reference is not an eight-thread comparison. Native BiocParallel versus
OpenMP are different implementations; use supported backends without nested
oversubscription, preserve seeds/order, and verify results. CPU-only comparisons
do not imply GPU validation. GPU/device changes require explicit deployment and
same-input correctness evidence.

Inspect scheduler capacity immediately before submission. A timed pair runs on
one allocation, sequentially, with node/CPU model, allocation, effective threads
and competing-load diagnostics recorded. Independent pairs can run concurrently
within memory/I/O limits. Alternating pair order and independent repeats reduce
some order effects, but do not remove shared filesystem cache effects or establish
statistical significance. Do not flush host caches or change system settings.

## Measure the actual stage boundaries

For MethSCAn capture prepare, filter, smooth, scan and matrix when those stages
are in scope. For vmrseq include native poolData if claiming end-to-end from native
cell files, then loading/filtering, smooth, fit and output serialization. A model-only
benchmark using a shared pool is valid if explicitly labelled; do not hide excluded
pooling/conversion costs in an “end-to-end” figure.

Keep wall time, user/system CPU, allocated core-hours, process launch, serialization,
validation/hash overhead and scheduler wait distinguishable. R expression timers
and outer subprocess timers have different boundaries. Sum per-chromosome compute
times only as cumulative work, not parallel makespan. Report repeated observations
and paired time ratios; median paired ratios need not equal the ratio of medians.

Linux wait4/sacct maxima are accounting high-water marks, not necessarily the
simultaneous process-tree footprint. Sampled sums of child RSS may double-count
shared pages and miss short peaks; state sampling/attribution. Reserved memory
and CPU are not measured utilization. Use bounded-memory, storage-aware verification
blocks so a validation bottleneck is not mislabelled software runtime.

## Correctness is separate from execution and hashes

Produce MD5/SHA256 inventories for inputs and stage outputs, plus logical checks.
A file hash addresses byte identity; compressed headers, object metadata and
serialization formats may differ without a scientific difference. Conversely,
a plausible region count or successful exit does not establish equivalence.

Compare these invariants with predeclared rules:

- Cell/site identities, genomic coordinates, order, shape and label alignment.
- Sparse matrix indices and values, finite/NA/NaN/Inf patterns and infinity signs.
- Exact integer/discrete counts and binary/missing state encodings.
- Smoothed site statistics, region boundaries and counts, matrix values, and the
  fit's declared scientific fields (including thresholds/parameters, not just VMRs).
- Floating outputs using explicit absolute/relative tolerance and maximum errors;
  do not byte-compare floating text as if every BED field were discrete.

Treat schema/format changes explicitly and compare aligned scientific content;
report missing fields instead of silently comparing only the intersection. Keep
canonical hashes tied to a documented ordering/encoding if used. A canonical hash
does not replace tolerance checks for approximately equal numerical values.

Maintain three distinct outcomes: native execution status, artifact validity and
reference-equivalence status. A valid but non-equivalent output is a benchmark
result, not an automatic execution failure. Preserve discrepant coordinates,
values and missingness, investigate propagation to final regions/matrices, and
continue independent comparisons within the authorized scope. Do not relax tolerance,
patch a method or discard discordant outputs just to obtain a pass. A malformed
output, failed command or unknown-empty fit still blocks its dependent analysis.

For example, a smoother can differ at chromosome/data boundaries while agreeing
elsewhere; inspect those positions before attributing the difference to roundoff.
Even if final matrices agree on a pilot, do not generalize that observation to the
full cohort or every parameter. Zero-region returns require documented native
semantics and valid completion evidence, not merely a NULL fit or an absent file.

## Storage, downstream claims and delivery

Budget peak working disk, not only compressed source size. Use separate run/repeat
paths, preserve final outputs and discrepant evidence, and remove only explicitly
rebuildable intermediates created by this run after their own checks are recorded.
Keep hashes and a deletion ledger. Do not clean historical inputs/results to make
a benchmark fit; a space/resource limit is reported rather than hidden by subsampling.

Deliver per-stage/per-repeat metrics, full parameters/versions, raw and logical
checksum reports, equivalence failures, retained-output paths, resources and plots.
Between different methods, region counts, lengths, base-pair overlap/Jaccard and
coverage are descriptive comparisons; equality is not expected. Timing ratios
between different algorithms are not patch speedups. Downstream clustering equivalence
requires its own fixed inputs, method, seeds and evidence; it cannot be inferred
from a matching number of VMRs. Use native completion/indexing and separate visual review.
