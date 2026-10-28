# Data card

## MovieLens-derived fallback

The official MIND-small download was unavailable on 2026-10-28 because the
official host returned HTTP 409. This project does not use an unofficial MIND
mirror. When `ratings.csv` and `movies.csv` from MovieLens 25M are supplied
under `DATA_ROOT/ml-25m`, `scripts/movielens_to_mind.py` creates MIND-format
files under `data/raw/MINDsmall_train` and `data/raw/MINDsmall_dev`.

The converter samples 10,000 users with a fixed seed. It computes one global
timestamp cutoff at the 80th percentile of positive ratings (`rating >= 4`)
among those users. Ratings before the cutoff form train; ratings on or after
the cutoff form dev. Each user contributes at most 20 train impressions and 10 dev
impressions, selected with the fixed seed. A positive rating is `rating >= 4.0`.
Each synthetic impression contains exactly 1 positive and 19 uniformly sampled
negative movies the user has not rated, so the constructed candidate-level CTR
is 0.05 by construction. These uniform negatives favour popularity-based
scorers and are not equivalent to real recommendation candidates. Histories
contain only previous positive events. Impressions are synthetic by design and
must not be reported as MIND results. The train-known set consists of all
items that are positives in train impressions or appear in any train history
entry; dev cold-start metrics are computed against that set.

This derived data is for pipeline testing only. Its metrics must not be
reported as MIND results. MovieLens source terms/licensing must be reviewed
before use or redistribution. User IDs are syntheticized in the derived MIND
files as `U<id>` and must be hashed before streaming.
