"""
研究管道基准测试 CLI
运行并发/场景基准测试并输出 JSON 结果。
使用真实 PostgreSQL 连接，需要 --database-url 参数。

Usage:
    butler-benchmark-research --database-url 'postgresql+asyncpg://user:pass@host/db' --task-count 12
    butler-benchmark-research --database-url 'postgresql+asyncpg://user:pass@host/db' --worker-counts 1,3,5 --task-count 12 --output /tmp/bench.json
"""
import asyncio
import json
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from src.research.benchmark import BenchmarkConfig, run_full_benchmark


def run():
    """运行研究管道基准测试"""
    parser = argparse.ArgumentParser(
        description="Benchmark research pipeline concurrency with PostgreSQL"
    )
    parser.add_argument(
        "--database-url",
        required=True,
        help="PostgreSQL database URL (required, e.g. postgresql+asyncpg://user:pass@host/db)",
    )
    parser.add_argument(
        "--worker-counts",
        default="1,3,5",
        help="Comma-separated worker counts to test (default: 1,3,5)",
    )
    parser.add_argument(
        "--task-count",
        type=int,
        default=12,
        help="Number of tasks per scenario (default: 12)",
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
            "worker_counts": worker_counts,
            "task_count": args.task_count,
        },
        "provenance": {
            "benchmark_kind": "postgresql_controlled_harness",
            "external_dependencies": "fake",
            "taskiq_transport": False,
            "production_traffic": False,
        },
        "results": [asdict(r) for r in results],
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False))
        print(f"Benchmark results written to {args.output}")
    else:
        print(json.dumps(output, indent=2, ensure_ascii=False))
