# 3-Minute Demonstration Video Narration Script

**Project**: Recommender at Scale: Latency, Cost and Popularity Bias in Streaming News Recommendation  
**Course**: Big Data Systems (Final Submission Demo: 2 November 2026)  
**Team**:  
- Sripada Krishna Sameer Aditya (PES1UG24AM285)  
- Shree Verdhan M (PES1UG24AM265)  
- Shrivamshi Chikkireddi (PES1UG24AM287)  
**Repository**: https://github.com/krishna28-sam/Recommender-at-Scale-Latency-Cost-and-Popularity-Bias  
**Target Duration**: Exactly 180 seconds (3:00)

---

## Segment Breakdown & Visual Layout

### Segment 1: Title, Problem Statement & Motivation (0:00 – 0:25 | 25s)
- **Visual Display**: Title card with project title, team members, institutional metadata, and dual problem pillars (Systems Scalability vs. Publisher Popularity Bias).
- **Spoken Narration**:
  > *"Good morning. Welcome to our demonstration of 'Recommender at Scale: Latency, Cost, and Popularity Bias'. Modern digital platforms serve millions of users concurrently, creating two conflicting challenges: first, streaming engines must deliver recommendations within sub-second latencies under heavy ingestion; second, standard click-through rate models create a severe popularity bias loop, where dominant publishers monopolize user feeds and starve emerging content creators. Our project rigorously compares Apache Spark Structured Streaming and Apache Flink on the real MIND news dataset to evaluate real-time scalability, cloud costs, and algorithmic fairness mitigation."*

---

### Segment 2: Dual-Engine Streaming Architecture (0:25 – 0:55 | 30s)
- **Visual Display**: Complete system architecture flow diagram illustrating the Replay Producer, Kafka topics (`impressions` & `recommendations` with 2 partitions and `LogAppendTime`), Spark micro-batching, Flink continuous DataStream, static Laplace CTR tables, and the Benchmark Monitor.
- **Spoken Narration**:
  > *"Here is our end-to-end distributed system architecture. The pipeline begins with an empirical replay producer reading from the MIND dataset. For strict privacy compliance, all user IDs are pseudonymized using salted SHA-256 hashes, ensuring zero raw user IDs enter Kafka. Events flow into a partitioned Kafka cluster configured with LogAppendTime, which timestamps records upon disk arrival to eliminate clock skew. We deploy two streaming engines: PySpark Structured Streaming using configurable micro-batch triggers, and PyFlink using event-driven pipelined execution. Each engine queries precomputed Laplace-smoothed CTR tables and applies our fair re-ranking algorithm before emitting top-5 served recommendations back to Kafka."*

---

### Segment 3: Popularity Bias, Fairness & The Pareto Frontier (0:55 – 1:25 | 30s)
- **Visual Display**: Chart 4 Pareto frontier (Exposure L1 Distance vs. Served nDCG@5 utility), metric equations for Exposure L1 and Laplace CTR, and 95% bootstrap confidence interval summary.
- **Spoken Narration**:
  > *"Before streaming, we analyzed offline ranking on 73,152 validation impressions across six synthetic publisher mappings. Without intervention, popular articles dominate user impressions, creating severe exposure inequality. We introduced an exposure-aware greedy re-ranking penalty governed by parameter lambda. When lambda equals zero, the recommender acts greedily on CTR. As lambda increases to 5.0, our fair re-ranker slashes publisher exposure inequality by 40% to 44%, verified across 1,000 bootstrap resamples with 95% confidence intervals strictly excluding zero. Crucially, this massive fairness gain comes at a minor utility cost of only 1.2% to 4.4% in served nDCG@5."*

---

### Segment 4: Live Streaming Pipeline & Smoke Validation (1:25 – 1:55 | 30s)
- **Visual Display**: Terminal playback executing `MIND_USER_HASH_SALT="demo-secret-2026" ENGINE_MODE=pass-through make smoke`, highlighting Kafka topic lifecycle, container orchestration, consumer offset inspection, and the green offset parity check.
- **Spoken Narration**:
  > *"Now let's examine the streaming pipeline in action. We execute our verified `make smoke` target, which starts Kafka, provisions the dual topics with LogAppendTime, and launches the replay producer alongside Spark and Flink. In this smoke test, pass-through mode swiftly verifies container orchestration, network routing, and message transport without loading heavy model tables. Both engines consume live impressions, serialize top recommendations, and pass automated bounded offset checks, confirming all input events were processed without missing records. Full scoring and fair re-ranking are executed in our 42-run benchmark matrix."*

---

### Segment 5: 42-Run Benchmark Matrix & Systems Findings (1:55 – 2:35 | 40s)
- **Visual Display**: Table 1 summary and multi-panel charts displaying End-to-End Latency vs. Rate, CPU per 1,000 events, Backlog accumulation at saturation (18,000+ events), and the Flink bundle buffer comparison (1,008 ms vs. 216 ms).
- **Spoken Narration**:
  > *"Across our 42-run benchmark matrix with 60-second measurement windows and 3 independent replications, we uncovered three critical systems insights: First, PyFlink out-of-the-box introduces a 1,008 ms latency floor due to its internal Python worker bundle buffer. By tuning `python.fn-execution.bundle.time` to 50 milliseconds, p50 latency plummeted to 216 ms, beating Spark's 292 ms. Second, Spark's 1-second fixed trigger increased latency to 920 ms, but reduced CPU utilization by 39% by amortizing driver coordination. Third, at 2,000 events/second, single-node capacity saturates at approximately 1,730 events/second, causing queue backlog to swell past 18,000 events. Most importantly, fair re-ranking added less than 1% CPU and under 12 ms latency, proving real-time fairness is highly production-viable."*

---

### Segment 6: Honest Limitations, Cloud Costs & Conclusion (2:35 – 3:00 | 25s)
- **Visual Display**: Summary slide detailing methodological limitations (synthetic publisher controls, assumed cloud pricing, in-memory state), key numerical takeaways, GitHub repository link, and team sign-off.
- **Spoken Narration**:
  > *"To maintain scientific rigor, we disclose three honest limitations: our publisher groups are synthetic analytical controls because MIND lacks publisher tags; cost figures are modeled using standard cloud pricing rates rather than live invoices; and state is tracked in single-node memory. In conclusion, lightweight fair re-ranking is computationally viable at streaming ingestion rates, and tuning engine buffer configurations is far more decisive than raw engine selection. Our complete code, 4-page report, and 14-page viva guide are published and reproducible on GitHub. Thank you."*

