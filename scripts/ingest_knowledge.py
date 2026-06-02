"""
本地知识库导入脚本
从本地 .md/.txt 文件读取内容，并通过 KnowledgeService 写入 SQLite

Workflow:
  命令行参数 → 读取文件 → 确保数据库表存在 → 创建 KnowledgeIngestRequest
  → KnowledgeService.ingest() → 提交事务并输出导入结果
"""
import argparse
import asyncio
from pathlib import Path

from src.db.base import Base
from src.db.session import async_session, engine
from src.knowledge.schemas import KnowledgeIngestRequest
from src.knowledge.service import KnowledgeService


def parse_args() -> argparse.Namespace:
    """解析命令行参数

    参数:
        无

    返回:
        argparse.Namespace: 包含文件路径、scope、domain 等导入参数
    """
    parser = argparse.ArgumentParser(
        description="Import a Markdown/TXT document into the knowledge base."
    )
    parser.add_argument("path", help="Path to .md or .txt document")
    parser.add_argument("--title", default="", help="Document title; defaults to filename")
    parser.add_argument("--scope-type", required=True, choices=["public", "user", "group"])
    parser.add_argument("--scope-id", default=None, help="Required for user/group scopes")
    parser.add_argument(
        "--domain",
        required=True,
        choices=["global", "qa", "fitness", "meal", "summary"],
    )
    parser.add_argument("--created-by", default=None, help="Creator user_id")
    return parser.parse_args()


async def _ensure_tables() -> None:
    """确保知识库导入所需数据库表已创建

    参数:
        无

    返回:
        None；通过 SQLAlchemy metadata 创建缺失表
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def main() -> None:
    """执行文档导入

    参数:
        无

    返回:
        None；导入结果打印到标准输出
    """
    args = parse_args()
    path = Path(args.path)
    if path.suffix.lower() not in {".md", ".txt"}:
        raise SystemExit("Only .md and .txt files are supported in Stage 1")

    content = path.read_text(encoding="utf-8")
    request = KnowledgeIngestRequest(
        title=args.title or path.stem,
        source=str(path),
        content=content,
        scope_type=args.scope_type,
        scope_id=args.scope_id,
        domain=args.domain,
        created_by=args.created_by,
    )
    service = KnowledgeService()

    await _ensure_tables()
    async with async_session() as db:
        document = await service.ingest(request, db)
        await db.commit()

    if document is None:
        print("Skipped duplicate document")
    else:
        print(f"Imported document #{document.id}: {document.title}")


if __name__ == "__main__":
    asyncio.run(main())
