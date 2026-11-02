# Official scDblFinder on one independent capture's full-gene raw counts.
args <- commandArgs(TRUE)
stopifnot(length(args) == 5L)
work <- args[1]
seed <- as.integer(args[2])
suppressPackageStartupMessages(library(Matrix))
suppressPackageStartupMessages(library(SingleCellExperiment))
suppressPackageStartupMessages(library(scDblFinder))
suppressPackageStartupMessages(library(BiocParallel))
counts <- as(readMM(file.path(work, "counts.mtx")), "CsparseMatrix")
cells <- readLines(file.path(work, "cells.tsv"), encoding="UTF-8")
stopifnot(ncol(counts) == length(cells), !anyDuplicated(cells),
          all(is.finite(counts@x)), all(counts@x >= 0),
          all(counts@x == round(counts@x)))
colnames(counts) <- cells
rownames(counts) <- paste0("gene_", seq_len(nrow(counts)))
sce <- SingleCellExperiment(list(counts=counts))
settings <- list(sce=sce, clusters=identical(args[5], "TRUE"), BPPARAM=SerialParam())
if (args[3] != "auto") settings$dbr <- as.numeric(args[3])
if (args[4] != "auto") settings$dbr.per1k <- as.numeric(args[4])
set.seed(seed)
fit <- do.call(scDblFinder, settings)
stopifnot(identical(colnames(fit), cells), all(is.finite(fit$scDblFinder.score)),
          all(fit$scDblFinder.class %in% c("singlet", "doublet")))
write.table(data.frame(cell_id=cells, scDblFinder.score=fit$scDblFinder.score,
                       scDblFinder.class=fit$scDblFinder.class),
            file.path(work, "calls.tsv"), sep="\t", quote=FALSE, row.names=FALSE)
saveRDS(list(metadata=metadata(fit), seed=seed, dbr=args[3], dbr_per1k=args[4],
             clusters=settings$clusters, formals=formals(scDblFinder), session=sessionInfo()),
        file.path(work, "metadata.rds"))
writeLines(capture.output(sessionInfo()), file.path(work, "R_session.txt"))
write.table(data.frame(version=as.character(packageVersion("scDblFinder")), seed=seed,
                       dbr=args[3], dbr_per1k=args[4], clusters=settings$clusters),
            file.path(work, "parameters.tsv"), sep="\t", quote=FALSE, row.names=FALSE)
