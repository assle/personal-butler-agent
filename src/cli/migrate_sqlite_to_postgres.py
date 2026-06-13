"""
SQLite 到 PostgreSQL 一次性迁移工具
按依赖顺序复制所有业务表，回填 workspace_id，校验完整性

Usage:
  uv run butler-migrate-sqlite-to-postgres \
    --source sqlite+aiosqlite:///butler.db \
    --target postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler \
    --workspace-id default \
    --workspace-name "Default Workspace" \
    --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from src.config import settings

logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setLevel(logging.INFO)
    logger.addHandler(h)


# 表迁移顺序：父表在前，子表在后
TABLE_ORDER = [
    # 无外部依赖的表
    "workspaces",
    "conversation_summaries",
    "conversation_messages",
    "group_messages",
    "group_webhooks",
    "inbound_messages",
    "knowledge_documents",
    "knowledge_chunks",
    "knowledge_chunk_embeddings",
    "polls",
    "poll_votes",
    "reminders",
    "reminder_runs",
    "user_group_access",
    "user_memories",
    "memory_fragments",
    "wecom_user_bindings",
    # 依赖 workspaces
    "workspace_members",
    "user_profile",
    # 依赖 workspaces + workspace_members
    "research_tasks",
    "research_reports",
    "research_deliveries",
]


@dataclass(frozen=True)
class MigrationResult:
    """迁移校验结果"""
    table_counts: dict[str, tuple[int, int]]  # (source_count, target_count)
    duplicate_source_msgids: list[str]
    orphaned_workspace_rows: list[str]


async def migrate_database(
    sqlite_url: str,
    postgres_url: str,
    *,
    workspace_id: str,
    workspace_name: str,
    dry_run: bool,
) -> MigrationResult:
    """迁移并校验结构化业务数据

    参数:
        sqlite_url: 只读 SQLite 来源 URL
        postgres_url: 已升级到 Alembic head 的 PostgreSQL URL
        workspace_id: 承接旧数据的工作空间 ID
        workspace_name: 默认工作空间名称
        dry_run: 为 True 时仅校验来源与目标，不提交写入

    返回:
        MigrationResult: 表计数与完整性校验结果
    """
    # 创建引擎
    source_engine = create_async_engine(sqlite_url, echo=False)
    target_engine = create_async_engine(postgres_url, echo=False)
    source_session = async_sessionmaker(source_engine, class_=AsyncSession, expire_on_commit=False)
    target_session = async_sessionmaker(target_engine, class_=AsyncSession, expire_on_commit=False)

    table_counts: dict[str, tuple[int, int]] = {}
    duplicate_source_msgids: list[str] = []
    orphaned_workspace_rows: list[str] = []

    try:
        async with source_session() as src, target_session() as tgt:
            # 1. 确保默认工作空间存在
            await _ensure_workspace(tgt, workspace_id, workspace_name, dry_run)
            if not dry_run:
                await tgt.flush()

            # 2. 计数来源表
            source_counts = {}
            for table_name in TABLE_ORDER:
                result = await src.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                source_counts[table_name] = result.scalar() or 0
            logger.info("来源 SQLite 表计数: %s", source_counts)

            # 3. 按顺序复制表数据
            for table_name in TABLE_ORDER:
                source_count = source_counts.get(table_name, 0)
                if source_count == 0:
                    table_counts[table_name] = (0, 0)
                    continue

                rows = await _fetch_table(src, table_name)
                target_count = await _insert_table(
                    tgt, table_name, rows,
                    workspace_id=workspace_id,
                    dry_run=dry_run,
                )
                table_counts[table_name] = (source_count, target_count)
                logger.info(
                    "迁移表 %s: %d/%d 行", table_name, target_count, source_count
                )

            # 4. 回填 workspace_id 到已有表
            await _backfill_workspace_id(tgt, workspace_id, dry_run)

            # 5. 校验
            duplicate_source_msgids = await _check_duplicate_msgids(tgt)
            orphaned_workspace_rows = await _check_orphaned_fks(tgt, workspace_id)

            if dry_run:
                logger.info("DRY RUN — 未提交任何写入")
            else:
                await tgt.commit()
                logger.info("迁移已提交")

    finally:
        await source_engine.dispose()
        await target_engine.dispose()

    return MigrationResult(
        table_counts=table_counts,
        duplicate_source_msgids=duplicate_source_msgids,
        orphaned_workspace_rows=orphaned_workspace_rows,
    )


async def _ensure_workspace(db, workspace_id, workspace_name, dry_run):
    """确保默认工作空间存在于目标数据库"""
    result = await db.execute(
        text("SELECT 1 FROM workspaces WHERE id = :id"),
        {"id": workspace_id},
    )
    if result.scalar() is not None:
        logger.info("工作空间 %s 已存在，跳过创建", workspace_id)
        return
    if dry_run:
        logger.info("DRY RUN: 将创建工作空间 %s", workspace_id)
        return
    await db.execute(
        text(
            "INSERT INTO workspaces (id, name, status, policy, created_at, updated_at) "
            "VALUES (:id, :name, 'active', '{}', :now, :now)"
        ),
        {
            "id": workspace_id,
            "name": workspace_name,
            "now": datetime.now(timezone.utc).isoformat(),
        },
    )


async def _fetch_table(db, table_name):
    """从来源库读取表全部行"""
    result = await db.execute(text(f"SELECT * FROM {table_name}"))
    columns = result.keys()
    return [dict(zip(columns, row)) for row in result.fetchall()]


async def _insert_table(db, table_name, rows, *, workspace_id, dry_run):
    """将行数据写入目标表，保留主键并回填 workspace_id"""
    if not rows:
        return 0

    columns = list(rows[0].keys())

    # 对需要 workspace_id 回填的表进行处理
    # 这些表在模型中定义 workspace_id 列为非空，迁移时回填默认值
    workspace_tables = {
        "research_tasks", "research_reports", "research_deliveries",
    }
    if table_name in workspace_tables and "workspace_id" in columns:
        for row in rows:
            if row.get("workspace_id") is None:
                row["workspace_id"] = workspace_id

    if dry_run:
        return len(rows)

    # 使用 INSERT 逐行执行以保留主键
    placeholders = ", ".join(f":{col}" for col in columns)
    col_names = ", ".join(columns)
    sql = f"INSERT INTO {table_name} ({col_names}) VALUES ({placeholders})"
    count = 0
    for row in rows:
        try:
            await db.execute(text(sql), row)
            count += 1
        except Exception as exc:
            logger.warning("插入 %s 行失败: %s", table_name, exc)
    return count


async def _backfill_workspace_id(db, workspace_id, dry_run):
    """为所有可归属行回填 workspace_id"""
    tables = ["research_tasks", "research_reports", "research_deliveries"]
    for table_name in tables:
        if dry_run:
            result = await db.execute(
                text(f"SELECT COUNT(*) FROM {table_name} WHERE workspace_id IS NULL")
            )
            null_count = result.scalar() or 0
            if null_count > 0:
                logger.info("DRY RUN: 将回填 %d 行到 %s", null_count, table_name)
        else:
            await db.execute(
                text(
                    f"UPDATE {table_name} SET workspace_id = :ws_id WHERE workspace_id IS NULL"
                ),
                {"ws_id": workspace_id},
            )
        await db.flush()


async def _check_duplicate_msgids(db):
    """检查 research_tasks 中重复的 source_msgid"""
    result = await db.execute(
        text(
            "SELECT source_msgid, COUNT(*) as cnt FROM research_tasks "
            "GROUP BY source_msgid HAVING cnt > 1"
        )
    )
    return [row[0] for row in result.fetchall()]


async def _check_orphaned_fks(db, workspace_id):
    """检查孤儿外键"""
    orphans = []
    # 检查 research_tasks 的 workspace_id
    result = await db.execute(
        text(
            "SELECT id FROM research_tasks "
            "WHERE workspace_id NOT IN (SELECT id FROM workspaces)"
        )
    )
    orphans.extend(f"research_tasks.id={row[0]}" for row in result.fetchall())
    return orphans


async def main():
    """CLI 异步入口"""
    parser = argparse.ArgumentParser(description="SQLite → PostgreSQL 一次性数据迁移")
    parser.add_argument("--source", required=True, help="SQLite 数据库 URL")
    parser.add_argument("--target", required=True, help="目标 PostgreSQL URL")
    parser.add_argument("--workspace-id", default="default", help="默认工作空间 ID")
    parser.add_argument("--workspace-name", default="Default Workspace", help="默认工作空间名称")
    parser.add_argument("--dry-run", action="store_true", help="仅校验，不写入")
    args = parser.parse_args()

    result = await migrate_database(
        sqlite_url=args.source,
        postgres_url=args.target,
        workspace_id=args.workspace_id,
        workspace_name=args.workspace_name,
        dry_run=args.dry_run,
    )

    # 输出结果
    print("\n=== 迁移结果 ===")
    for table, (src, tgt) in sorted(result.table_counts.items()):
        status = "✓" if src == tgt else "✗"
        print(f"  {status} {table}: SQLite={src} → PG={tgt}")

    if result.duplicate_source_msgids:
        print(f"\n重复 source_msgid: {result.duplicate_source_msgids}")
    if result.orphaned_workspace_rows:
        print(f"\n孤儿 workspace 外键: {result.orphaned_workspace_rows}")

    if not result.duplicate_source_msgids and not result.orphaned_workspace_rows:
        print("\n迁移校验通过。")


def run():
    """CLI 同步入口（兼容 pyproject.toml entry point）"""
    asyncio.run(main())


if __name__ == "__main__":
    run()
