#!/usr/bin/env python3
"""Pure annotation-profile guard used by analysis stages and tests."""


# Shared by preflight and MethSCAn selection/DMR. Compared case-insensitively;
# descriptive biological labels still require explicit review disposition.
PLACEHOLDER_LABELS = frozenset({
    "", "na", "nan", "none", "n/a", "unknown", "unannotated", "unassigned",
    "requires_review", "requires review",
})


def normalize_annotation_table(source, target, cell_column, type_column):
    """Rename configured identity columns without discarding per-row review evidence."""
    import csv
    with source.open(newline='') as handle:
        reader = csv.DictReader(handle, delimiter='\t')
        columns = list(reader.fieldnames or ())
        if cell_column not in columns or type_column not in columns:
            raise ValueError('annotation table lacks configured identity columns')
        fields = ['cell_id', 'cell_type'] + [key for key in columns
            if key not in {cell_column, type_column, 'cell_id', 'cell_type'}]
        with target.open('w', newline='') as sink:
            writer = csv.DictWriter(sink, fieldnames=fields, delimiter='\t', lineterminator='\n')
            writer.writeheader()
            for row in reader:
                record = {key: row.get(key, '') for key in fields}
                record.update(cell_id=row[cell_column], cell_type=row[type_column])
                writer.writerow(record)


def annotation_row_issue(row, type_column='cell_type'):
    """Return a reason an annotated row cannot enter cell-type DMR."""
    label = str(row.get(type_column) or '').strip()
    if label.lower() in PLACEHOLDER_LABELS:
        return 'placeholder_cell_type'
    for flag in ('annotation_requires_review', 'requires_review'):
        if str(row.get(flag) or '').strip().lower() not in {'', '0', 'false', 'no'}:
            return 'unresolved_' + flag
    status = str(row.get('review_status') or '').strip().lower()
    if status and status not in {'approved', 'reviewed', 'user_approved'}:
        return 'unapproved_row_review_status'
    if 'dmr_eligible' in row and str(row['dmr_eligible']).strip().lower() not in {'1', 'true', 'yes'}:
        return 'not_dmr_eligible'
    return None


def evaluate_annotation_profile(observed_clusters, analysis_signature, profile, unassigned="Unassigned"):
    observed = sorted(str(item) for item in observed_clusters)
    template = {
        "analysis_signature": analysis_signature,
        "expected_clusters": observed,
        "annotations": {
            cluster: {"cell_type": unassigned, "confidence": "unreviewed", "evidence": ""}
            for cluster in observed
        },
    }
    status = {"status": "requires_review", "analysis_signature": analysis_signature, "observed_clusters": observed}
    if profile is None:
        status["reason"] = "annotation_profile_absent"
        return {}, status, template
    expected = sorted(str(item) for item in profile.get("expected_clusters", []))
    if profile.get("analysis_signature") != analysis_signature:
        status["reason"] = "analysis_signature_mismatch"
        return {}, status, template
    if expected != observed:
        status["reason"] = "cluster_set_mismatch"
        return {}, status, template
    annotations = {str(key): value for key, value in (profile.get("annotations") or {}).items()}
    if set(annotations) != set(observed) or any(not item.get("cell_type") for item in annotations.values()):
        status["reason"] = "annotation_mapping_incomplete"
        return {}, status, template
    status["status"] = "reviewed"
    return annotations, status, template
