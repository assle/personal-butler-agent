"""
研究质量评估 CLI
支持离线模式，可输出 JSON 到文件或 stdout。

Usage:
    butler-evaluate-research --cases fixtures/research_eval_cases.json
    butler-evaluate-research --cases fixtures/research_eval_cases.json --output /tmp/eval.json
    butler-evaluate-research --cases fixtures/research_eval_cases.json --offline
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from src.research.evaluation.runner import EvaluationRunner


def run():
    """评估研究质量（离线模式）"""
    parser = argparse.ArgumentParser(
        description="Evaluate research quality with offline cases"
    )
    parser.add_argument("--cases", required=True, help="Path to cases JSON file")
    parser.add_argument("--offline", action="store_true", help="Run in offline mode")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path for pretty JSON results (default: stdout)",
    )
    args = parser.parse_args()

    runner = EvaluationRunner()
    results, summary = runner.run_offline_with_summary(Path(args.cases))

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary.model_dump(),
        "results": [r.model_dump() for r in results],
    }

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False))
        print(f"Results written to {args.output}")
    else:
        print(json.dumps(output, indent=2, ensure_ascii=False))
