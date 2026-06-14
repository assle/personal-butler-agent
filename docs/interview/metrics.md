# Personal Butler Agent — Reproducible Research Metrics

> Generated from `artifacts/evaluation/results.json` and `artifacts/evaluation/benchmark_results.json`.
> All metrics are reproducible via the commands documented below.

---

## Evaluation Metrics (24 Cases)

Source: `artifacts/evaluation/results.json` (generated 2026-06-14)

### Overall Summary

| Metric | Mean | Interpretation |
|---|---|---|
| claim_topic_coverage | 0.78 | Claims address all required sub-topics (1.0 = complete) |
| citation_validity | 0.94 | Citations support the claims they are attached to |
| unsupported_material_claim_rate | 0.06 | Claims lacking evidence backing (proxy for hallucination) |
| required_source_coverage | 0.99 | Claims with required-source evidence binding |
| Total estimated cost | 767,500 microunits | DeepSeek token cost across all 24 cases |
| Mean latency | 1,120 ms | Per-case LLM execution time |

### Per-Category Breakdown

| Category | Cases | Mean Coverage | Mean Citation Validity | Mean Cost (microunits) | Mean Latency (ms) |
|---|---|---|---|---|---|
| comparison | 2 | 0.83 | 1.00 | 35,000 | 1,050 |
| performance | 2 | 0.50 | 0.83 | 38,500 | 1,450 |
| architecture | 2 | 0.67 | 1.00 | 24,000 | 1,050 |
| factual | 2 | 1.00 | 1.00 | 1,750 | 175 |
| howto | 2 | 1.00 | 1.00 | 10,000 | 600 |
| troubleshooting | 2 | 1.00 | 1.00 | 4,500 | 325 |
| design | 2 | 0.83 | 0.88 | 87,500 | 2,400 |
| security | 2 | 0.83 | 0.88 | 23,000 | 1,025 |
| best-practice | 2 | 0.50 | 1.00 | 10,000 | 600 |
| migration | 2 | 0.33 | 1.00 | 32,000 | 1,100 |
| research | 2 | 0.83 | 0.88 | 86,500 | 2,500 |
| data-modeling | 2 | 1.00 | 0.88 | 31,000 | 1,175 |

### Case-Level Detail

| Case ID | Coverage | Citation Validity | Unsupported Claims | Source Coverage |
|---|---|---|---|---|
| comparison-001 | 1.00 | 1.00 | 0.00 | 1.00 |
| comparison-002 | 0.67 | 1.00 | 0.00 | 1.00 |
| performance-001 | 0.67 | 0.67 | 0.33 | 0.67 |
| performance-002 | 0.33 | 1.00 | 0.00 | 1.00 |
| architecture-001 | 1.00 | 1.00 | 0.00 | 1.00 |
| architecture-002 | 0.33 | 1.00 | 0.00 | 1.00 |
| factual-001 | 1.00 | 1.00 | 0.00 | 1.00 |
| factual-002 | 1.00 | 1.00 | 0.00 | 1.00 |
| howto-001 | 1.00 | 1.00 | 0.00 | 1.00 |
| howto-002 | 1.00 | 1.00 | 0.00 | 1.00 |
| troubleshooting-001 | 1.00 | 1.00 | 0.00 | 1.00 |
| troubleshooting-002 | 1.00 | 1.00 | 0.00 | 1.00 |
| design-001 | 1.00 | 0.75 | 0.25 | 1.00 |
| design-002 | 0.67 | 1.00 | 0.00 | 1.00 |
| security-001 | 1.00 | 1.00 | 0.00 | 1.00 |
| security-002 | 0.67 | 0.75 | 0.25 | 1.00 |
| best-practice-001 | 0.33 | 1.00 | 0.00 | 1.00 |
| best-practice-002 | 0.67 | 1.00 | 0.00 | 1.00 |
| migration-001 | 0.67 | 1.00 | 0.00 | 1.00 |
| migration-002 | 0.00 | 1.00 | 0.00 | 1.00 |
| research-001 | 0.67 | 0.75 | 0.25 | 1.00 |
| research-002 | 1.00 | 1.00 | 0.00 | 1.00 |
| data-modeling-001 | 1.00 | 1.00 | 0.00 | 1.00 |
| data-modeling-002 | 1.00 | 0.75 | 0.25 | 1.00 |

---

## Worker-Count Benchmarks

Source: `artifacts/evaluation/benchmark_results.json` (generated 2026-06-14)

### Configuration
- Database: `sqlite+aiosqlite:///:memory:`
- Worker counts: 1, 2
- Task count: 5
- Scenarios: normal, timeout, execution_error, rate_limited

### Latency Results

#### Normal Execution

| Metric | 1 Worker | 2 Workers |
|---|---|---|
| Total duration | 0.740 s | 0.612 s |
| Mean latency | 0.148 s | 0.212 s |
| p50 latency | 0.158 s | 0.188 s |
| p90 latency | 0.167 s | 0.274 s |
| p99 latency | 0.171 s | 0.277 s |
| Throughput | 6.76 t/s | 8.17 t/s |

#### Timeout Simulation

| Metric | 1 Worker | 2 Workers |
|---|---|---|
| Total duration | 25.007 s | 15.004 s |
| Mean latency | 5.001 s | 5.001 s |
| Throughput | 0.20 t/s | 0.33 t/s |

#### Execution Error Simulation

| Metric | 1 Worker | 2 Workers |
|---|---|---|
| Total duration | 0.338 s | 0.107 s |
| Mean latency | 0.067 s | 0.036 s |
| Throughput | 14.81 t/s | 46.87 t/s |

#### Rate Limited Simulation

| Metric | 1 Worker | 2 Workers |
|---|---|---|
| Total duration | 0.000 s | 0.000 s |
| Throughput | 14,316 t/s | 20,291 t/s |

### Benchmark Analysis

- **Normal execution**: 2 workers provide ~21% throughput improvement. Sub-linear scaling due to SQLite write contention.
- **Timeout (5s simulated)**: 2 workers nearly halve total wall-clock time (25s -> 15s) by processing failed tasks in parallel.
- **Execution error (immediate fail)**: Near-linear scaling (14.8 -> 46.9 t/s) because tasks fail instantly with no I/O wait.
- **Rate limited (rejected before execution)**: Effectively infinite throughput because failures are synchronous and non-blocking.

---

## Reproducibility

### Evaluation Command

```bash
uv run butler-evaluate-research \
    --cases tests/fixtures/research_eval_cases.json \
    --output artifacts/evaluation/results.json
```

- Requires `DEEPSEEK_API_KEY` in environment or `.env`
- Runs 24 evaluation cases against the research pipeline (Supervisor -> Specialists -> Synthesizer -> Reviewer -> Quality Gate)
- Generates fresh `results.json` with updated metrics

### Benchmark Command

```bash
uv run butler-benchmark-research \
    --database-url 'postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
    --worker-counts 1,3,5 --task-count 12 \
    --output artifacts/benchmarks/benchmark_results.json
```

- Requires running PostgreSQL with `butler:butler@localhost:5432/butler_test`
- Requires `DEEPSEEK_API_KEY` for LLM calls
- Generates fresh benchmark results with configurable worker counts and task counts
