"""Similarity and difference measures, in the standard library only.

The control plane adjudicates fingerprints here, and fingerprints are extracted
on a compute node that has scanpy installed while this process may not. So the
measures that decide whether a refactor changed behaviour, and whether two
scientific candidates are alike, are reimplemented rather than imported.

Two of them are worth a note.

`canonical_labels` is a *canonical form* rather than a best-matching search.
Section 13.1 asks for best label matching before comparing cluster assignments,
because `0 0 1 1 2` and `2 2 0 0 1` are the same partition. Renumbering labels
by order of first appearance reaches the same conclusion without solving an
assignment problem -- and unlike best matching it is unambiguous. When several
matchings tie on agreement there is no principled way to choose between them, so
the comparison would inherit that ambiguity. The canonical form has none: two
label vectors have equal canonical forms exactly when they describe the same
partition, provided the cell order is the same on both sides. That proviso is
why identity comparison runs first and is exact.

`pairwise_distance_correlation` deliberately takes sampled points. A full
distance matrix over every cell is neither affordable in pure Python nor
necessary: sections 7.4 and 13.3 both require a fixed sampling protocol, and
comparing two runs sampled differently would be comparing the sampling.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple


def canonical_labels(labels: Sequence[object]) -> Tuple[int, ...]:
    """Renumber labels by order of first appearance.

    `['b', 'b', 'a', 'a', 'c']` and `['a', 'a', 'c', 'c', 'b']` both become
    `(0, 0, 1, 1, 2)`. Cell order must already be known equal; this function
    cannot see a reordered input and will not detect one.
    """
    mapping: Dict[object, int] = {}
    out: List[int] = []
    for label in labels:
        if label not in mapping:
            mapping[label] = len(mapping)
        out.append(mapping[label])
    return tuple(out)


def labels_identical(left: Sequence[object], right: Sequence[object]) -> bool:
    """Exact partition equality, order-preserving and label-renumbering-invariant."""
    if len(left) != len(right):
        return False
    return canonical_labels(left) == canonical_labels(right)


def adjusted_rand_index(left: Sequence[object], right: Sequence[object]) -> float:
    """Agreement between two partitions, corrected for chance (section 13.2).

    Note this is a *stability* measure, not an equivalence one: an ARI of 0.99
    still means some cells changed cluster, so it can never establish that a
    refactor left behaviour unchanged.
    """
    if len(left) != len(right):
        raise ValueError("adjusted_rand_index: partitions differ in length")
    n = len(left)
    if n == 0:
        return 1.0
    contingency: Dict[Tuple[object, object], int] = {}
    a_counts: Dict[object, int] = {}
    b_counts: Dict[object, int] = {}
    for a, b in zip(left, right):
        contingency[(a, b)] = contingency.get((a, b), 0) + 1
        a_counts[a] = a_counts.get(a, 0) + 1
        b_counts[b] = b_counts.get(b, 0) + 1
    if len(a_counts) == 1 and len(b_counts) == 1:
        return 1.0
    sum_cells = sum(_comb2(v) for v in contingency.values())
    sum_a = sum(_comb2(v) for v in a_counts.values())
    sum_b = sum(_comb2(v) for v in b_counts.values())
    total = _comb2(n)
    expected = (sum_a * sum_b) / total
    maximum = 0.5 * (sum_a + sum_b)
    if maximum == expected:
        return 1.0 if sum_cells == expected else 0.0
    return (sum_cells - expected) / (maximum - expected)


def _comb2(value: int) -> float:
    return value * (value - 1) / 2.0


def jaccard(left: Iterable[object], right: Iterable[object]) -> float:
    """Set overlap. Empty on both sides counts as identical, not undefined."""
    a, b = set(left), set(right)
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 1.0


def _average_ranks(values: Sequence[float]) -> List[float]:
    """Ranks with ties averaged, so Spearman stays defined under ties."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        end = index
        while end + 1 < len(order) and values[order[end + 1]] == values[order[index]]:
            end += 1
        average = (index + end) / 2.0 + 1.0
        for position in range(index, end + 1):
            ranks[order[position]] = average
        index = end + 1
    return ranks


def spearman(left: Sequence[float], right: Sequence[float]) -> float:
    """Rank correlation. Returns 1.0 when either side is constant.

    A constant side carries no ranking information; returning 1.0 for "both
    flat" keeps a degenerate but identical comparison from reading as failure,
    and the tie handling above keeps a partially tied ranking honest.
    """
    if len(left) != len(right):
        raise ValueError("spearman: sequences differ in length")
    if len(left) < 2:
        return 1.0
    a, b = _average_ranks(left), _average_ranks(right)
    mean_a = sum(a) / len(a)
    mean_b = sum(b) / len(b)
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    var_a = sum((x - mean_a) ** 2 for x in a)
    var_b = sum((y - mean_b) ** 2 for y in b)
    if var_a == 0 or var_b == 0:
        return 1.0
    return cov / math.sqrt(var_a * var_b)


def allclose(
    left: Sequence[float],
    right: Sequence[float],
    rtol: float,
    atol: float,
) -> Tuple[bool, float, float]:
    """Element-wise closeness, reporting the worst deviation seen.

    The deviations are returned even on success: a run that passes at 0.9 of its
    tolerance is a different risk from one that passes at 0.01, and a drift
    reported early is worth more than one discovered after it crosses.
    """
    if len(left) != len(right):
        raise ValueError("allclose: sequences differ in length")
    worst_abs = 0.0
    worst_rel = 0.0
    for a, b in zip(left, right):
        delta = abs(a - b)
        worst_abs = max(worst_abs, delta)
        denominator = abs(b) if b else 1.0
        worst_rel = max(worst_rel, delta / denominator)
    ok = all(abs(a - b) <= atol + rtol * abs(b) for a, b in zip(left, right))
    return ok, worst_abs, worst_rel


def pairwise_distance_correlation(
    left: Sequence[Sequence[float]],
    right: Sequence[Sequence[float]],
) -> float:
    """Correlate the two point clouds' pairwise distances (section 13.2).

    Rotations, reflections and translations leave the answer at 1.0, which is
    what makes it usable for embeddings: PCA and scVI latent spaces are only
    defined up to such transforms, so a coordinate-wise comparison would report
    a difference where no geometric difference exists.
    """
    if len(left) != len(right):
        raise ValueError("pairwise_distance_correlation: point counts differ")
    if len(left) < 3:
        return 1.0
    distances_a: List[float] = []
    distances_b: List[float] = []
    for i in range(len(left)):
        for j in range(i + 1, len(left)):
            distances_a.append(_euclidean(left[i], left[j]))
            distances_b.append(_euclidean(right[i], right[j]))
    if not distances_a:
        return 1.0
    return _pearson(distances_a, distances_b)


def _euclidean(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError("_euclidean: points differ in dimension")
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _pearson(left: Sequence[float], right: Sequence[float]) -> float:
    mean_a = sum(left) / len(left)
    mean_b = sum(right) / len(right)
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(left, right))
    var_a = sum((x - mean_a) ** 2 for x in left)
    var_b = sum((y - mean_b) ** 2 for y in right)
    if var_a == 0 or var_b == 0:
        # Both clouds collapsed to a point: geometrically identical, and there
        # is no direction in which they could disagree.
        return 1.0
    return cov / math.sqrt(var_a * var_b)


def edge_overlap(left: Iterable[Tuple[object, object]], right: Iterable[Tuple[object, object]]) -> float:
    """Jaccard over undirected edges, so (a, b) and (b, a) are one edge."""
    normalised_a = {tuple(sorted((str(u), str(v)))) for u, v in left}
    normalised_b = {tuple(sorted((str(u), str(v)))) for u, v in right}
    return jaccard(normalised_a, normalised_b)


def set_equality(left: Iterable[object], right: Iterable[object]) -> bool:
    return set(left) == set(right)


def sequence_equality(left: Sequence[object], right: Sequence[object]) -> bool:
    if len(left) != len(right):
        return False
    return all(a == b for a, b in zip(left, right))
