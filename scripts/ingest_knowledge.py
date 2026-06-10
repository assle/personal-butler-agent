"""
知识库导入兼容脚本
保留原有 scripts/ingest_knowledge.py 调用方式，并转发到可安装的 CLI 实现。
"""
from src.cli.ingest_knowledge import run


if __name__ == "__main__":
    run()
