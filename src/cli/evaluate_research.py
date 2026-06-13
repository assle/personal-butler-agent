"""研究质量评估 CLI"""
import argparse, json
from pathlib import Path
from src.research.evaluation.runner import EvaluationRunner


def run():
    """评估研究质量（离线模式）"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    runner = EvaluationRunner()
    results = runner.run_offline(Path(args.cases))
    for r in results:
        print(r.model_dump_json())
