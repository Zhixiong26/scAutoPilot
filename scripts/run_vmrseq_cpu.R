#!/usr/bin/env Rscript
# Isolated vmrseq CPU analysis of ONE explicitly supplied pooled chromosome.
# Usage: pool_dir output_dir threads seed bp_window max_gap alpha min_cr min_vmr
args <- commandArgs(trailingOnly=TRUE)
if (length(args) != 9L) stop('expected: pool_dir output_dir threads seed bp_window max_gap alpha min_cr min_vmr')
if (getRversion() < '4.5') stop('this accelerated vmrseq release requires R >= 4.5')
if (nzchar(Sys.which('sbatch')) && !nzchar(Sys.getenv('SLURM_JOB_ID'))) stop('use a compute allocation')
if (dir.exists(args[2])) stop('output already exists; use a new directory')
values <- as.numeric(args[3:9])
if (any(!is.finite(values))) stop('parameters must be finite numbers')
threads <- values[1]; seed <- values[2]; bw <- values[3]; gap <- values[4]
alpha <- values[5]; min_cr <- values[6]; min_vmr <- values[7]
ints <- values[c(1,2,3,4,6,7)]
if (any(ints != floor(ints)) || threads < 1 || seed < 0 || bw < 1 || gap < 1 ||
    min_cr < 1 || min_vmr < 1 || alpha <= 0 || alpha >= 1) stop('invalid parameter ranges')
allocation <- Sys.getenv('SLURM_CPUS_PER_TASK')
if (nzchar(allocation) && threads > as.integer(allocation)) stop('threads exceed allocation')
suppressPackageStartupMessages(library(vmrseq))
if (as.character(packageVersion('vmrseq')) != '0.99.5.9000') stop('expected accelerated vmrseq 0.99.5.9000')
Sys.setenv(OMP_NUM_THREADS=threads, OPENBLAS_NUM_THREADS=1, MKL_NUM_THREADS=1)
set.seed(seed)
se <- HDF5Array::loadHDF5SummarizedExperiment(args[1])
if (length(unique(as.character(GenomicRanges::seqnames(se)))) != 1L) stop('supply one chromosome per CPU invocation')
total <- DelayedArray::rowSums(SummarizedExperiment::assays(se)[[1]] > 0)
se <- se[total >= 3, ]
if (!nrow(se)) stop('no sites with >= 3 covered cells')
# Native OpenMP kernels get the thread budget; avoid nested worker pools.
param <- BiocParallel::SerialParam()
gr <- vmrseq::vmrseqSmooth(se, bpWindow=bw, BPPARAM=param)
fit <- vmrseq::vmrseqFit(gr, alpha=alpha, maxGap=gap, minNumCR=min_cr,
                        minNumVMR=min_vmr, BPPARAM=param)
dir.create(args[2], recursive=TRUE)
saveRDS(fit, file.path(args[2], 'vmrseq_fit.rds'))
write.table(as.data.frame(fit$vmr.ranges), file.path(args[2], 'vmr_genomic.tsv'),
            sep='\t', quote=FALSE, row.names=FALSE)
writeLines(capture.output(sessionInfo()), file.path(args[2], 'sessionInfo.txt'))
writeLines(capture.output(dput(list(arguments=args, coordinate_system='1-based closed',
                                  covered_cells_per_site=3L))), file.path(args[2], 'parameters.R'))
