"""The metrics decide whether the project's headline claim is true.

They are pure arithmetic and get tested against cases with known answers, so a
number in the benchmark table is never the first time the code has been checked.
"""

from __future__ import annotations

import pytest

from eval.metrics import b_cubed, binary, pairwise, summarise

# Three memos mentioning the same two people. Mentions are "memo:name".
GOLD = {
    "m1:Wei Lin": "wei", "m2:Wei Lin": "wei", "m3:the GIC one": "wei",
    "m1:Arjun": "arjun", "m2:Arjun Menon": "arjun",
}


def test_perfect_clustering_scores_one():
    assert pairwise(GOLD, dict(GOLD)).f1 == 1.0
    assert b_cubed(GOLD, dict(GOLD)).f1 == 1.0


def test_cluster_ids_are_arbitrary():
    """Only the partition matters. Renaming every cluster changes nothing."""
    renamed = {m: "X" if c == "wei" else "Y" for m, c in GOLD.items()}
    assert b_cubed(GOLD, renamed).f1 == 1.0
    assert pairwise(GOLD, renamed).f1 == 1.0


def test_a_missed_match_splits_a_cluster():
    """The system failed to recognise 'the GIC one' as Wei Lin -- the exact
    failure the person graph exists to prevent."""
    pred = dict(GOLD) | {"m3:the GIC one": "new_person"}

    pw = pairwise(GOLD, pred)
    b3 = b_cubed(GOLD, pred)
    # Wei's 3 gold pairs drop to 1; nothing spurious is asserted.
    assert pw.precision == 1.0
    assert pw.recall == pytest.approx(1 / 2)
    assert b3.precision == 1.0
    assert b3.recall < 1.0


def test_a_wrong_merge_is_punished_on_precision():
    """Two different people collapsed into one. Worse than a split: it silently
    destroys a real record."""
    pred = {m: "everyone" for m in GOLD}
    pw = pairwise(GOLD, pred)

    assert pw.recall == 1.0
    assert pw.precision < 1.0


def test_b_cubed_is_not_dominated_by_the_largest_cluster():
    """Pairwise counts pairs, so a 5-mention cluster outweighs five singletons
    45-to-0. B-cubed weighs every mention equally -- which is why it is the
    headline number."""
    gold = {f"big{i}": "big" for i in range(5)} | {f"solo{i}": f"s{i}" for i in range(5)}
    # Shatter the big cluster; leave the singletons correct.
    pred = {f"big{i}": f"b{i}" for i in range(5)} | {f"solo{i}": f"s{i}" for i in range(5)}

    # Pairwise: all 10 of the big cluster's pairs are lost, singletons contribute
    # none, so recall reads as total failure.
    assert pairwise(gold, pred).recall == 0.0
    # B-cubed: each of the 5 shattered mentions recovers 1/5 of its gold cluster,
    # each singleton recovers all of its own -> (5*0.2 + 5*1.0)/10.
    assert b_cubed(gold, pred).recall == pytest.approx(0.6)


def test_metrics_only_score_mentions_present_in_both():
    pred = {"m1:Wei Lin": "wei"}
    assert b_cubed(GOLD, pred).f1 == 1.0


def test_binary_scores_the_substantive_filter():
    gold = {"wei": True, "arjun": True, "daniel": False}
    pred = {"wei": True, "arjun": True, "daniel": True}   # kept a passing mention

    s = binary(gold, pred)
    assert s.recall == 1.0
    assert s.precision == pytest.approx(2 / 3)


def test_summarise_flags_a_single_run_as_unreliable():
    """Bedrock is not deterministic at temperature 0. One sample is not a result."""
    assert "UNRELIABLE" in summarise([0.9])
    out = summarise([0.8, 0.9, 1.0])
    assert "0.900" in out and "n=3" in out
