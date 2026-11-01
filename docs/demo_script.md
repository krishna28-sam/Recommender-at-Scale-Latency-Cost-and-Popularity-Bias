# 3-Minute Demonstration Script: Recommender at Scale

**Project**: Recommender at Scale: Latency, Cost and Popularity Bias  
**Team**:  
- Sripada Krishna Sameer Aditya (PES1UG24AM285)  
- Shree Verdhan M (PES1UG24AM265)  
- Shrivamshi Chikkireddi (PES1UG24AM287)  
**Target Duration**: Exactly 3 minutes (180 seconds)  
**Demo Date**: 2 November 2026  

---

## Timing Breakdown Overview

| Time Window | Segment | Focus | Screen / Visual Display |
| :--- | :--- | :--- | :--- |
| **0:00 – 0:20 (20s)** | Architecture & Problem | Motivation, dual-engine setup | Architecture Mermaid diagram (README.md) |
| **0:20 – 0:50 (30s)** | Offline Popularity Bias | Pareto curve (Exposure L1 vs nDCG@5) | Chart 4 in `notebooks/results.ipynb` |
| **0:50 – 1:50 (60s)** | Live Streaming Demonstration | End-to-end Kafka transport & engine | Terminal executing `make smoke` |
| **1:50 – 2:40 (50s)** | Benchmark Matrix Findings | Latency, buffer tuning, saturation | Table 1 & Chart 1 from report / notebook |
| **2:40 – 3:00 (20s)** | Limitations & Conclusion | Caveats, ASSUMED cost, Q&A | `cards/model_card.md` & Repo summary |

---

## Detailed Script & Spoken Narrative

### 1. Architecture Overview (0:00 – 0:20 | 20 seconds)
- **Visual**: Display the architecture diagram from `README.md`.
- **Presenter Spoken Narrative**:
  > *"Good morning. Our project evaluates high-throughput streaming news recommendation at scale. We compare Apache Spark Structured Streaming against Apache Flink on the real MIND-small dataset. We address two core challenges: first, characterizing real-time latency and saturation limits under heavy ingestion; second, mitigating publisher popularity bias in real time using a stateful fair re-ranking algorithm."*

---

### 2. Offline Popularity Bias & Pareto Frontier (0:20 – 0:50 | 30 seconds)
- **Visual**: Display Chart 4 from `notebooks/results.ipynb` (Popularity Bias Mitigation: Exposure L1 vs. Served Utility).
- **Presenter Spoken Narrative**:
  > *"Before streaming, we analyzed offline ranking on 73,152 validation impressions across six synthetic publisher mappings. Standard point-wise CTR models suffer from severe popularity concentration. By introducing an exposure-aware penalty lambda between 0.0 and 5.0, our fair re-ranker discounts over-represented publishers. As shown on this Pareto curve, setting lambda=0.6 reduces publisher exposure distance by over 12% with virtually zero loss in served nDCG@5. Even aggressive re-ranking at lambda=5.0 slashes exposure distance by 40% to 44% with only a 0.0036 to 0.0134 (1.2% to 4.4%) utility penalty on served nDCG@5."*

---

### 3. Live Streaming Demonstration (0:50 – 1:50 | 60 seconds)
- **Visual**: Switch to terminal. Execute the live smoke verification command.
- **Terminal Command**:
  ```bash
  MIND_USER_HASH_SALT="demo-secret-2026" ENGINE_MODE=pass-through make smoke
  ```
- **Scope & What Is Exercised**:
  - *Infrastructure & Transport*: Brings up Kafka (with `LogAppendTime`), starts Spark Structured Streaming and PyFlink DataStream containers, and spins up the replay producer.
  - *Data Privacy*: Verifies that the replay producer cryptographically salts and hashes user IDs using SHA-256 before emitting records to Kafka (zero raw user IDs in flight).
  - *Streaming Pipeline*: Demonstrates end-to-end ingestion and delivery across both engines with automated bounded offset validation (ensuring all input impressions are served with $R \ge I$, rejecting missing outputs, and bounding at-least-once duplication to $\le 1.2\times$).
  - *Note on Pass-Through Mode*: `make smoke` uses `ENGINE_MODE=pass-through` to swiftly prove container, broker, and transport health in under 60 seconds without loading heavy model tables. The full scoring and fairness-aware re-ranking algorithms (`ENGINE_MODE=score`) are validated in our benchmark matrix (`bench/results/*.csv`) and unit tests (`tests/test_streaming.py`, `tests/test_recsys.py`).
- **Presenter Spoken Narrative**:
  > *"Now let's see the streaming pipeline live. We run `make smoke`, which tests end-to-end container and transport orchestration: Kafka provisions topics with LogAppendTime, while our replay producer hashes user IDs with salted SHA-256 for privacy. Both Spark and PyFlink consume the live stream, emit top recommendations, and pass bounded offset checks confirming that all input events were processed without missing outputs. While this fast smoke test validates infrastructure with pass-through routing, our full scoring and fair re-ranking models were executed across our comprehensive 42-run benchmark matrix."*
- **Action**: Highlight the green checkmark: `spark offset parity check passed` and `flink offset parity check passed`.

---

### 4. Streaming Benchmark Matrix Findings (1:50 – 2:40 | 50 seconds)
- **Visual**: Display Table 1 and Chart 1 from `report/report.docx` or `notebooks/results.ipynb`.
- **Presenter Spoken Narrative**:
  > *"Across our 42-run benchmark matrix with 60-second windows and 3 replications, we uncovered several critical systems insights:*
  > *1. **Flink's Bundle Buffer**: Out of the box, PyFlink's Python worker buffers output records, creating a 1,008 ms latency floor at 1,000 events/second. By tuning bundle buffer time to 50 ms (`flink-p1-tuned`), p50 latency plummeted to 216 ms, beating Spark.*
  > *2. **Spark Micro-batch Tradeoff**: Spark's default eager trigger achieves 292 ms latency, while a 1-second trigger increases latency to 920 ms but reduces CPU usage by 39% by amortizing driver coordination.*
  > *3. **Saturation Collapse**: At 2,000 events/second, both single-node engines saturate around 1,730 events/second, causing queue backlog to swell past 18,000 events.*
  > *4. **Re-ranking Overhead**: Fair re-ranking adds less than 1% CPU and 4% latency below saturation, making real-time fairness highly practical."*

---

### 5. Honest Limitations, Costs & Conclusion (2:40 – 3:00 | 20 seconds)
- **Visual**: Display `cards/model_card.md` Limitations section.
- **Presenter Spoken Narrative**:
  > *"To remain methodologically honest: our cost numbers are ASSUMED and illustrative based on standard cloud modeling, not live quotes. Publisher mappings are synthetic analytical controls since MIND lacks publisher tags, and state is maintained in single-node memory without external checkpointing. In conclusion, lightweight fair re-ranking is feasible at sub-second streaming latencies, with Flink offering lower per-event cost and Spark offering simpler micro-batch tuning. Thank you, and we welcome your questions."*

---

## Contingency Backup Plan (If Live Docker Fails)

If Docker or Kafka experiences startup latency, port conflicts, or container crashes during the live evaluation:

1. **Immediate Action**: Do not spend time live-debugging Docker in front of the evaluators.
2. **Switch to Pre-Rendered Visuals**:
   - Immediately open `notebooks/results.ipynb` in the browser or VS Code notebook viewer.
   - Walk through the pre-executed live outputs in Cell 1 (`Probe rows loaded: 41`, `Matrix summary rows loaded: 14`), showing that the pipeline has been verified with 42 replicated runs.
3. **Inspect Output Files**:
   - Show `data/processed/analysis/matrix_summary.csv` and `logs/probe_report.csv` directly in terminal:
     ```bash
     head -n 8 data/processed/analysis/matrix_summary.csv | cut -d, -f1,2,4,6,12,18,22
     ```
4. **Offline Re-ranking Demonstration**:
   - Run the fast unit test suite to prove full functional correctness:
     ```bash
     source .venv/bin/activate && python3 -m pytest -q
     ```
5. **Video Backup**: Prior to the presentation, record a 60-second screen capture of a successful `make smoke` execution and keep the MP4 on your local desktop as an emergency backup.
