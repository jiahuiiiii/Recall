"""Clustering metrics for entity resolution. Pure functions, no LLM, no I/O.

Entity resolution is a clustering problem: each real human is a cluster, and every
mention across every memo belongs to exactly one. The system is scored on whether
its clusters match the gold ones -- not on whether it guessed the same ids, which
are arbitrary.

Two metrics, because they fail differently:

- **Pairwise P/R/F1** counts co-reference decisions. It is dominated by large
  clusters: one person mentioned in ten memos contributes 45 pairs, a person
  mentioned once contributes none. Splitting a big cluster looks catastrophic.
- **B-cubed** scores per mention and averages, so every mention counts equally
  regardless of how popular its cluster is. This is the headline number; it is
  the standard for coreference and it does not let one chatty contact dominate.

Report both. A gap between them says something real about *where* the errors are.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations


@dataclass(frozen=True)
class Score:
    precision: float
    recall: float
    f1: float

    def __str__(self) -> str:
        return f"P={self.precision:.3f} R={self.recall:.3f} F1={self.f1:.3f}"


def _f1(precision: float, recall: float) -> float:
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def _pairs(clusters: dict[str, str]) -> set[frozenset[str]]:
    """Every co-reference pair implied by a mention -> cluster assignment."""
    by_cluster: dict[str, list[str]] = {}
    for mention, cluster in clusters.items():
        by_cluster.setdefault(cluster, []).append(mention)
    return {
        frozenset(pair)
        for members in by_cluster.values()
        for pair in combinations(sorted(members), 2)
    }


def pairwise(gold: dict[str, str], pred: dict[str, str]) -> Score:
    """P/R/F1 over co-reference pairs.

    `gold` and `pred` map mention-id -> cluster-id. Cluster ids need not match
    between the two; only the partition matters.
    """
    shared = gold.keys() & pred.keys()
    g = _pairs({m: gold[m] for m in shared})
    p = _pairs({m: pred[m] for m in shared})
    if not g and not p:
        return Score(1.0, 1.0, 1.0)

    tp = len(g & p)
    precision = tp / len(p) if p else 0.0
    recall = tp / len(g) if g else 0.0
    return Score(precision, recall, _f1(precision, recall))


def b_cubed(gold: dict[str, str], pred: dict[str, str]) -> Score:
    """B-cubed P/R/F1 (Bagga & Baldwin).

    For each mention: precision is the fraction of its predicted cluster that is
    genuinely co-referent; recall is the fraction of its gold cluster that was
    recovered. Averaged over mentions, so every mention weighs the same.
    """
    shared = sorted(gold.keys() & pred.keys())
    if not shared:
        return Score(0.0, 0.0, 0.0)

    gold_members: dict[str, set[str]] = {}
    pred_members: dict[str, set[str]] = {}
    for m in shared:
        gold_members.setdefault(gold[m], set()).add(m)
        pred_members.setdefault(pred[m], set()).add(m)

    precisions, recalls = [], []
    for m in shared:
        g = gold_members[gold[m]]
        p = pred_members[pred[m]]
        overlap = len(g & p)
        precisions.append(overlap / len(p))
        recalls.append(overlap / len(g))

    precision = sum(precisions) / len(precisions)
    recall = sum(recalls) / len(recalls)
    return Score(precision, recall, _f1(precision, recall))


def binary(gold: dict[str, bool], pred: dict[str, bool]) -> Score:
    """P/R/F1 for a yes/no call, used for the substantive (passing-mention) filter.

    Positive class is "this belongs in the contact book".
    """
    shared = gold.keys() & pred.keys()
    tp = sum(1 for k in shared if gold[k] and pred[k])
    fp = sum(1 for k in shared if not gold[k] and pred[k])
    fn = sum(1 for k in shared if gold[k] and not pred[k])
    precision = tp / (tp + fp) if tp + fp else (1.0 if not fn else 0.0)
    recall = tp / (tp + fn) if tp + fn else 1.0
    return Score(precision, recall, _f1(precision, recall))


def summarise(runs: list[float]) -> str:
    """mean and spread across repeats.

    Bedrock is not deterministic even at temperature 0, so a single run is not a
    result. Anything reported from one sample can flip on a re-run, which is
    exactly the mistake to avoid in front of judges.
    """
    if not runs:
        return "n/a"
    if len(runs) == 1:
        return f"{runs[0]:.3f} (n=1, UNRELIABLE)"
    mean = sum(runs) / len(runs)
    return f"{mean:.3f} ±{(max(runs) - min(runs)) / 2:.3f} (n={len(runs)}, min={min(runs):.3f} max={max(runs):.3f})"
