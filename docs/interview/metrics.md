# Personal Butler Agent — Reproducible Research Metrics

> Generated from `artifacts/evaluation/2026-06-interview-baseline.json` and `artifacts/benchmarks/2026-06-interview-baseline.json`.
> All metrics are reproducible via the commands documented below.

> **Disclaimer**: These metrics are produced by offline, deterministic evaluation and a PostgreSQL controlled-harness benchmark. The following are **not measured**: production QPS, DeepSeek API latency in real conditions, Taskiq transport throughput, or factual accuracy against ground truth. Metrics should be interpreted as baseline pipeline correctness indicators, not production service-level indicators.

---

## Evaluation Metrics (24 Cases)

Source: `artifacts/evaluation/2026-06-interview-baseline.json`

### Overall Summary

| Metric | Mean | Interpretation |
|---|---|---|
| claim_topic_coverage | 0.78 | Claims address all required sub-topics (1.0 = complete) |
| citation_validity | 0.94 | Citations support the claims they are attached to |
| unsupported_material_claim_rate | 0.06 | Claims lacking evidence backing (proxy for hallucination) |
| required_source_coverage | 0.99 | Claims with required-source evidence binding |

### Per-Category Breakdown

| Category | Cases | Mean Coverage | Mean Citation Validity |
|---|---|---|---|---|
| comparison | 2 | 0.83 | 1.00 |
| performance | 2 | 0.50 | 0.83 |
| architecture | 2 | 0.67 | 1.00 |
| factual | 2 | 1.00 | 1.00 |
| howto | 2 | 1.00 | 1.00 |
| troubleshooting | 2 | 1.00 | 1.00 |
| design | 2 | 0.83 | 0.88 |
| security | 2 | 0.83 | 0.88 |
| best-practice | 2 | 0.50 | 1.00 |
| migration | 2 | 0.33 | 1.00 |
| research | 2 | 0.83 | 0.88 |
| data-modeling | 2 | 1.00 | 0.88 |

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

Source: `artifacts/benchmarks/2026-06-interview-baseline.json`

### Configuration
- **Benchmark kind**: PostgreSQL controlled harness (fake external dependencies)
- **Database dialect**: `postgresql+asyncpg`
- **Worker counts**: 1, 3, 5
- **Task count**: 12
- **Scenarios**: normal, timeout, execution_error, rate_limited
- **Duplicate claim prevention**: verified zero duplicate claims across all worker counts

### Results Summary

| Worker Count | Normal (t/s) | Timeout (t/s) | Execution Error (t/s) | Rate Limited (t/s) |
|---|---|---|---|---|
| 1 | (see artifact) | (see artifact) | (see artifact) | (see artifact) |
| 3 | (see artifact) | (see artifact) | (see artifact) | (see artifact) |
| 5 | (see artifact) | (see artifact) | (see artifact) | (see artifact) |

> Run `python3 -m json.tool artifacts/benchmarks/2026-06-interview-baseline.json` for full latency percentiles and per-worker metrics.

### Benchmark Analysis

- **Controlled harness**: all external dependencies are mocked; measured time reflects database contention, leasing overhead, and step dispatch, not real LLM or network latency.
- **No duplicate claims**: zero `duplicate_claim_count` across all runs validates the `FOR UPDATE SKIP LOCKED` claim mechanism.
- **Linearity limited by PostgreSQL**: scaling from 1 to 3 to 5 workers shows diminishing returns as PostgreSQL row-lock contention increases, especially for time-bound scenarios.

---

## Reproducibility

### Evaluation Command

```bash
DEEPSEEK_API_KEY=test uv run butler-evaluate-research \
    --cases tests/fixtures/research_eval_cases.json \
    --offline \
    --output artifacts/evaluation/2026-06-interview-baseline.json
```

- Uses `--offline` mode: no real LLM calls; computes deterministic metrics from versioned fixture artifacts.
- Runs 24 predefined case fixtures against deterministic metric calculation logic.
- Generates fresh `2026-06-interview-baseline.json` with updated metrics.

### Benchmark Command

```bash
DEEPSEEK_API_KEY=test uv run butler-benchmark-research \
    --database-url 'postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
    --worker-counts 1,3,5 --task-count 12 \
    --output artifacts/benchmarks/2026-06-interview-baseline.json
```

- **Requires**: running PostgreSQL with `butler:butler@localhost:5432/butler_test`
- **Does not require**: `DEEPSEEK_API_KEY` (offline fixture evaluation)
- **Provenance limitation**: results reflect a controlled harness with fake external dependencies, not production workload. Throughput numbers are useful for comparing relative worker-count efficiency, not for capacity planning.
