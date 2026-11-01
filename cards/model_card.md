# Model Card: Streaming Fair News Recommender

## 1. Model Details & Architecture

- **Architecture**: Two-stage recommender consisting of:
  1. **Base Scorer (`recsys/scorer.py`)**: Deterministic point-wise candidate scoring combining Laplace-smoothed item Click-Through Rate (CTR, $\alpha=10.0$) and user historical category affinity:
     $$\text{score}(u, i) = \frac{\text{clicks}_i + \alpha \cdot \text{global\_ctr}}{\text{impressions}_i + \alpha} + \beta \cdot \text{affinity}(u, \text{category}_i)$$
  2. **Fair Re-Ranker (`recsys/reranker.py`)**: Greedy sequential selector serving top-$k$ ($k=5$) items that optimizes a trade-off between relevance and cumulative publisher exposure fairness:
     $$i^* = \arg\max_{i \in \mathcal{C}} \left[ \text{score}(u, i) - \lambda \cdot \max(0, \text{curr\_share}(g_i) - \text{target\_share}(g_i)) \right]$$
     Carries an exponentially discounted running exposure accumulator across impression sessions.
- **Engines**: Identical scoring and re-ranking logic implemented in:
  - Apache Spark Structured Streaming (`spark/pass_through.py`)
  - Apache Flink PyFlink DataStream API (`flink/pass_through.py`)
- **Version**: 1.0 (Course Benchmark Release, 2 Nov 2026)

## 2. Intended Use

- **Primary Use**: Comparative benchmarking of stream processing engines (Spark vs. Flink) under varying throughput loads, quantifying end-to-end latency, resource saturation, and runtime overhead of real-time fairness re-ranking.
- **Secondary Use**: Controlled study of popularity bias and publisher representation trade-offs in news recommendation.
- **Out of Scope**: Not intended for production commercial news recommendation without online feedback loops, rolling CTR updates, or authenticated user sessions.

## 3. Data & Training Setup

- **Dataset**: Microsoft News Dataset (MIND-small) train split (156,965 behaviors, 51,282 news articles) and dev split (73,152 behaviors, 42,416 news articles).
- **Publisher Mappings**: MIND contains no native publisher attributes. Six synthetic mappings (3 uniform random: `random_101..303`; 3 category-correlated: `category_404..606`) across 65,234 unique news articles partition items into 10 publisher groups.
- **Target Distribution**: Target publisher shares equal the empirical candidate impression share in the training split.

## 4. Limitations & Engineering Tradeoffs

- **Static Item Statistics**: Candidate click and impression counts are precomputed from the training period. In real-world news systems, popularity evolves rapidly within hours; rolling streaming counters remain future work.
- **Engine State Architecture**:
  - In Spark Structured Streaming, per-impression scoring runs in map partitions, while cross-impression publisher state is held in memory.
  - In Flink, state is maintained in TaskManager memory without external checkpointing in this single-node benchmark harness.
- **Single-Node Docker Footprint**: Benchmarks run in Docker containers with explicit memory and CPU constraints. Real production clusters with distributed Kafka partitions will exhibit different network serialization profiles.
- **Illustrative Cost Estimates**: All dollar figures use ASSUMED pricing parameters from `config/model.yaml` (\$0.0001/vCPU-s, \$0.00001/GB-s) and represent illustrative cost models, not cloud service quotes.

## 5. Popularity Bias & Ethical Caveats

- **Descriptive Analytical Control**: Publisher exposure equity is evaluated relative to synthetic target shares. Equalized exposure does not imply journalistic merit or real-world publisher fairness.
- **Cold-Start Bias**: News items absent from the training split have low base scores due to lack of historical clicks, leading to lower served exposure regardless of re-ranking $\lambda$.
- **Utility Tradeoff**: Increasing $\lambda$ reduces publisher exposure L1 distance by up to 50% with minimal loss in served nDCG@5 up to $\lambda \approx 0.6$, beyond which ranking relevance degrades.

## 6. Privacy & User Data Protection

- **User Pseudonymization**: Raw user IDs (`U...`) from MIND behaviors are never logged, emitted to Kafka, or stored in plaintext.
- **Salting & Hashing**: All streaming replay and evaluation pipelines hash user IDs using SHA-256 combined with a secret salt (`MIND_USER_HASH_SALT`).
- **Data Retention**: Raw TSVs and zip archives in `data/raw/` are excluded from version control and repository distribution.
