import math

from bias.offline_metrics import (
    compute_auc,
    compute_exposure_l1,
    compute_mrr,
    compute_ndcg,
    compute_served_ndcg,
    gini,
    load_train_known,
)


def test_small_fixture_metrics_and_gini():
    # Hand-computed fixture for 4 candidates ranked by score:
    # scores = [0.9, 0.7, 0.5, 0.1]
    # labels = [0, 1, 0, 0]
    # AUC = 2/3 = 0.6666666666666666
    # MRR = 1/2 = 0.5
    # nDCG@10 = 1 / log2(3) = 0.6309297535714575
    # Gini([1,1,1,1]) = 0.0
    # Gini([4,0,0,0]) = 0.75
    labels = [0, 1, 0, 0]
    assert abs(compute_auc(labels) - 0.6666666666666666) < 1e-9
    assert abs(compute_mrr(labels) - 0.5) < 1e-9
    assert abs(compute_ndcg(labels, 10) - 0.6309297535714575) < 1e-9
    assert abs(gini([1, 1, 1, 1]) - 0.0) < 1e-9
    assert abs(gini([4, 0, 0, 0]) - 0.75) < 1e-9


def test_served_exposure_metrics_hand_computed():
    labels = [0, 1, 0]
    assert abs(compute_ndcg(labels, 5) - 1.0 / math.log2(3)) < 1e-9
    assert abs(compute_exposure_l1({"a": 1.0, "b": 0.5}, {"a": 0.5, "b": 0.5})
               - (2.0 / 3.0 - 0.5) * 2) < 1e-9


def test_served_ndcg_uses_full_impression_ideal_with_two_positives():
    labels = [1, 0, 1, 0]
    served_labels = [1, 0]
    ideal_dcg = 1.0 + 1.0 / math.log2(3)
    expected = 1.0 / ideal_dcg
    assert abs(compute_served_ndcg(labels, served_labels, 5) - expected) < 1e-9


def test_served_ndcg_equals_full_ndcg_at_lambda_zero_fixture():
    labels = [1, 0, 1, 0]
    assert abs(compute_served_ndcg(labels, labels, 5) - compute_ndcg(labels, 5)) < 1e-9


def test_cold_items_are_defined_by_train_behaviors(tmp_path):
    train = tmp_path / "train.tsv"
    train.write_text(
        "1\tU1\t2020-01-01\tNseen\tNseen-1 Ntrain-0\n"
        "2\tU2\t2020-01-02\tNhistory\tNother-1\n"
    )
    assert load_train_known(train) == {"Nseen", "Nhistory", "Nother"}
