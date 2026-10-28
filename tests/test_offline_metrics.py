from bias.offline_metrics import compute_auc, compute_mrr, compute_ndcg, gini


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
