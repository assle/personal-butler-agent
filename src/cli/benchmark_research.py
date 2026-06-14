"""
研究管道基准测试 CLI
运行并发/场景基准测试并输出 JSON 结果。

Usage:
    butler-benchmark-research --task-count 10
    butler-benchmark-research --worker-counts 1,2,4,8 --task-count 20 --output /tmp/bench.json
    butler-benchmark-research --database-url postgresql+asyncpg://localhost/bench --task-count 50
"""
import asyncio
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

from src.research.benchmark import BenchmarkConfig, run_full_benchmark


def run():
    """运行研究管道基准测试"""
    parser = argparse.ArgumentParser(
        description="Benchmark research pipeline concurrency"
    )
    parser.add_argument(
        "--database-url",
        default="sqlite+aiosqlite:///:memory:",
        help="Database URL for benchmark (default: in-memory SQLite)",
    )
    parser.add_argument(
        "--worker-counts",
        default="1,2,4,8",
        help="Comma-separated worker counts to test (default: 1,2,4,8)",
    )
    parser.add_argument(
        "--task-count",
        type=int,
        default=10,
        help="Number of tasks per scenario (default: 10)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path for JSON results (default: stdout)",
    )
    args = parser.parse_args()

    worker_counts = [int(w.strip()) for w in args.worker_counts.split(",")]
    config = BenchmarkConfig(
        database_url=args.database_url,
        worker_counts=worker_counts,
        task_count=args.task_count,
    )

    results = asyncio.run(run_full_benchmark(config))

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "database_url": args.database_url,
            "worker_counts": worker_counts,
            "task_count": args.task_count,
        },
        "results": [
            {
                "scenario": r.scenario,
                "worker_count": r.worker_count,
                "task_count": r.task_count,
                "success_count": r.success_count,
                "failure_count": r.failure_count,
                "total_duration_s": round(r.total_duration_s, 3),
                "p50_latency_s": round(r.p50_latency_s, 3),
                "p90_latency_s": round(r.p90_latency_s, 3),
                "p99_latency_s": round(r.p99_latency_s, 3),
                "mean_latency_s": round(r.mean_latency_s, 3),
                "throughput_tasks_per_sec": round(r.throughput_tasks_per_sec, 3),
            }
            for r in results
        ],
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False))
        print(f"Benchmark results written to {args.output}")
    else:
        print(json.dumps(output, indent=2, ensure_ascii=False))
