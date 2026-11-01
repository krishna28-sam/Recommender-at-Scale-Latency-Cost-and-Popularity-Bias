# Data card

## Primary data: MIND-small

The primary data used for all reported offline metrics, model tables, and streaming benchmarks is real MIND-small obtained from the official Microsoft Research Azure Blob distribution endpoint with Hugging Face mirror fallback (`Recommenders/MIND`), governed under the Microsoft Research License Terms of Use.
It is stored locally under `data/raw/MINDsmall_train` and `data/raw/MINDsmall_dev`. Raw data files are strictly local and are never committed or distributed.

### Dataset Verification and File Checksums
- **Source**: Microsoft News Dataset (MIND-small) via Microsoft Research Azure Blob / Hugging Face mirror
- **License**: Microsoft Research License Terms (research and non-commercial use)
- **Download / Staging Date**: 2026-10-29
- **Archive Checksums** (recorded in `data/raw/mind_small.sha256`):
  - `data/raw/_dl/MINDsmall_train.zip`: `6ef97a271580b98ccfc4301ada55cc639423cb0576a78b8dcfcf74a4dbcc3194`
  - `data/raw/_dl/MINDsmall_dev.zip`: `d6ce515dcaa6b6d47ddf0a326eebc8a31b84735ae410285c9882ca2a06eec669`
- **Extracted Raw TSV Checksums**:
  - `data/raw/MINDsmall_train/news.tsv`: `cd49d7da275e9c405f627d75a0de9d4ec6ad43ff8a8db5d23a447591676e09d6` (51,282 news items)
  - `data/raw/MINDsmall_train/behaviors.tsv`: `a424547c8fa17c9ea4879c2110221c2b2f2709f4f7615ede0b0d8e4765158658` (156,965 impressions)
  - `data/raw/MINDsmall_dev/news.tsv`: `e5d144667558c449d16084fe6bfa01940c2f5d5785ea9f9110292bc3b94eb822` (42,416 news items)
  - `data/raw/MINDsmall_dev/behaviors.tsv`: `b6c460e33b1a8693252ded6e626da7d3ccf78920eea2ec11889020bb7d8443ef` (73,152 impressions)

### Data Hygiene and Integrity
- **No MovieLens or Synthetic Data in Reported Numbers**: All reported offline numbers in `data/processed/bias_summary.csv` / `json` and all 42 prediction files in `data/outputs/dev_predictions` evaluate model predictions strictly over the real MIND-small dataset.
- **Publishers**: MIND has no publisher field. Publisher mappings in this project (`random_101..303`, `category_404..606`) are synthetic controlled groups for exposure analysis over the union of 65,234 unique news items; exposure share is not itself evidence of real-world publisher unfairness.
- **Privacy**: Raw user IDs are never logged or exported; streaming replay hashes user IDs with SHA-256 and an environment salt (`MIND_USER_HASH_SALT`).

## Fallback: MovieLens-25M Derived Data

MovieLens 25M was prepared solely as an offline fallback when direct Azure Blob endpoints intermittently returned HTTP 409.
Outputs from the fallback pipeline reside in `data/processed_movielens/` and `data/outputs_movielens/` and **must never be reported as MIND results**.

- **Citation**: F. Maxwell Harper and Joseph A. Konstan. 2015. The MovieLens Datasets: History and Context. *ACM Transactions on Interactive Intelligent Systems* (TiiS) 5, 4, Article 19 (December 2015), 19 pages. DOI: https://doi.org/10.1145/2827872
- **Archive Checksum**: `data/raw/ml-25m.zip` (SHA-256: `91ae79848e42ff39f6daf4837544259b36283db8525e646fb8cfad4505359fc4`)
- **Conversion Details**: Samples 10,000 users with fixed seed `20261028`, splits train/dev at the 80th percentile timestamp of positive ratings (`rating >= 4.0`), generating impressions with 1 positive and 19 uniformly sampled unrated negative movies (CTR = 0.05 by construction).
- **Redistribution Restriction**: `data/raw/` is excluded from git tracking and must never be shared publicly.

The recommender smoothing constant is `alpha=10.0`, matching `config/model.yaml` and `docs/spec.md`.
