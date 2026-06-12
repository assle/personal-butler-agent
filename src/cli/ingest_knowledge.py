"""
本地知识库导入命令
解析命令行参数，读取 Markdown/TXT/PDF 文档或网页 URL，并通过 KnowledgeService 写入数据库。

Workflow:
  命令行参数 → 读取文件或抓取网页 → 确保数据库表存在 → 创建 KnowledgeIngestRequest
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
    """解析知识库导入命令参数

    参数:
        无

    返回:
        argparse.Namespace: 包含文件路径、scope、domain 等导入参数
    """
    parser = argparse.ArgumentParser(
        description="Import a Markdown/TXT/PDF document or web URL into the knowledge base."
    )
    parser.add_argument("path", nargs="?", default=None, help="Path to .md, .txt, or .pdf document")
    parser.add_argument("--url", default=None, help="Web URL to import")
    parser.add_argument("--title", default="", help="Document title; defaults to filename or URL path")
    parser.add_argument("--scope-type", required=True, choices=["public", "user", "group"])
    parser.add_argument("--scope-id", default=None, help="Required for user/group scopes")
    parser.add_argument(
        "--domain",
        required=True,
        choices=["global", "qa", "summary"],
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

    if args.path:
        path = Path(args.path)
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            from src.knowledge.parsers.pdf_parser import parse_pdf
            chunks = parse_pdf(path.read_bytes())
            content = "\n\n".join(c.content for c in chunks)
        elif suffix in (".md", ".txt"):
            content = path.read_text(encoding="utf-8")
        else:
            raise SystemExit(f"Unsupported file type: {suffix}. Use .md, .txt, or .pdf")
        source = str(path)
        title = args.title or path.stem
    elif args.url:
        from src.knowledge.parsers.web_parser import parse_web
        chunks = parse_web(args.url)
        content = "\n\n".join(c.content for c in chunks)
        source = args.url
        title = args.title or args.url.rsplit("/", 1)[-1]
    else:
        raise SystemExit("Provide either a file path or --url")

    request = KnowledgeIngestRequest(
        title=title,
        source=source,
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


def run() -> None:
    """启动异步知识库导入命令

    参数:
        无

    返回:
        None；执行完成后退出命令行进程
    """
    asyncio.run(main())


if __name__ == "__main__":
    run()
