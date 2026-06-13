# Multi-Agent Research Phase 1 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the asynchronous research foundation: private-chat submission, durable task state, Redis Stream queue, independent worker execution, a clearly labeled one-shot LLM draft, and proactive Enterprise WeChat custom-application delivery.

**Architecture:** `PrivateButlerAgent` recognizes explicit Phase 1 research commands and delegates persistence plus enqueueing to `ResearchSubmissionService`. Taskiq uses `RedisStreamBroker`; worker tasks reopen their own SQLAlchemy sessions, generate an `unreviewed_foundation` draft, persist it, and enqueue a separate delivery task. `WeComAppMessageClient` converts robot `open_userid` values, caches custom-application tokens in Redis, validates Enterprise WeChat business responses, and never treats HTTP 200 alone as success.

**Tech Stack:** Python 3.13+, FastAPI, SQLAlchemy 2 async, SQLite, Taskiq, taskiq-redis, Redis Streams, httpx, LangChain `LLMClient`, pytest

---

## Plan Boundary

The approved design contains five independently testable phases. Do not implement all phases in one change set.

| Plan | Deliverable |
|---|---|
| **Phase 1, this plan** | Queue, workers, task/report/delivery persistence, explicit private submission, one-shot draft, custom-app push |
| Phase 2, later plan | Deterministic planning, authorized retrieval, synthesis, evidence/claim schemas, citation validation |
| Phase 3, later plan | Supervisor plus Planner, Knowledge Researcher, Web Researcher, Synthesizer, Evidence Reviewer |
| Phase 4, later plan | Persistent graph checkpoints, cancellation, admin operations, metrics, robust recovery |
| Phase 5, later plan | PostgreSQL migration and independently scalable worker pools |

Phase 1 must not claim that reports are researched, cited, or independently reviewed. Every generated report and notification uses quality status `unreviewed_foundation`.

Approving execution of this plan explicitly authorizes creation and modification of the test files listed below.

## File Map

**New runtime modules**

- `src/models/research.py`: research task, report, delivery, group authorization, and WeCom identity binding tables.
- `src/research/__init__.py`: stable public exports.
- `src/research/schemas.py`: statuses and immutable result dataclasses.
- `src/research/service.py`: task creation, idempotency, per-user concurrency, transitions, and lookup.
- `src/research/broker.py`: Taskiq `RedisStreamBroker`.
- `src/research/queue.py`: application-owned dispatcher interface and Taskiq adapter.
- `src/research/submission.py`: private-chat submit/status facade.
- `src/research/executor.py`: one-shot draft execution and report persistence.
- `src/research/delivery.py`: identity resolution, delivery formatting, and delivery-state persistence.
- `src/research/tasks.py`: thin Taskiq research and delivery tasks.
- `src/wechat/app_client.py`: custom-application token, ID conversion, and application-message API client.

**Modified runtime modules**

- `pyproject.toml`, `uv.lock`: Taskiq and Redis dependencies.
- `src/config.py`: queue, research, and custom-application settings.
- `src/models/__init__.py`: register research ORM models.
- `src/messaging/dispatch.py`: pass source `msgid` into private scene state.
- `src/agents/private_butler/graph.py`: explicit research submit/status shortcuts.
- `src/main.py`: construct submission dependencies and manage producer broker lifecycle.

**Tests**

- `tests/test_research_models.py`
- `tests/test_research_service.py`
- `tests/test_research_queue.py`
- `tests/test_wecom_app_client.py`
- `tests/test_research_executor.py`
- `tests/test_research_delivery.py`
- `tests/test_research_tasks.py`
- Modify `tests/test_config.py`
- Modify `tests/test_butler_agent.py`
- Modify `tests/test_messaging.py`
- Modify `tests/test_aibot_callback.py`

**Documentation**

- `.env.example`
- `deployment.md`
- `deployment.en.md`
- `README.md`
- `README.en.md`
- `CLAUDE.md`
- `AGENTS.md`
- `docs/agent/active-context.md`
- `docs/agent/patterns.md`
- `docs/agent/decisions.md`
- `docs/agent/config-variables.md`
- `docs/agent/upgrade-roadmap.md`

---

### Task 1: Add Async Queue and Custom-App Configuration

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `src/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing configuration tests**

Append to `tests/test_config.py`:

```python
def test_settings_loads_research_and_wecom_app_config():
    """验证研究队列和企微自建应用配置可从环境变量加载"""
    env_vars = {
        "DEEPSEEK_API_KEY": "sk-test-key",
        "RESEARCH_ENABLED": "true",
        "REDIS_URL": "redis://redis.test:6379/2",
        "RESEARCH_QUEUE_NAME": "butler-research-test",
        "RESEARCH_MAX_ROUNDS": "4",
        "RESEARCH_TIMEOUT_SECONDS": "300",
        "WECOM_APP_CORP_ID": "ww-test",
        "WECOM_APP_SECRET": "secret-test",
        "WECOM_APP_AGENT_ID": "1000002",
    }
    with patch.dict(os.environ, env_vars, clear=True):
        from src.config import Settings

        settings = Settings(_env_file=None)
        assert settings.research_enabled is True
        assert settings.redis_url == "redis://redis.test:6379/2"
        assert settings.research_queue_name == "butler-research-test"
        assert settings.research_max_rounds == 4
        assert settings.research_timeout_seconds == 300
        assert settings.wecom_app_corp_id == "ww-test"
        assert settings.wecom_app_secret == "secret-test"
        assert settings.wecom_app_agent_id == 1000002


def test_settings_research_defaults_are_disabled():
    """验证未配置 Redis 和自建应用时研究功能默认关闭"""
    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test-key"}, clear=True):
        from src.config import Settings

        settings = Settings(_env_file=None)
        assert settings.research_enabled is False
        assert settings.redis_url == "redis://127.0.0.1:6379/0"
        assert settings.research_queue_name == "butler-research"
        assert settings.research_max_rounds == 4
        assert settings.research_timeout_seconds == 300
        assert settings.wecom_app_corp_id == ""
        assert settings.wecom_app_secret == ""
        assert settings.wecom_app_agent_id == 0
```

Keep `test_legacy_self_built_app_env_is_ignored()` unchanged: legacy
`WECOM_CORP_ID` and `WECOM_CORP_SECRET` must still be ignored. The new names are
deliberately `WECOM_APP_*` to avoid reviving the retired callback integration.

- [ ] **Step 2: Run the tests and confirm the new fields are missing**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_config.py -q
```

Expected: the two new tests fail with missing `Settings` attributes.

- [ ] **Step 3: Add dependencies and settings**

Add to `pyproject.toml` dependencies:

```toml
    "taskiq>=0.11.0",
    "taskiq-redis>=1.0.0",
    "redis>=5.0.0",
```

Add to `Settings` in `src/config.py`:

```python
    # 异步研究任务配置；默认关闭，启用时要求 Redis 和企微自建应用配置
    research_enabled: bool = False
    redis_url: str = "redis://127.0.0.1:6379/0"
    research_queue_name: str = "butler-research"
    research_max_rounds: int = 4
    research_timeout_seconds: int = 300

    # 企业微信自建应用主动私聊配置，与智能机器人回调配置相互独立
    wecom_app_corp_id: str = ""
    wecom_app_secret: str = ""
    wecom_app_agent_id: int = 0
```

- [ ] **Step 4: Lock dependencies and rerun config tests**

Run:

```bash
uv sync
DEEPSEEK_API_KEY=test uv run pytest tests/test_config.py -q
```

Expected: config tests pass and `uv.lock` contains Taskiq, taskiq-redis, and redis.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/config.py tests/test_config.py
git commit -m "feat: add research queue and WeCom app configuration"
```

---

### Task 2: Add Durable Research Models

**Files:**
- Create: `src/models/research.py`
- Modify: `src/models/__init__.py`
- Create: `tests/test_research_models.py`

- [ ] **Step 1: Write failing metadata and constraint tests**

Create `tests/test_research_models.py`:

```python
"""
研究任务 ORM 测试
验证研究任务、报告、投递、群权限和企微用户绑定表已注册。
"""
from sqlalchemy import inspect

from src.db.base import Base


def test_research_tables_are_registered():
    """验证研究基础设施表全部注册到 SQLAlchemy metadata"""
    expected = {
        "research_tasks",
        "research_reports",
        "research_deliveries",
        "user_group_access",
        "wecom_user_bindings",
    }
    assert expected <= set(Base.metadata.tables)


def test_research_task_has_idempotency_and_user_status_indexes():
    """验证研究任务具备回调幂等和用户运行状态索引"""
    table = Base.metadata.tables["research_tasks"]
    assert table.c.source_msgid.unique is True
    index_columns = {
        tuple(column.name for column in index.columns)
        for index in table.indexes
    }
    assert ("requester_open_userid", "status") in index_columns


def test_research_report_version_is_unique_per_task():
    """验证同一任务的报告版本不可重复"""
    table = Base.metadata.tables["research_reports"]
    constraints = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if hasattr(constraint, "columns")
    }
    assert ("task_id", "version") in constraints
```

- [ ] **Step 2: Run the test and verify table registration fails**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_research_models.py -q
```

Expected: FAIL because the tables do not exist.

- [ ] **Step 3: Create the ORM models**

Create `src/models/research.py`:

```python
"""
异步研究任务 ORM 模型
持久化任务、报告、独立投递状态、群知识授权和企微用户身份映射。

Workflow:
1. 私聊提交写入 ResearchTask
2. Worker 生成 ResearchReport
3. 独立投递任务更新 ResearchDelivery
4. WeComUserBinding 缓存 open_userid 到 userid 的受控转换
5. UserGroupAccess 为后续群知识库检索提供管理员授权
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base


def _utcnow() -> datetime:
    """返回带 UTC 时区的当前时间"""
    return datetime.now(timezone.utc)


class ResearchTask(Base):
    """研究任务主表"""

    __tablename__ = "research_tasks"
    __table_args__ = (
        Index("ix_research_tasks_user_status", "requester_open_userid", "status"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_msgid: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True
    )
    requester_open_userid: Mapped[str] = mapped_column(
        String(256), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    research_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="foundation"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="queued", index=True
    )
    access_scope: Mapped[dict] = mapped_column(JSON, nullable=False)
    max_rounds: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    current_round: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    enqueued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class ResearchReport(Base):
    """研究报告版本表"""

    __tablename__ = "research_reports"
    __table_args__ = (
        UniqueConstraint("task_id", "version", name="uq_research_report_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("research_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    quality_status: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class ResearchDelivery(Base):
    """研究报告主动私聊投递状态"""

    __tablename__ = "research_deliveries"

    task_id: Mapped[str] = mapped_column(
        ForeignKey("research_tasks.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending", index=True
    )
    recipient_userid: Mapped[str | None] = mapped_column(String(256), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wecom_msgid: Mapped[str | None] = mapped_column(String(256), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class UserGroupAccess(Base):
    """管理员维护的用户群知识库授权"""

    __tablename__ = "user_group_access"
    __table_args__ = (
        UniqueConstraint("user_id", "group_id", name="uq_user_group_access"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    group_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class WeComUserBinding(Base):
    """智能机器人 open_userid 到自建应用 userid 的映射"""

    __tablename__ = "wecom_user_bindings"

    open_userid: Mapped[str] = mapped_column(String(256), primary_key=True)
    userid: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active"
    )
    converted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
```

Register all five models in `src/models/__init__.py` and add them to `__all__`.

- [ ] **Step 4: Run model tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_research_models.py tests/test_db.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/models/research.py src/models/__init__.py tests/test_research_models.py
git commit -m "feat: add durable research task models"
```

---

### Task 3: Implement Task Lifecycle, Idempotency, and Per-User Concurrency

**Files:**
- Create: `src/research/__init__.py`
- Create: `src/research/schemas.py`
- Create: `src/research/service.py`
- Create: `tests/test_research_service.py`

- [ ] **Step 1: Write failing service tests**

Create `tests/test_research_service.py` with these tests:

```python
"""
研究任务服务测试
验证任务创建幂等、每用户单任务限制、状态转换和报告查询。
"""
import pytest

from src.research.schemas import ResearchTaskStatus
from src.research.service import ResearchTaskService, UserResearchBusyError


@pytest.mark.asyncio
async def test_create_task_is_idempotent_by_source_msgid(db_session):
    """同一回调 msgid 只能创建一个任务"""
    service = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    first, created_first = await service.create_task(
        db_session,
        source_msgid="msg-1",
        requester_open_userid="open-u1",
        question="比较三个知识库方案",
    )
    second, created_second = await service.create_task(
        db_session,
        source_msgid="msg-1",
        requester_open_userid="open-u1",
        question="这段文本应被幂等忽略",
    )
    assert created_first is True
    assert created_second is False
    assert second.id == first.id
    assert second.question == "比较三个知识库方案"


@pytest.mark.asyncio
async def test_create_task_rejects_second_active_task_for_same_user(db_session):
    """同一用户已有运行任务时拒绝创建第二个任务"""
    service = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    await service.create_task(
        db_session,
        source_msgid="msg-1",
        requester_open_userid="open-u1",
        question="任务一",
    )
    with pytest.raises(UserResearchBusyError):
        await service.create_task(
            db_session,
            source_msgid="msg-2",
            requester_open_userid="open-u1",
            question="任务二",
        )


@pytest.mark.asyncio
async def test_mark_running_and_complete_persist_report(db_session):
    """任务可进入运行状态并以 unreviewed_foundation 报告完成"""
    service = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    task, _ = await service.create_task(
        db_session,
        source_msgid="msg-1",
        requester_open_userid="open-u1",
        question="研究问题",
    )
    await service.mark_running(db_session, task.id)
    report = await service.complete_with_report(
        db_session,
        task.id,
        summary="摘要",
        body="正文",
        quality_status="unreviewed_foundation",
    )
    refreshed = await service.get_task(db_session, task.id)
    assert refreshed.status == ResearchTaskStatus.COMPLETED.value
    assert refreshed.quality_status == "unreviewed_foundation"
    assert report.version == 1


@pytest.mark.asyncio
async def test_get_user_task_rejects_other_user(db_session):
    """用户不能查看其他用户的研究任务"""
    service = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    task, _ = await service.create_task(
        db_session,
        source_msgid="msg-1",
        requester_open_userid="open-u1",
        question="研究问题",
    )
    assert await service.get_user_task(db_session, task.id, "open-u2") is None
```

- [ ] **Step 2: Run tests and verify imports fail**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_research_service.py -q
```

Expected: FAIL because `src.research` does not exist.

- [ ] **Step 3: Add schemas**

Create `src/research/schemas.py`:

```python
"""
研究任务共享数据结构
定义任务、投递和质量状态，供服务、Worker 和私聊入口共享。
"""
from dataclasses import dataclass
from enum import StrEnum


class ResearchTaskStatus(StrEnum):
    """研究任务状态"""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class ResearchDeliveryStatus(StrEnum):
    """研究报告投递状态"""

    PENDING = "pending"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    FAILED = "failed"


ACTIVE_RESEARCH_STATUSES = {
    ResearchTaskStatus.QUEUED.value,
    ResearchTaskStatus.RUNNING.value,
}


@dataclass(frozen=True)
class ResearchReportSnapshot:
    """供投递层使用的报告快照"""

    task_id: str
    requester_open_userid: str
    question: str
    summary: str
    body: str
    quality_status: str
```

- [ ] **Step 4: Implement the service**

Create `src/research/service.py`:

```python
"""
研究任务生命周期服务
负责创建、幂等、单用户并发限制、状态转换、报告持久化和权限化查询。
"""
from datetime import datetime, timezone
from secrets import token_hex

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.research import ResearchDelivery, ResearchReport, ResearchTask
from src.research.schemas import (
    ACTIVE_RESEARCH_STATUSES,
    ResearchReportSnapshot,
    ResearchTaskStatus,
)


class UserResearchBusyError(RuntimeError):
    """当前用户已有运行中的研究任务"""


class ResearchTaskNotFoundError(RuntimeError):
    """研究任务不存在"""


def _new_task_id() -> str:
    """生成用户可读、数据库稳定的研究任务 ID"""
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"R{date}-{token_hex(4).upper()}"


class ResearchTaskService:
    """研究任务持久化服务"""

    def __init__(self, max_rounds: int, timeout_seconds: int):
        """初始化默认预算"""
        self._max_rounds = max_rounds
        self._timeout_seconds = timeout_seconds

    async def create_task(
        self,
        db: AsyncSession,
        *,
        source_msgid: str,
        requester_open_userid: str,
        question: str,
    ) -> tuple[ResearchTask, bool]:
        """按回调 msgid 幂等创建任务，并限制每用户一个活动任务"""
        existing = (
            await db.execute(
                select(ResearchTask).where(ResearchTask.source_msgid == source_msgid)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing, False

        active = (
            await db.execute(
                select(ResearchTask).where(
                    ResearchTask.requester_open_userid == requester_open_userid,
                    ResearchTask.status.in_(ACTIVE_RESEARCH_STATUSES),
                )
            )
        ).scalar_one_or_none()
        if active is not None:
            raise UserResearchBusyError(active.id)

        task = ResearchTask(
            id=_new_task_id(),
            source_msgid=source_msgid,
            requester_open_userid=requester_open_userid,
            question=question.strip(),
            research_type="foundation",
            status=ResearchTaskStatus.QUEUED.value,
            access_scope={
                "public": True,
                "user_id": requester_open_userid,
                "group_ids": [],
                "web": True,
            },
            max_rounds=self._max_rounds,
            timeout_seconds=self._timeout_seconds,
        )
        db.add(task)
        await db.flush()
        db.add(ResearchDelivery(task_id=task.id, status="pending"))
        await db.flush()
        return task, True

    async def get_task(self, db: AsyncSession, task_id: str) -> ResearchTask:
        """按 ID 获取任务，不存在时抛出明确异常"""
        task = await db.get(ResearchTask, task_id)
        if task is None:
            raise ResearchTaskNotFoundError(task_id)
        return task

    async def get_user_task(
        self, db: AsyncSession, task_id: str, requester_open_userid: str
    ) -> ResearchTask | None:
        """只返回属于当前用户的任务"""
        return (
            await db.execute(
                select(ResearchTask).where(
                    ResearchTask.id == task_id,
                    ResearchTask.requester_open_userid == requester_open_userid,
                )
            )
        ).scalar_one_or_none()

    async def mark_running(self, db: AsyncSession, task_id: str) -> ResearchTask:
        """将 queued 任务标记为 running；已完成任务保持幂等"""
        task = await self.get_task(db, task_id)
        if task.status == ResearchTaskStatus.COMPLETED.value:
            return task
        task.status = ResearchTaskStatus.RUNNING.value
        task.started_at = task.started_at or datetime.now(timezone.utc)
        task.error = None
        await db.flush()
        return task

    async def mark_enqueued(self, db: AsyncSession, task_id: str) -> ResearchTask:
        """记录任务已成功提交到 Redis Stream"""
        task = await self.get_task(db, task_id)
        task.enqueued_at = task.enqueued_at or datetime.now(timezone.utc)
        await db.flush()
        return task

    async def complete_with_report(
        self,
        db: AsyncSession,
        task_id: str,
        *,
        summary: str,
        body: str,
        quality_status: str,
    ) -> ResearchReport:
        """创建首版报告并完成任务；重复执行返回已存在报告"""
        existing = (
            await db.execute(
                select(ResearchReport).where(
                    ResearchReport.task_id == task_id,
                    ResearchReport.version == 1,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        task = await self.get_task(db, task_id)
        report = ResearchReport(
            task_id=task_id,
            version=1,
            summary=summary,
            body=body,
            quality_status=quality_status,
        )
        db.add(report)
        task.status = ResearchTaskStatus.COMPLETED.value
        task.quality_status = quality_status
        task.completed_at = datetime.now(timezone.utc)
        task.error = None
        await db.flush()
        return report

    async def mark_failed(
        self, db: AsyncSession, task_id: str, error: str
    ) -> ResearchTask:
        """记录研究执行失败"""
        task = await self.get_task(db, task_id)
        task.status = ResearchTaskStatus.FAILED.value
        task.error = error[:1000]
        task.completed_at = datetime.now(timezone.utc)
        await db.flush()
        return task

    async def mark_timed_out(
        self, db: AsyncSession, task_id: str, error: str
    ) -> ResearchTask:
        """记录研究任务超过硬时间预算"""
        task = await self.get_task(db, task_id)
        task.status = ResearchTaskStatus.TIMED_OUT.value
        task.error = error[:1000]
        task.completed_at = datetime.now(timezone.utc)
        await db.flush()
        return task

    async def get_report_snapshot(
        self, db: AsyncSession, task_id: str
    ) -> ResearchReportSnapshot:
        """加载投递所需任务与首版报告"""
        task = await self.get_task(db, task_id)
        report = (
            await db.execute(
                select(ResearchReport).where(
                    ResearchReport.task_id == task_id,
                    ResearchReport.version == 1,
                )
            )
        ).scalar_one()
        return ResearchReportSnapshot(
            task_id=task.id,
            requester_open_userid=task.requester_open_userid,
            question=task.question,
            summary=report.summary,
            body=report.body,
            quality_status=report.quality_status,
        )
```

Create `src/research/__init__.py` exporting `ResearchTaskService`, `UserResearchBusyError`, and status enums.

- [ ] **Step 5: Run service tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_research_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/research tests/test_research_service.py
git commit -m "feat: add research task lifecycle service"
```

---

### Task 4: Add the Redis Stream Broker and Queue Adapter

**Files:**
- Create: `src/research/broker.py`
- Create: `src/research/queue.py`
- Create: `tests/test_research_queue.py`

- [ ] **Step 1: Write failing dispatcher tests**

Create `tests/test_research_queue.py`:

```python
"""
研究任务队列适配器测试
验证应用层只依赖 enqueue 接口，不依赖 Taskiq 返回结果。
"""
from unittest.mock import AsyncMock

import pytest

from src.research.queue import TaskiqResearchDispatcher


@pytest.mark.asyncio
async def test_dispatcher_enqueues_research_task():
    """研究 dispatcher 调用 Taskiq task 的 kiq"""
    task = AsyncMock()
    dispatcher = TaskiqResearchDispatcher(research_task=task, delivery_task=AsyncMock())
    await dispatcher.enqueue_research("R20260612-ABCDEF12")
    task.kiq.assert_awaited_once_with("R20260612-ABCDEF12")


@pytest.mark.asyncio
async def test_dispatcher_enqueues_delivery_separately():
    """报告投递使用独立 Taskiq task"""
    delivery = AsyncMock()
    dispatcher = TaskiqResearchDispatcher(
        research_task=AsyncMock(), delivery_task=delivery
    )
    await dispatcher.enqueue_delivery("R20260612-ABCDEF12")
    delivery.kiq.assert_awaited_once_with("R20260612-ABCDEF12")
```

- [ ] **Step 2: Run tests and verify modules are missing**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_research_queue.py -q
```

Expected: FAIL because queue modules do not exist.

- [ ] **Step 3: Create broker and dispatcher**

Create `src/research/broker.py`:

```python
"""
研究任务 Taskiq broker
使用 Redis Stream 提供消息确认，生产者和 Worker 共享此 broker 实例定义。
"""
from taskiq_redis import RedisStreamBroker

from src.config import settings


broker = RedisStreamBroker(
    url=settings.redis_url,
    queue_name=settings.research_queue_name,
)
"""研究任务 Redis Stream broker；业务结果不写 Taskiq result backend"""
```

Create `src/research/queue.py`:

```python
"""
研究任务队列适配层
隔离业务服务与 Taskiq，使测试和未来 broker 替换不影响任务服务。
"""
from typing import Protocol


class ResearchDispatcher(Protocol):
    """研究任务派发接口"""

    async def enqueue_research(self, task_id: str) -> None:
        """派发研究执行任务"""
        raise NotImplementedError

    async def enqueue_delivery(self, task_id: str) -> None:
        """派发独立报告投递任务"""
        raise NotImplementedError


class TaskiqResearchDispatcher:
    """Taskiq 派发实现"""

    def __init__(self, research_task, delivery_task):
        """注入已注册的 Taskiq task 对象"""
        self._research_task = research_task
        self._delivery_task = delivery_task

    async def enqueue_research(self, task_id: str) -> None:
        """把任务 ID 放入研究队列"""
        await self._research_task.kiq(task_id)

    async def enqueue_delivery(self, task_id: str) -> None:
        """把任务 ID 放入独立投递任务"""
        await self._delivery_task.kiq(task_id)
```

- [ ] **Step 4: Run queue tests and import smoke**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_research_queue.py -q
DEEPSEEK_API_KEY=test uv run python3 -c "from src.research.broker import broker; print(type(broker).__name__)"
```

Expected: tests pass and command prints `RedisStreamBroker` without connecting to Redis.

- [ ] **Step 5: Commit**

```bash
git add src/research/broker.py src/research/queue.py tests/test_research_queue.py
git commit -m "feat: add Redis Stream research dispatcher"
```

---

### Task 5: Implement Enterprise WeChat Custom-App Messaging

**Files:**
- Create: `src/wechat/app_client.py`
- Create: `tests/test_wecom_app_client.py`

- [ ] **Step 1: Write failing API-client tests**

Create `tests/test_wecom_app_client.py` covering:

```python
"""
企微自建应用消息客户端测试
验证 token 缓存、open_userid 转换、业务错误和主动文本消息。
"""
from unittest.mock import AsyncMock

import pytest

from src.wechat.app_client import WeComAppApiError, WeComAppMessageClient


@pytest.mark.asyncio
async def test_client_reuses_cached_access_token():
    """缓存命中时不调用 gettoken"""
    cache = AsyncMock()
    cache.get.return_value = "cached-token"
    get_json = AsyncMock()
    client = WeComAppMessageClient(
        corp_id="ww-test",
        secret="secret",
        agent_id=1000002,
        cache=cache,
        get_json=get_json,
        post_json=AsyncMock(),
    )
    assert await client.get_access_token() == "cached-token"
    get_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_client_fetches_and_caches_access_token():
    """缓存未命中时获取 token，并以 expires_in-300 缓存"""
    cache = AsyncMock()
    cache.get.return_value = None
    get_json = AsyncMock(
        return_value={"errcode": 0, "access_token": "new-token", "expires_in": 7200}
    )
    client = WeComAppMessageClient(
        corp_id="ww-test",
        secret="secret",
        agent_id=1000002,
        cache=cache,
        get_json=get_json,
        post_json=AsyncMock(),
    )
    assert await client.get_access_token() == "new-token"
    cache.set.assert_awaited_once_with(
        "wecom:app:ww-test:1000002:access_token", "new-token", 6900
    )


@pytest.mark.asyncio
async def test_convert_open_userid_returns_plain_userid():
    """转换接口返回自建应用可发送的明文 userid"""
    cache = AsyncMock()
    cache.get.return_value = "token"
    post_json = AsyncMock(
        return_value={
            "errcode": 0,
            "userid_list": [{"open_userid": "open-u1", "userid": "u1"}],
            "invalid_open_userid_list": [],
        }
    )
    client = WeComAppMessageClient(
        corp_id="ww-test",
        secret="secret",
        agent_id=1000002,
        cache=cache,
        get_json=AsyncMock(),
        post_json=post_json,
    )
    assert await client.convert_open_userid("open-u1") == "u1"


@pytest.mark.asyncio
async def test_send_text_rejects_http_200_business_failure():
    """HTTP 200 但 errcode 非零时必须抛出业务异常"""
    cache = AsyncMock()
    cache.get.return_value = "token"
    client = WeComAppMessageClient(
        corp_id="ww-test",
        secret="secret",
        agent_id=1000002,
        cache=cache,
        get_json=AsyncMock(),
        post_json=AsyncMock(return_value={"errcode": 81013, "errmsg": "invalid user"}),
    )
    with pytest.raises(WeComAppApiError):
        await client.send_text("u1", "完成")


@pytest.mark.asyncio
async def test_send_text_rejects_invaliduser_and_unlicenseduser():
    """部分无效收件人也不能视为单用户投递成功"""
    cache = AsyncMock()
    cache.get.return_value = "token"
    for response in (
        {"errcode": 0, "invaliduser": "u1", "unlicenseduser": ""},
        {"errcode": 0, "invaliduser": "", "unlicenseduser": "u1"},
    ):
        client = WeComAppMessageClient(
            corp_id="ww-test",
            secret="secret",
            agent_id=1000002,
            cache=cache,
            get_json=AsyncMock(),
            post_json=AsyncMock(return_value=response),
        )
        with pytest.raises(WeComAppApiError):
            await client.send_text("u1", "完成")


@pytest.mark.asyncio
async def test_send_text_refreshes_expired_token_once():
    """token 失效业务码触发一次缓存清理和刷新"""
    cache = AsyncMock()
    cache.get.side_effect = ["expired-token", None]
    get_json = AsyncMock(
        return_value={"errcode": 0, "access_token": "fresh-token", "expires_in": 7200}
    )
    post_json = AsyncMock(
        side_effect=[
            {"errcode": 42001, "errmsg": "access_token expired"},
            {"errcode": 0, "errmsg": "ok", "msgid": "msg-1"},
        ]
    )
    client = WeComAppMessageClient(
        corp_id="ww-test",
        secret="secret",
        agent_id=1000002,
        cache=cache,
        get_json=get_json,
        post_json=post_json,
    )
    assert await client.send_text("u1", "完成") == "msg-1"
    cache.delete.assert_awaited_once()
```

- [ ] **Step 2: Run tests and verify the client is missing**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_wecom_app_client.py -q
```

Expected: FAIL on import.

- [ ] **Step 3: Implement the client**

Create `src/wechat/app_client.py`:

```python
"""
企业微信自建应用主动消息客户端
缓存 access_token、转换智能机器人 open_userid，并发送应用文本消息。
"""
from collections.abc import Awaitable, Callable
from typing import Protocol

import httpx


class AccessTokenCache(Protocol):
    """access_token 缓存接口"""

    async def get(self, key: str) -> str | None:
        """读取缓存值"""
        raise NotImplementedError

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        """按 TTL 保存缓存值"""
        raise NotImplementedError

    async def delete(self, key: str) -> None:
        """删除失效缓存值"""
        raise NotImplementedError


class RedisAccessTokenCache:
    """基于 redis.asyncio 的 access_token 缓存"""

    def __init__(self, redis_client):
        """注入 Redis 客户端"""
        self._redis = redis_client

    async def get(self, key: str) -> str | None:
        """读取并解码 token"""
        value = await self._redis.get(key)
        if value is None:
            return None
        return value.decode() if isinstance(value, bytes) else str(value)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        """保存带 TTL 的 token"""
        await self._redis.set(key, value, ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        """删除 token"""
        await self._redis.delete(key)


class WeComAppApiError(RuntimeError):
    """企业微信自建应用 API 业务错误"""


GetJson = Callable[[str, dict], Awaitable[dict]]
PostJson = Callable[[str, dict, dict], Awaitable[dict]]


class WeComAppMessageClient:
    """企业微信自建应用主动消息客户端"""

    def __init__(
        self,
        *,
        corp_id: str,
        secret: str,
        agent_id: int,
        cache: AccessTokenCache,
        get_json: GetJson | None = None,
        post_json: PostJson | None = None,
    ):
        """初始化凭据、缓存和可注入 HTTP 函数"""
        self._corp_id = corp_id
        self._secret = secret
        self._agent_id = agent_id
        self._cache = cache
        self._get_json = get_json
        self._post_json = post_json
        self._token_key = f"wecom:app:{corp_id}:{agent_id}:access_token"

    async def get_access_token(self, force_refresh: bool = False) -> str:
        """读取缓存或调用 gettoken；提前 300 秒过期"""
        if not force_refresh:
            cached = await self._cache.get(self._token_key)
            if cached:
                return cached
        response = await self._get(
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
            {"corpid": self._corp_id, "corpsecret": self._secret},
        )
        self._ensure_ok(response)
        token = str(response.get("access_token", ""))
        if not token:
            raise WeComAppApiError("gettoken response missing access_token")
        ttl = max(60, int(response.get("expires_in", 7200)) - 300)
        await self._cache.set(self._token_key, token, ttl)
        return token

    async def convert_open_userid(self, open_userid: str) -> str:
        """把智能机器人 open_userid 转换为自建应用 userid"""
        response = await self._post_with_token_retry(
            "https://qyapi.weixin.qq.com/cgi-bin/batch/openuserid_to_userid",
            {"open_userid_list": [open_userid]},
        )
        self._ensure_ok(response)
        if open_userid in response.get("invalid_open_userid_list", []):
            raise WeComAppApiError("open_userid is invalid or outside app visibility")
        for item in response.get("userid_list", []):
            if item.get("open_userid") == open_userid and item.get("userid"):
                return str(item["userid"])
        raise WeComAppApiError("open_userid conversion returned no userid")

    async def send_text(self, userid: str, content: str) -> str:
        """向单个成员发送应用文本消息并返回 msgid"""
        response = await self._post_with_token_retry(
            "https://qyapi.weixin.qq.com/cgi-bin/message/send",
            {
                "touser": userid,
                "msgtype": "text",
                "agentid": self._agent_id,
                "text": {"content": self._truncate_utf8(content, 2048)},
                "enable_duplicate_check": 1,
                "duplicate_check_interval": 1800,
            },
        )
        self._ensure_ok(response)
        if response.get("invaliduser") or response.get("unlicenseduser"):
            raise WeComAppApiError(
                "recipient is invalid, outside visibility, or unlicensed"
            )
        return str(response.get("msgid", ""))

    async def _post_with_token_retry(self, url: str, payload: dict) -> dict:
        """token 失效时清缓存并只重试一次"""
        for attempt in range(2):
            token = await self.get_access_token(force_refresh=attempt == 1)
            response = await self._post(
                url, {"access_token": token}, payload
            )
            if int(response.get("errcode", -1)) not in {40014, 42001}:
                return response
            await self._cache.delete(self._token_key)
        return response

    @staticmethod
    def _truncate_utf8(content: str, max_bytes: int) -> str:
        """按 UTF-8 字节上限截断文本，避免切断多字节字符"""
        encoded = content.encode("utf-8")
        if len(encoded) <= max_bytes:
            return content
        return encoded[:max_bytes].decode("utf-8", errors="ignore")

    async def _get(self, url: str, params: dict) -> dict:
        """执行 JSON GET"""
        if self._get_json is not None:
            return await self._get_json(url, params)
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    async def _post(self, url: str, params: dict, payload: dict) -> dict:
        """执行 JSON POST"""
        if self._post_json is not None:
            return await self._post_json(url, params, payload)
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, params=params, json=payload)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _ensure_ok(response: dict) -> None:
        """检查企业微信业务 errcode"""
        if int(response.get("errcode", -1)) != 0:
            raise WeComAppApiError(
                f"WeCom API failed: {response.get('errcode')} {response.get('errmsg', '')}"
            )
```

- [ ] **Step 4: Run client tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_wecom_app_client.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/wechat/app_client.py tests/test_wecom_app_client.py
git commit -m "feat: add WeCom custom-app message client"
```

---

### Task 6: Add Foundation Draft Execution

**Files:**
- Create: `src/research/executor.py`
- Create: `tests/test_research_executor.py`

- [ ] **Step 1: Write failing executor tests**

Create `tests/test_research_executor.py`:

```python
"""
Phase 1 研究执行器测试
验证 Worker 生成明确标记为未审核的单次 LLM 初稿，并保持幂等。
"""
from unittest.mock import AsyncMock

import pytest

from src.research.executor import FoundationResearchExecutor
from src.research.service import ResearchTaskService


@pytest.mark.asyncio
async def test_executor_persists_unreviewed_foundation_report(db_session):
    """执行器生成初稿并完成任务"""
    service = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    task, _ = await service.create_task(
        db_session,
        source_msgid="msg-1",
        requester_open_userid="open-u1",
        question="比较 Taskiq 与 Celery",
    )
    llm = AsyncMock()
    llm.chat.return_value = "## 初步结论\nTaskiq 更贴近异步项目。"
    executor = FoundationResearchExecutor(service, llm)

    report = await executor.execute(db_session, task.id)

    assert report.quality_status == "unreviewed_foundation"
    assert report.body.startswith("## 初步结论")
    llm.chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_executor_is_idempotent_after_report_exists(db_session):
    """重复投递同一任务不会重复调用 LLM 或创建第二份报告"""
    service = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    task, _ = await service.create_task(
        db_session,
        source_msgid="msg-1",
        requester_open_userid="open-u1",
        question="研究问题",
    )
    llm = AsyncMock()
    llm.chat.return_value = "初稿"
    executor = FoundationResearchExecutor(service, llm)
    first = await executor.execute(db_session, task.id)
    second = await executor.execute(db_session, task.id)
    assert second.id == first.id
    assert llm.chat.await_count == 1
```

- [ ] **Step 2: Run tests and verify executor is missing**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_research_executor.py -q
```

Expected: FAIL on import.

- [ ] **Step 3: Implement the executor**

Create `src/research/executor.py`:

```python
"""
Phase 1 研究执行器
在独立 Worker 中生成单次 LLM 初稿；不检索、不引用、不声称已经审核。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.research import ResearchReport
from src.research.service import ResearchTaskService


FOUNDATION_PROMPT = """你正在生成异步研究能力 Phase 1 的初步草稿。

要求：
- 回答用户问题并给出清晰结构；
- 明确区分事实、推断和建议；
- 不要伪造引用、链接或检索过程；
- 不要声称已经进行多来源研究或独立审核；
- 如果依赖最新资料，请明确写出“需要下一阶段联网检索核验”。

用户问题：
{question}
"""


class FoundationResearchExecutor:
    """单次 LLM 初稿执行器"""

    def __init__(self, task_service: ResearchTaskService, llm):
        """注入任务服务和 LLMClient"""
        self._tasks = task_service
        self._llm = llm

    async def execute(self, db: AsyncSession, task_id: str) -> ResearchReport:
        """幂等生成并持久化 unreviewed_foundation 报告"""
        existing = (
            await db.execute(
                select(ResearchReport).where(
                    ResearchReport.task_id == task_id,
                    ResearchReport.version == 1,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        task = await self._tasks.mark_running(db, task_id)
        body = await self._llm.chat(
            messages=[
                {
                    "role": "system",
                    "content": FOUNDATION_PROMPT.format(question=task.question),
                },
                {"role": "user", "content": task.question},
            ],
            temperature=0.3,
        )
        clean_body = body.strip() or "未生成有效初稿。"
        summary = clean_body.replace("\n", " ")[:240]
        return await self._tasks.complete_with_report(
            db,
            task_id,
            summary=summary,
            body=clean_body,
            quality_status="unreviewed_foundation",
        )
```

- [ ] **Step 4: Run executor tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_research_executor.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/research/executor.py tests/test_research_executor.py
git commit -m "feat: add foundation research draft executor"
```

---

### Task 7: Implement Identity Binding and Independent Delivery

**Files:**
- Create: `src/research/delivery.py`
- Create: `tests/test_research_delivery.py`

- [ ] **Step 1: Write failing delivery tests**

Create `tests/test_research_delivery.py`:

```python
"""
研究报告投递服务测试
验证企微身份映射、失败隔离和投递幂等。
"""
from unittest.mock import AsyncMock

import pytest

from src.models.research import ResearchDelivery, ResearchTask, WeComUserBinding
from src.research.delivery import ResearchDeliveryService
from src.research.service import ResearchTaskService


async def _completed_task(db_session):
    """创建带首版报告的已完成任务"""
    tasks = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    task, _ = await tasks.create_task(
        db_session,
        source_msgid="msg-delivery",
        requester_open_userid="open-u1",
        question="比较 Taskiq 和 Celery",
    )
    await tasks.complete_with_report(
        db_session,
        task.id,
        summary="Taskiq 更贴近 async 项目。",
        body="完整初稿",
        quality_status="unreviewed_foundation",
    )
    return tasks, task


@pytest.mark.asyncio
async def test_delivery_converts_and_persists_user_binding(db_session):
    """首次投递转换 open_userid，保存绑定并发送消息"""
    tasks, task = await _completed_task(db_session)
    client = AsyncMock()
    client.convert_open_userid.return_value = "plain-u1"
    client.send_text.return_value = "wecom-msg-1"
    service = ResearchDeliveryService(tasks, client)

    delivery = await service.deliver(db_session, task.id)

    binding = await db_session.get(WeComUserBinding, "open-u1")
    assert binding.userid == "plain-u1"
    assert delivery.status == "delivered"
    assert delivery.wecom_msgid == "wecom-msg-1"
    client.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_delivery_reuses_existing_binding(db_session):
    """已有 active 绑定时不重复调用转换接口"""
    tasks, task = await _completed_task(db_session)
    db_session.add(
        WeComUserBinding(
            open_userid="open-u1",
            userid="plain-u1",
            status="active",
        )
    )
    await db_session.flush()
    client = AsyncMock()
    client.send_text.return_value = "wecom-msg-1"

    await ResearchDeliveryService(tasks, client).deliver(db_session, task.id)

    client.convert_open_userid.assert_not_awaited()
    client.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_delivery_failure_preserves_completed_report(db_session):
    """主动推送失败只标记 delivery failed，不改变 research task completed"""
    tasks, task = await _completed_task(db_session)
    client = AsyncMock()
    client.convert_open_userid.return_value = "plain-u1"
    client.send_text.side_effect = RuntimeError("network down")

    with pytest.raises(RuntimeError, match="network down"):
        await ResearchDeliveryService(tasks, client).deliver(db_session, task.id)

    delivery = await db_session.get(ResearchDelivery, task.id)
    refreshed_task = await db_session.get(ResearchTask, task.id)
    assert delivery.status == "failed"
    assert refreshed_task.status == "completed"


@pytest.mark.asyncio
async def test_delivery_is_idempotent_after_delivered(db_session):
    """已投递任务不会重复发送"""
    tasks, task = await _completed_task(db_session)
    client = AsyncMock()
    client.convert_open_userid.return_value = "plain-u1"
    client.send_text.return_value = "wecom-msg-1"
    service = ResearchDeliveryService(tasks, client)
    await service.deliver(db_session, task.id)
    await service.deliver(db_session, task.id)
    assert client.send_text.await_count == 1
```

- [ ] **Step 2: Run tests and verify delivery module is missing**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_research_delivery.py -q
```

Expected: FAIL on import.

- [ ] **Step 3: Implement delivery service**

Create `src/research/delivery.py` with:

```python
"""
研究报告主动私聊投递服务
解析并缓存企微身份映射，独立维护投递状态，失败不回滚研究报告。
"""
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.research import ResearchDelivery, WeComUserBinding
from src.research.schemas import ResearchDeliveryStatus
from src.research.service import ResearchTaskService


class ResearchDeliveryService:
    """研究报告主动投递服务"""

    def __init__(self, task_service: ResearchTaskService, app_client):
        """注入任务服务和企微自建应用客户端"""
        self._tasks = task_service
        self._client = app_client

    async def deliver(self, db: AsyncSession, task_id: str) -> ResearchDelivery:
        """幂等投递报告；失败只更新 delivery 状态"""
        delivery = await db.get(ResearchDelivery, task_id)
        if delivery is None:
            delivery = ResearchDelivery(task_id=task_id, status="pending")
            db.add(delivery)
            await db.flush()
        if delivery.status == ResearchDeliveryStatus.DELIVERED.value:
            return delivery

        snapshot = await self._tasks.get_report_snapshot(db, task_id)
        binding = await db.get(WeComUserBinding, snapshot.requester_open_userid)
        if binding is None or binding.status != "active":
            userid = await self._client.convert_open_userid(
                snapshot.requester_open_userid
            )
            binding = WeComUserBinding(
                open_userid=snapshot.requester_open_userid,
                userid=userid,
                status="active",
                converted_at=datetime.now(timezone.utc),
            )
            await db.merge(binding)
        else:
            userid = binding.userid

        delivery.status = ResearchDeliveryStatus.DELIVERING.value
        delivery.recipient_userid = userid
        delivery.attempts += 1
        delivery.error = None
        await db.flush()

        content = (
            f"研究任务 {snapshot.task_id} 已完成\n"
            f"问题：{snapshot.question}\n"
            f"质量状态：{snapshot.quality_status}\n\n"
            f"{snapshot.summary}\n\n"
            "当前为 Phase 1 单次 LLM 初稿，尚未进行多来源检索、逐项引用和独立审核。"
        )
        try:
            delivery.wecom_msgid = await self._client.send_text(userid, content)
        except Exception as exc:
            delivery.status = ResearchDeliveryStatus.FAILED.value
            delivery.error = str(exc)[:1000]
            await db.flush()
            raise

        delivery.status = ResearchDeliveryStatus.DELIVERED.value
        delivery.delivered_at = datetime.now(timezone.utc)
        await db.flush()
        return delivery
```

The test must confirm the task remains `completed` after delivery raises.

- [ ] **Step 4: Run delivery tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_research_delivery.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/research/delivery.py tests/test_research_delivery.py
git commit -m "feat: add independent research report delivery"
```

---

### Task 8: Register Thin Taskiq Worker Tasks

**Files:**
- Create: `src/research/tasks.py`
- Create: `tests/test_research_tasks.py`

- [ ] **Step 1: Write failing worker orchestration tests**

Create `tests/test_research_tasks.py`:

```python
"""
Taskiq 核心任务函数测试
不连接 Redis，验证研究、超时、失败和独立投递重试。
"""
import asyncio
from unittest.mock import AsyncMock

import pytest

from src.research.tasks import execute_delivery_job, execute_research_job


class _SessionContext:
    """复用 pytest AsyncSession 的测试上下文"""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        """返回测试会话"""
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        """不关闭 fixture 管理的会话"""
        return False


def _session_factory(session):
    """构造兼容 worker 的会话工厂"""
    return lambda: _SessionContext(session)


@pytest.mark.asyncio
async def test_execute_research_job_commits_report_then_enqueues_delivery(db_session):
    """研究任务提交报告后单独派发 delivery"""
    executor = AsyncMock()
    dispatcher = AsyncMock()
    task_service = AsyncMock()

    await execute_research_job(
        "R20260612-ABCDEF12",
        session_factory=_session_factory(db_session),
        executor=executor,
        dispatcher=dispatcher,
        task_service=task_service,
        timeout_seconds=300,
    )

    executor.execute.assert_awaited_once_with(
        db_session, "R20260612-ABCDEF12"
    )
    dispatcher.enqueue_delivery.assert_awaited_once_with(
        "R20260612-ABCDEF12"
    )
    task_service.mark_failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_research_job_marks_failure_and_does_not_enqueue_delivery(
    db_session,
):
    """研究执行失败时记录失败且不投递"""
    executor = AsyncMock()
    executor.execute.side_effect = RuntimeError("llm down")
    dispatcher = AsyncMock()
    task_service = AsyncMock()

    with pytest.raises(RuntimeError, match="llm down"):
        await execute_research_job(
            "R20260612-ABCDEF12",
            session_factory=_session_factory(db_session),
            executor=executor,
            dispatcher=dispatcher,
            task_service=task_service,
            timeout_seconds=300,
        )

    task_service.mark_failed.assert_awaited_once()
    dispatcher.enqueue_delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_research_job_marks_timeout(db_session):
    """超过硬预算时记录 timed_out 而不是普通 failed"""
    async def never_finishes(db, task_id):
        """模拟超时任务"""
        await asyncio.sleep(1)

    executor = AsyncMock()
    executor.execute.side_effect = never_finishes
    dispatcher = AsyncMock()
    task_service = AsyncMock()

    with pytest.raises(TimeoutError):
        await execute_research_job(
            "R20260612-ABCDEF12",
            session_factory=_session_factory(db_session),
            executor=executor,
            dispatcher=dispatcher,
            task_service=task_service,
            timeout_seconds=0.001,
        )

    task_service.mark_timed_out.assert_awaited_once()
    task_service.mark_failed.assert_not_awaited()
    dispatcher.enqueue_delivery.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_delivery_job_retries_three_times(db_session):
    """投递瞬时失败最多尝试三次，不触发研究执行"""
    delivery_service = AsyncMock()
    delivery_service.deliver.side_effect = [
        RuntimeError("first"),
        RuntimeError("second"),
        None,
    ]
    sleep = AsyncMock()

    await execute_delivery_job(
        "R20260612-ABCDEF12",
        session_factory=_session_factory(db_session),
        delivery_service=delivery_service,
        sleep=sleep,
    )

    assert delivery_service.deliver.await_count == 3
    assert sleep.await_count == 2
```

- [ ] **Step 2: Implement testable core job functions and Taskiq wrappers**

Create `src/research/tasks.py`:

```python
"""
Taskiq 研究与投递任务
Taskiq wrapper 只接收 task_id；数据库会话和服务在 Worker 进程内重新创建。
"""
import asyncio

from redis.asyncio import Redis

from src.config import settings
from src.db.session import async_session
from src.llm.client import LLMClient
from src.research.broker import broker
from src.research.delivery import ResearchDeliveryService
from src.research.executor import FoundationResearchExecutor
from src.research.queue import TaskiqResearchDispatcher
from src.research.service import ResearchTaskService
from src.wechat.app_client import (
    RedisAccessTokenCache,
    WeComAppMessageClient,
)


async def execute_research_job(
    task_id: str,
    *,
    session_factory,
    executor,
    dispatcher,
    task_service,
    timeout_seconds,
) -> None:
    """执行研究、提交报告，再派发独立投递任务"""
    async with session_factory() as db:
        try:
            async with asyncio.timeout(timeout_seconds):
                await executor.execute(db, task_id)
            await db.commit()
        except TimeoutError:
            await db.rollback()
            async with session_factory() as timeout_db:
                await task_service.mark_timed_out(
                    timeout_db,
                    task_id,
                    f"research exceeded {timeout_seconds} seconds",
                )
                await timeout_db.commit()
            raise
        except Exception as exc:
            await db.rollback()
            async with session_factory() as failed_db:
                await task_service.mark_failed(failed_db, task_id, str(exc))
                await failed_db.commit()
            raise
    await dispatcher.enqueue_delivery(task_id)


async def execute_delivery_job(
    task_id: str,
    *,
    session_factory,
    delivery_service,
    sleep=asyncio.sleep,
) -> None:
    """独立投递，指数退避重试三次"""
    last_error: Exception | None = None
    for attempt, delay in enumerate((0, 1, 2), start=1):
        if delay:
            await sleep(delay)
        async with session_factory() as db:
            try:
                await delivery_service.deliver(db, task_id)
                await db.commit()
                return
            except Exception as exc:
                last_error = exc
                await db.commit()
    assert last_error is not None
    raise last_error


_task_service = ResearchTaskService(
    max_rounds=settings.research_max_rounds,
    timeout_seconds=settings.research_timeout_seconds,
)
_redis_client = Redis.from_url(settings.redis_url)
_app_client = WeComAppMessageClient(
    corp_id=settings.wecom_app_corp_id,
    secret=settings.wecom_app_secret,
    agent_id=settings.wecom_app_agent_id,
    cache=RedisAccessTokenCache(_redis_client),
)
_executor = FoundationResearchExecutor(_task_service, LLMClient())
_delivery_service = ResearchDeliveryService(_task_service, _app_client)


@broker.task(task_name="research.deliver")
async def deliver_research_task(task_id: str) -> None:
    """Taskiq 报告投递入口"""
    await execute_delivery_job(
        task_id,
        session_factory=async_session,
        delivery_service=_delivery_service,
    )


@broker.task(task_name="research.run")
async def run_research_task(task_id: str) -> None:
    """Taskiq 研究执行入口"""
    dispatcher = TaskiqResearchDispatcher(
        run_research_task, deliver_research_task
    )
    await execute_research_job(
        task_id,
        session_factory=async_session,
        executor=_executor,
        dispatcher=dispatcher,
        task_service=_task_service,
        timeout_seconds=settings.research_timeout_seconds,
    )
```

Keep `deliver_research_task` defined before `run_research_task`; do not solve
task registration or forward-reference errors by importing `src.main`.

- [ ] **Step 3: Run worker tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_research_tasks.py -q
```

Expected: PASS without a live Redis server.

- [ ] **Step 4: Verify Taskiq discovers both tasks**

Run with a local Redis instance:

```bash
redis-cli ping
DEEPSEEK_API_KEY=test uv run taskiq worker \
  --ack-type when_executed \
  --workers 1 \
  --max-async-tasks 1 \
  src.research.broker:broker src.research.tasks
```

Expected: worker starts, imports `research.run` and `research.deliver`, and waits for jobs. Stop it with Ctrl-C after the startup log is visible.

- [ ] **Step 5: Commit**

```bash
git add src/research/tasks.py tests/test_research_tasks.py
git commit -m "feat: add research and delivery worker tasks"
```

---

### Task 9: Add Private-Chat Submission and Status Lookup

**Files:**
- Create: `src/research/submission.py`
- Modify: `src/agents/private_butler/graph.py`
- Modify: `src/messaging/dispatch.py`
- Modify: `tests/test_butler_agent.py`
- Modify: `tests/test_messaging.py`
- Modify: `tests/test_aibot_callback.py`

- [ ] **Step 1: Write failing private-agent tests**

Add tests to `tests/test_butler_agent.py`:

```python
@pytest.mark.asyncio
async def test_private_butler_submits_explicit_deep_research(db_session):
    """“深度研究：”在私聊中创建异步任务并绕过 ReAct 图"""
    submitter = AsyncMock()
    submitter.submit.return_value = "已创建研究任务 R20260612-ABCDEF12。"
    agent = PrivateButlerAgent(
        llm_client=FakeToolCallingLLM([]),
        summary_agent=FakeAgent(),
        knowledge_service=AsyncMock(),
        web_search_service=AsyncMock(),
        research_submitter=submitter,
    )
    result = await agent.handle(
        "private_butler",
        "深度研究：比较 Taskiq 和 Celery",
        "open-u1",
        db_session,
        extra_state={"chat_type": "single", "source_msgid": "msg-r1"},
    )
    assert result.data == {"intent": "research_submit"}
    submitter.submit.assert_awaited_once_with(
        db_session,
        source_msgid="msg-r1",
        requester_open_userid="open-u1",
        question="比较 Taskiq 和 Celery",
    )


@pytest.mark.asyncio
async def test_private_butler_returns_research_status(db_session):
    """“查看研究任务 ID”只允许查询当前用户任务"""
    submitter = AsyncMock()
    submitter.status.return_value = "任务已完成。"
    agent = PrivateButlerAgent(
        llm_client=FakeToolCallingLLM([]),
        summary_agent=FakeAgent(),
        knowledge_service=AsyncMock(),
        web_search_service=AsyncMock(),
        research_submitter=submitter,
    )
    result = await agent.handle(
        "private_butler",
        "查看研究任务 R20260612-ABCDEF12",
        "open-u1",
        db_session,
        extra_state={"chat_type": "single", "source_msgid": "msg-status"},
    )
    assert result.data == {"intent": "research_status"}
```

Update exact-call assertions in `tests/test_messaging.py` and `tests/test_aibot_callback.py` to include:

```python
"source_msgid": message.msg_id
```

inside private `extra_state`.

- [ ] **Step 2: Run focused tests and confirm failure**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_butler_agent.py \
  tests/test_messaging.py \
  tests/test_aibot_callback.py -q
```

Expected: FAIL because the submitter parameter and `source_msgid` propagation do not exist.

- [ ] **Step 3: Add submission facade**

Create `src/research/submission.py`:

```python
"""
私聊研究任务提交与查询门面
把 PrivateButlerAgent 与持久化、队列派发隔离。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.research import ResearchReport
from src.research.service import ResearchTaskService, UserResearchBusyError


class ResearchSubmissionService:
    """私聊研究提交和状态查询服务"""

    def __init__(self, task_service: ResearchTaskService, dispatcher):
        """注入任务服务和队列派发器"""
        self._tasks = task_service
        self._dispatcher = dispatcher

    async def submit(
        self,
        db: AsyncSession,
        *,
        source_msgid: str,
        requester_open_userid: str,
        question: str,
    ) -> str:
        """创建并派发任务；重复回调返回同一任务 ID"""
        if not source_msgid:
            return "研究任务缺少消息标识，暂时无法可靠创建。"
        try:
            task, created = await self._tasks.create_task(
                db,
                source_msgid=source_msgid,
                requester_open_userid=requester_open_userid,
                question=question,
            )
        except UserResearchBusyError as exc:
            return f"你已有运行中的研究任务 {exc}，请完成后再提交新任务。"
        if created or task.enqueued_at is None:
            # 必须先提交数据库，再发布 task_id，避免 Worker 抢先读取不到任务。
            await db.commit()
            try:
                await self._dispatcher.enqueue_research(task.id)
                await self._tasks.mark_enqueued(db, task.id)
                await db.commit()
            except Exception as exc:
                await db.rollback()
                await self._tasks.mark_failed(
                    db, task.id, f"queue dispatch failed: {exc}"
                )
                await db.commit()
                return "研究任务入队失败，请稍后重新提交。"
        return (
            f"已创建研究任务 {task.id}。完成后会通过企微自建应用主动私聊通知。\n"
            "当前 Phase 1 输出为未审核初稿，不含多来源检索和逐项引用。"
        )

    async def status(
        self,
        db: AsyncSession,
        *,
        task_id: str,
        requester_open_userid: str,
    ) -> str:
        """查询当前用户自己的任务状态和已完成初稿"""
        task = await self._tasks.get_user_task(
            db, task_id.upper(), requester_open_userid
        )
        if task is None:
            return "没有找到属于你的该研究任务。"
        if task.status != "completed":
            detail = f"\n失败原因：{task.error}" if task.error else ""
            return f"研究任务 {task.id} 当前状态：{task.status}{detail}"
        report = (
            await db.execute(
                select(ResearchReport).where(
                    ResearchReport.task_id == task.id,
                    ResearchReport.version == 1,
                )
            )
        ).scalar_one()
        return (
            f"研究任务 {task.id} 已完成。\n"
            f"质量状态：{report.quality_status}\n\n{report.body}"
        )
```

- [ ] **Step 4: Add deterministic private-chat shortcuts**

In `src/agents/private_butler/graph.py`:

```python
_RESEARCH_SUBMIT_PATTERN = re.compile(r"^(?:深度研究|研究任务)[：:]\s*(.+)$", re.DOTALL)
_RESEARCH_STATUS_PATTERN = re.compile(
    r"^查看研究任务\s+(R\d{8}-[A-F0-9]{8})$", re.IGNORECASE
)
```

Add optional `research_submitter=None` to `PrivateButlerAgent.__init__`, store it, and before reminder routing in `handle()`:

```python
        if chat_type == "single" and self._research_submitter is not None:
            status_match = _RESEARCH_STATUS_PATTERN.match(message.strip())
            if status_match:
                reply = await self._research_submitter.status(
                    db,
                    task_id=status_match.group(1),
                    requester_open_userid=user_id,
                )
                return AgentResponse(reply=reply, data={"intent": "research_status"})

            submit_match = _RESEARCH_SUBMIT_PATTERN.match(message.strip())
            if submit_match:
                reply = await self._research_submitter.submit(
                    db,
                    source_msgid=(extra_state or {}).get("source_msgid", ""),
                    requester_open_userid=user_id,
                    question=submit_match.group(1).strip(),
                )
                return AgentResponse(reply=reply, data={"intent": "research_submit"})
```

Do not add research tools or routes to `GroupMentionAgent`.

In `src/messaging/dispatch.py`, change the private `extra_state` to:

```python
        extra_state={
            "chat_type": "single",
            "chat_id": message.chat_id,
            "source_msgid": message.msg_id,
        },
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_butler_agent.py \
  tests/test_messaging.py \
  tests/test_aibot_callback.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add \
  src/research/submission.py \
  src/agents/private_butler/graph.py \
  src/messaging/dispatch.py \
  tests/test_butler_agent.py \
  tests/test_messaging.py \
  tests/test_aibot_callback.py
git commit -m "feat: add private research submission and lookup"
```

---

### Task 10: Wire Producer Lifecycle and Worker Dependencies

**Files:**
- Modify: `src/main.py`
- Modify: `tests/test_smoke.py`

- [ ] **Step 1: Add a smoke test for disabled-by-default wiring**

Add to `tests/test_smoke.py`:

```python
def test_research_is_disabled_without_explicit_config():
    """默认配置下导入 app 不连接 Redis，私聊 agent 不具备研究 submitter"""
    from src.config import settings
    from src.main import private_butler_agent

    assert settings.research_enabled is False
    assert private_butler_agent._research_submitter is None
```

- [ ] **Step 2: Add conditional runtime wiring**

In `src/main.py`:

1. Construct `ResearchTaskService` for both enabled and disabled configurations.
2. Only import Taskiq task objects and construct `TaskiqResearchDispatcher` when `settings.research_enabled` is true.
3. Inject `ResearchSubmissionService` into `PrivateButlerAgent`.
4. In `lifespan`, call `await research_broker.startup()` before yielding and `await research_broker.shutdown()` during shutdown only when enabled.
5. Validate at startup that enabled research has non-empty `WECOM_APP_CORP_ID`, `WECOM_APP_SECRET`, and positive `WECOM_APP_AGENT_ID`; raise `RuntimeError` naming missing fields.

Use this shape:

```python
research_task_service = ResearchTaskService(
    max_rounds=settings.research_max_rounds,
    timeout_seconds=settings.research_timeout_seconds,
)
research_broker = None
research_submission_service = None

if settings.research_enabled:
    from src.research.broker import broker as research_broker
    from src.research.queue import TaskiqResearchDispatcher
    from src.research.submission import ResearchSubmissionService
    from src.research.tasks import deliver_research_task, run_research_task

    research_submission_service = ResearchSubmissionService(
        research_task_service,
        TaskiqResearchDispatcher(run_research_task, deliver_research_task),
    )
```

Pass `research_submitter=research_submission_service` into `PrivateButlerAgent`.

- [ ] **Step 3: Run smoke and full unit suite**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_smoke.py tests/test_butler_agent.py -q
DEEPSEEK_API_KEY=test uv run pytest -q
```

Expected: PASS without Redis because `RESEARCH_ENABLED` defaults to false.

- [ ] **Step 4: Commit**

```bash
git add src/main.py tests/test_smoke.py
git commit -m "feat: wire optional research producer lifecycle"
```

---

### Task 11: Add an End-to-End Foundation Test

**Files:**
- Create: `tests/test_research_foundation_flow.py`

- [ ] **Step 1: Build an integration test with in-process fakes**

Create `tests/test_research_foundation_flow.py`:

```python
"""
异步研究 Phase 1 端到端测试
使用真实服务和 ORM、假队列/LLM/企微客户端验证完整基础链路。
"""
import re
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from src.agents.private_butler import PrivateButlerAgent
from src.messaging import InboundMessage, dispatch_message
from src.models.research import ResearchDelivery, ResearchReport, ResearchTask
from src.research.delivery import ResearchDeliveryService
from src.research.executor import FoundationResearchExecutor
from src.research.service import ResearchTaskService
from src.research.submission import ResearchSubmissionService


class RecordingDispatcher:
    """记录研究和投递任务 ID 的内存 dispatcher"""

    def __init__(self):
        """初始化记录列表"""
        self.research_ids: list[str] = []
        self.delivery_ids: list[str] = []

    async def enqueue_research(self, task_id: str) -> None:
        """记录研究任务 ID"""
        self.research_ids.append(task_id)

    async def enqueue_delivery(self, task_id: str) -> None:
        """记录投递任务 ID"""
        self.delivery_ids.append(task_id)


@pytest.mark.asyncio
async def test_private_research_foundation_flow_is_durable_and_idempotent(
    db_session,
):
    """私聊提交、生成初稿、主动投递和重复回调形成完整闭环"""
    tasks = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    dispatcher = RecordingDispatcher()
    submitter = ResearchSubmissionService(tasks, dispatcher)
    private_agent = PrivateButlerAgent(
        llm_client=AsyncMock(),
        summary_agent=AsyncMock(),
        knowledge_service=AsyncMock(),
        web_search_service=AsyncMock(),
        research_submitter=submitter,
    )
    inbound = InboundMessage(
        source="wecom_callback",
        msg_id="msg-flow-1",
        msg_type="text",
        user_id="open-u1",
        content="深度研究：比较 Taskiq 和 Celery",
        chat_type="single",
        chat_id=None,
        response_url="https://example.test/reply",
        raw={},
    )

    first = await dispatch_message(
        inbound,
        db_session,
        private_agent=private_agent,
        group_agent=AsyncMock(),
    )
    duplicate = await dispatch_message(
        inbound,
        db_session,
        private_agent=private_agent,
        group_agent=AsyncMock(),
    )

    task_id = re.search(r"R\d{8}-[A-F0-9]{8}", first.reply).group(0)
    rows = (await db_session.execute(select(ResearchTask))).scalars().all()
    assert duplicate.reply == first.reply
    assert len(rows) == 1
    assert dispatcher.research_ids == [task_id]

    llm = AsyncMock()
    llm.chat.return_value = "## 初步结论\nTaskiq 更贴近 async 项目。"
    report = await FoundationResearchExecutor(tasks, llm).execute(
        db_session, task_id
    )
    assert report.quality_status == "unreviewed_foundation"

    app_client = AsyncMock()
    app_client.convert_open_userid.return_value = "plain-u1"
    app_client.send_text.return_value = "wecom-msg-1"
    delivery = await ResearchDeliveryService(tasks, app_client).deliver(
        db_session, task_id
    )
    assert delivery.status == "delivered"
    sent_content = app_client.send_text.await_args.args[1]
    assert "尚未进行多来源检索、逐项引用和独立审核" in sent_content

    stored_report = (
        await db_session.execute(
            select(ResearchReport).where(ResearchReport.task_id == task_id)
        )
    ).scalar_one()
    stored_delivery = await db_session.get(ResearchDelivery, task_id)
    assert stored_report.body.startswith("## 初步结论")
    assert stored_delivery.wecom_msgid == "wecom-msg-1"


@pytest.mark.asyncio
async def test_group_message_does_not_use_private_research_submitter(db_session):
    """群聊研究文本仍走群场景，不进入私聊研究队列"""
    dispatcher = RecordingDispatcher()
    tasks = ResearchTaskService(max_rounds=4, timeout_seconds=300)
    private_agent = AsyncMock()
    group_agent = AsyncMock()
    group_agent.handle.return_value.reply = "群聊不开放研究任务。"
    group_agent.handle.return_value.data = {"intent": "group_mention"}

    await dispatch_message(
        InboundMessage(
            source="wecom_callback",
            msg_id="msg-group-research",
            msg_type="text",
            user_id="open-u1",
            content="深度研究：比较 Taskiq 和 Celery",
            chat_type="group",
            chat_id="group-1",
            response_url="https://example.test/reply",
            raw={},
        ),
        db_session,
        private_agent=private_agent,
        group_agent=group_agent,
    )

    private_agent.handle.assert_not_awaited()
    assert dispatcher.research_ids == []
```

- [ ] **Step 2: Run the integration test**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_research_foundation_flow.py -q
```

Expected: PASS with no external network and no Redis.

- [ ] **Step 3: Commit**

```bash
git add tests/test_research_foundation_flow.py
git commit -m "test: cover asynchronous research foundation flow"
```

---

### Task 12: Update Runtime Documentation and Architecture Decisions

**Files:**
- Modify: `.env.example`
- Modify: `deployment.md`
- Modify: `deployment.en.md`
- Modify: `README.md`
- Modify: `README.en.md`
- Modify: `CLAUDE.md`
- Modify: `AGENTS.md`
- Modify: `docs/agent/active-context.md`
- Modify: `docs/agent/patterns.md`
- Modify: `docs/agent/decisions.md`
- Modify: `docs/agent/config-variables.md`
- Modify: `docs/agent/upgrade-roadmap.md`

- [ ] **Step 1: Document exact environment variables**

Add:

```env
# Phase 1 异步研究（默认关闭）
RESEARCH_ENABLED=false
REDIS_URL=redis://127.0.0.1:6379/0
RESEARCH_QUEUE_NAME=butler-research
RESEARCH_MAX_ROUNDS=4
RESEARCH_TIMEOUT_SECONDS=300

# 企业微信自建应用主动私聊；仅 RESEARCH_ENABLED=true 时必填
WECOM_APP_CORP_ID=
WECOM_APP_SECRET=
WECOM_APP_AGENT_ID=0
```

State explicitly that `WECOM_APP_*` is a proactive delivery integration and does not replace `WECOM_AIBOT_*` callback variables.

- [ ] **Step 2: Document local and production processes**

Add these commands to both deployment guides:

```bash
# Redis
redis-server

# API producer
uv run uvicorn src.main:app --host 127.0.0.1 --port 8000

# Research workers: total concurrency 3, one async job per child
uv run taskiq worker \
  --ack-type when_executed \
  --workers 3 \
  --max-async-tasks 1 \
  src.research.broker:broker src.research.tasks
```

Explain that API and worker processes use the same database. Phase 1 keeps SQLite for the approved small-team rollout, but operators must watch for `database is locked`; PostgreSQL remains the Phase 5 target.

- [ ] **Step 3: Update architecture and project memory**

Apply all of the following:

- Revise ADR-001 from single-process to “FastAPI API process plus optional Taskiq worker processes when research is enabled”.
- Amend ADR-012 to clarify that old `WECOM_CORP_ID/WECOM_CORP_SECRET` remain retired, while new `WECOM_APP_*` fields exist only for proactive custom-application delivery.
- Add a new ADR for Redis Stream + Taskiq, authoritative DB state, and separate delivery retries.
- Add a reusable async-research pattern to `docs/agent/patterns.md`.
- Add Phase 1 capability and explicit `unreviewed_foundation` limitation to `active-context.md`.
- Mark asynchronous foundation complete in `upgrade-roadmap.md`, leaving deterministic and multi-agent research pending.
- Add `src/research/`, Taskiq, Redis, custom-app delivery, and worker entry command to `CLAUDE.md`.
- Copy `CLAUDE.md` byte-for-byte to `AGENTS.md`.
- Update README trees and startup instructions.

- [ ] **Step 4: Verify mirrored docs and stale statements**

Run:

```bash
cmp -s CLAUDE.md AGENTS.md
rg -n "single-process|avoids Redis|不再暴露.*WECOM_APP|only inbound message API" \
  CLAUDE.md AGENTS.md README.md README.en.md deployment.md deployment.en.md docs/agent
```

Expected:

- `cmp` exits 0.
- No document claims that the enabled research deployment is single-process.
- No document confuses `WECOM_APP_*` with the retired callback integration.

- [ ] **Step 5: Commit**

```bash
git add \
  .env.example \
  deployment.md deployment.en.md \
  README.md README.en.md \
  CLAUDE.md AGENTS.md \
  docs/agent
git commit -m "docs: document asynchronous research foundation"
```

---

### Task 13: Verify the Phase 1 Exit Condition

**Files:**
- No new files unless verification reveals a defect.

- [ ] **Step 1: Run formatting and static repository checks**

Run:

```bash
git diff --check
cmp -s CLAUDE.md AGENTS.md
uv lock --check
```

Expected: all commands exit 0.

- [ ] **Step 2: Run focused research tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_models.py \
  tests/test_research_service.py \
  tests/test_research_queue.py \
  tests/test_wecom_app_client.py \
  tests/test_research_executor.py \
  tests/test_research_delivery.py \
  tests/test_research_tasks.py \
  tests/test_research_foundation_flow.py -q
```

Expected: all pass.

- [ ] **Step 3: Run the complete test suite**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest -q
```

Expected: all existing and new tests pass without real DeepSeek, Redis, or Enterprise WeChat calls.

- [ ] **Step 4: Perform a local Redis worker smoke test**

Start Redis, then:

```bash
RESEARCH_ENABLED=true \
DEEPSEEK_API_KEY=test \
WECOM_APP_CORP_ID=ww-test \
WECOM_APP_SECRET=test-secret \
WECOM_APP_AGENT_ID=1000002 \
uv run taskiq worker \
  --ack-type when_executed \
  --workers 1 \
  --max-async-tasks 1 \
  src.research.broker:broker src.research.tasks
```

Expected: worker starts and waits for tasks. This smoke test verifies broker/task discovery only; it must not send a real Enterprise WeChat message with fake credentials.

- [ ] **Step 5: Review Phase 1 acceptance criteria**

Confirm:

- Private chat explicitly submits `深度研究：<问题>`.
- Group chat has no research entry.
- Callback `msgid` provides task idempotency.
- One user cannot start two active tasks.
- Worker receives only `task_id`, then opens its own DB session.
- Research and delivery are separate queue tasks.
- Reports survive delivery failure.
- Delivery checks `errcode`, `invaliduser`, and `unlicenseduser`.
- The user can query a completed report even when push delivery fails.
- Every Phase 1 report is visibly marked `unreviewed_foundation`.
- No code claims that citation review or multi-agent research exists yet.

---

## Follow-On Plan Gates

Do not write or execute Phase 2 until Phase 1 has:

1. a green full test suite;
2. a successful real Redis enqueue/consume test;
3. one successful real `open_userid` conversion;
4. one successful custom-application private delivery;
5. confirmation that SQLite does not show unacceptable lock contention under three workers.

Phase 2 then replaces `FoundationResearchExecutor` with a deterministic LangGraph workflow while preserving `ResearchTaskService`, Taskiq task names, delivery isolation, and the private-chat interface.

## Primary References

- [Approved design](../specs/2026-06-12-multi-agent-research-upgrade-design.md)
- [Taskiq getting started](https://taskiq-python.github.io/guide/getting-started.html)
- [Taskiq CLI](https://taskiq-python.github.io/guide/cli.html)
- [Taskiq Redis Stream broker](https://github.com/taskiq-python/taskiq-redis)
- [Enterprise WeChat access token](https://developer.work.weixin.qq.com/document/path/91039)
- [Enterprise WeChat application messages](https://developer.work.weixin.qq.com/document/path/90236)
- [Enterprise WeChat intelligent-robot user ID conversion](https://developer.work.weixin.qq.com/document/path/101521)
