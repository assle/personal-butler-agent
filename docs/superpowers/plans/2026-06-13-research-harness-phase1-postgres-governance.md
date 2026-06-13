# Research Harness Phase 1: PostgreSQL and Workspace Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace production SQLite schema creation with Alembic-managed PostgreSQL, introduce workspace isolation, provide a verified one-time migration path, and add permission/hook foundations.

**Architecture:** Keep SQLAlchemy models portable, use `asyncpg` for runtime PostgreSQL and Alembic for schema ownership. Existing records migrate into a configured default workspace; all new research access is resolved through workspace membership before task creation.

**Tech Stack:** SQLAlchemy 2 async, PostgreSQL 16+, asyncpg, Alembic, Pydantic Settings, pytest, pytest-asyncio

---

## File Map

**New database and migration files**

- `alembic.ini`: Alembic CLI configuration.
- `alembic/env.py`: load metadata and convert async runtime URL for migrations.
- `alembic/script.py.mako`: revision template.
- `alembic/versions/20260613_0001_postgres_workspace_baseline.py`: baseline schema.
- `src/db/migrations.py`: startup schema revision check.
- `src/cli/migrate_sqlite_to_postgres.py`: one-time data copy and validation.

**New governance files**

- `src/models/workspace.py`: workspace and membership ORM models.
- `src/governance/__init__.py`: stable governance exports.
- `src/governance/permissions.py`: structured permission decisions and policy.
- `src/governance/hooks.py`: typed async hook bus.
- `src/governance/workspaces.py`: workspace membership resolver.

**Modified runtime files**

- `pyproject.toml`, `uv.lock`: add `asyncpg` and `alembic`.
- `src/config.py`: PostgreSQL, migration, and default workspace settings.
- `src/db/session.py`: engine factory and PostgreSQL pool settings.
- `src/main.py`: replace production `create_all()` with revision verification.
- `src/models/__init__.py`: register workspace models.
- `src/models/research.py`: add `workspace_id` and workspace-safe constraints.
- `src/research/service.py`: require resolved workspace context.
- `src/research/submission.py`: resolve membership before task creation.
- `src/knowledge/keyword_search.py`: database-aware keyword retrieval.
- `src/knowledge/service.py`: remove direct SQLite FTS ownership.

**Tests**

- `tests/test_config.py`
- `tests/test_workspace_models.py`
- `tests/test_workspace_service.py`
- `tests/test_permission_engine.py`
- `tests/test_hook_bus.py`
- `tests/test_research_service.py`
- `tests/integration/conftest.py`
- `tests/integration/test_postgres_schema.py`
- `tests/integration/test_workspace_isolation.py`
- `tests/integration/test_sqlite_migration.py`
- `tests/integration/test_postgres_knowledge_search.py`

**Documentation**

- `.env.example`
- `deployment.md`
- `deployment.en.md`
- `docs/agent/config-variables.md`
- `docs/agent/decisions.md`
- `docs/agent/patterns.md`
- `docs/agent/active-context.md`
- `docs/agent/upgrade-roadmap.md`

The approved phase plan explicitly authorizes the listed test changes.

### Task 1: Add PostgreSQL and Alembic Dependencies

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `src/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing configuration tests**

Append tests that define the production contract:

```python
def test_settings_default_database_url_is_postgresql():
    """验证团队部署默认数据库切换为 PostgreSQL"""
    with patch.dict(
        os.environ,
        {"DEEPSEEK_API_KEY": "test"},
        clear=True,
    ):
        settings = Settings(_env_file=None)
    assert settings.database_url == (
        "postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler"
    )
    assert settings.database_pool_size == 10
    assert settings.database_max_overflow == 20
    assert settings.database_require_migrations is True


def test_settings_loads_workspace_bootstrap_config():
    """验证默认工作空间迁移配置可从环境变量加载"""
    env = {
        "DEEPSEEK_API_KEY": "test",
        "DEFAULT_WORKSPACE_ID": "ws-internal",
        "DEFAULT_WORKSPACE_NAME": "Internal Research",
    }
    with patch.dict(os.environ, env, clear=True):
        settings = Settings(_env_file=None)
    assert settings.default_workspace_id == "ws-internal"
    assert settings.default_workspace_name == "Internal Research"
```

- [ ] **Step 2: Run tests and confirm the old SQLite default fails**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_config.py::test_settings_default_database_url_is_postgresql \
  tests/test_config.py::test_settings_loads_workspace_bootstrap_config -q
```

Expected: FAIL because the new settings do not exist and `DATABASE_URL` still
defaults to SQLite.

- [ ] **Step 3: Add dependencies and settings**

Add dependencies:

```toml
"alembic>=1.14.0",
"asyncpg>=0.30.0",
```

Replace the SQLite-specific settings block with:

```python
    # PostgreSQL 结构化数据库配置；生产 schema 由 Alembic 管理
    database_url: str = (
        "postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler"
    )
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_require_migrations: bool = True

    # 首次迁移时用于承接现有单租户数据的默认工作空间
    default_workspace_id: str = "default"
    default_workspace_name: str = "Default Workspace"
```

- [ ] **Step 4: Lock dependencies and rerun tests**

Run:

```bash
uv lock
DEEPSEEK_API_KEY=test uv run pytest tests/test_config.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/config.py tests/test_config.py
git commit -m "build: add postgres and alembic configuration"
```

### Task 2: Introduce Engine Factory and PostgreSQL Test Fixture

**Files:**
- Modify: `src/db/session.py`
- Modify: `tests/conftest.py`
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_postgres_schema.py`

- [ ] **Step 1: Write failing engine factory tests**

Create an integration test:

```python
import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_postgres_fixture_uses_postgresql(postgres_engine):
    """验证集成测试连接到真实 PostgreSQL"""
    assert postgres_engine.dialect.name == "postgresql"
    async with postgres_engine.connect() as connection:
        assert await connection.scalar(text("select 1")) == 1
```

Add a unit assertion to `tests/test_db.py`:

```python
def test_create_engine_options_for_postgres():
    """验证 PostgreSQL 引擎启用连接池健康检查"""
    options = build_engine_options(
        "postgresql+asyncpg://u:p@localhost/db",
        pool_size=10,
        max_overflow=20,
    )
    assert options == {
        "echo": False,
        "pool_pre_ping": True,
        "pool_size": 10,
        "max_overflow": 20,
    }
```

- [ ] **Step 2: Run the focused tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_db.py -q
```

Expected: FAIL because `build_engine_options` does not exist.

- [ ] **Step 3: Implement explicit engine creation**

Add these public helpers to `src/db/session.py`:

```python
def build_engine_options(
    database_url: str,
    *,
    pool_size: int,
    max_overflow: int,
) -> dict:
    """按数据库类型生成异步引擎参数

    参数:
        database_url: SQLAlchemy 异步数据库 URL
        pool_size: PostgreSQL 常驻连接数
        max_overflow: PostgreSQL 临时溢出连接数

    返回:
        dict: 可传给 create_async_engine 的参数
    """
    options = {"echo": False}
    if database_url.startswith("postgresql+"):
        options.update(
            pool_pre_ping=True,
            pool_size=pool_size,
            max_overflow=max_overflow,
        )
    return options


def create_database_engine(database_url: str) -> AsyncEngine:
    """创建并配置异步数据库引擎

    参数:
        database_url: SQLAlchemy 异步数据库 URL

    返回:
        AsyncEngine: 已配置的 SQLAlchemy 异步引擎
    """
    async_engine = create_async_engine(
        database_url,
        **build_engine_options(
            database_url,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
        ),
    )
    enable_sqlite_foreign_keys(async_engine)
    return async_engine
```

Initialize the module engine through `create_database_engine`.

- [ ] **Step 4: Add opt-in PostgreSQL fixtures**

Implement `tests/integration/conftest.py` so integration tests require an
explicit disposable database:

```python
import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

@pytest_asyncio.fixture
async def postgres_engine():
    """提供显式配置的 PostgreSQL 集成测试引擎

    产出:
        AsyncEngine: 指向一次性测试数据库的异步引擎
    """
    url = os.getenv("TEST_DATABASE_URL", "")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    engine = create_async_engine(url, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def postgres_session(postgres_engine):
    """提供每个测试自动回滚的 PostgreSQL 会话

    产出:
        AsyncSession: 绑定外层回滚事务的异步会话
    """
    async with postgres_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest_asyncio.fixture
async def postgres_session_factory(postgres_engine):
    """提供并发 PostgreSQL 会话工厂

    产出:
        async_sessionmaker: 可创建独立事务的会话工厂
    """
    return async_sessionmaker(
        postgres_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
```

- [ ] **Step 5: Verify unit and PostgreSQL tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_db.py -q
TEST_DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  DEEPSEEK_API_KEY=test uv run pytest \
  tests/integration/test_postgres_schema.py::test_postgres_fixture_uses_postgresql -q
```

Expected: PASS when the disposable PostgreSQL database is running.

- [ ] **Step 6: Commit**

```bash
git add src/db/session.py tests/conftest.py tests/integration
git commit -m "refactor: add postgres engine and integration fixtures"
```

### Task 3: Add Workspace Models

**Files:**
- Create: `src/models/workspace.py`
- Modify: `src/models/__init__.py`
- Test: `tests/test_workspace_models.py`

- [ ] **Step 1: Write metadata tests**

```python
from src.db.base import Base


def test_workspace_tables_are_registered():
    """验证工作空间与成员表注册到 metadata"""
    assert {"workspaces", "workspace_members"} <= set(Base.metadata.tables)


def test_workspace_membership_is_unique():
    """验证同一工作空间内用户身份唯一"""
    table = Base.metadata.tables["workspace_members"]
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if hasattr(constraint, "columns")
    }
    assert ("workspace_id", "open_userid") in unique_columns
```

- [ ] **Step 2: Run tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_workspace_models.py -q
```

Expected: FAIL because the models do not exist.

- [ ] **Step 3: Add workspace models**

Create `Workspace` and `WorkspaceMember` with this public shape:

```python
class Workspace(Base):
    """团队工作空间"""

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active", index=True
    )
    policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class WorkspaceMember(Base):
    """工作空间成员与角色"""

    __tablename__ = "workspace_members"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "open_userid",
            name="uq_workspace_member_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    open_userid: Mapped[str] = mapped_column(
        String(256), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(
        String(32), nullable=False, default="member"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="active"
    )
    research_approved_once: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
```

- [ ] **Step 4: Run model tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_workspace_models.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/models/workspace.py src/models/__init__.py tests/test_workspace_models.py
git commit -m "feat: add workspace membership models"
```

### Task 4: Add Workspace Resolution Service

**Files:**
- Create: `src/governance/__init__.py`
- Create: `src/governance/workspaces.py`
- Test: `tests/test_workspace_service.py`

- [ ] **Step 1: Write failing resolution tests**

```python
@pytest.mark.asyncio
async def test_resolve_active_membership_returns_workspace_context(db_session):
    """验证活动成员可解析工作空间上下文"""
    workspace, member = await seed_workspace_member(
        db_session,
        workspace_id="ws-a",
        open_userid="open-u1",
        role="member",
    )
    service = WorkspaceService()
    context = await service.resolve_member(db_session, "open-u1")
    assert context.workspace_id == workspace.id
    assert context.member_id == member.id
    assert context.role == "member"


@pytest.mark.asyncio
async def test_resolve_member_rejects_ambiguous_membership(db_session):
    """验证多工作空间身份必须显式选择，不能静默越权"""
    await seed_workspace_member(db_session, "ws-a", "open-u1", "member")
    await seed_workspace_member(db_session, "ws-b", "open-u1", "member")
    with pytest.raises(AmbiguousWorkspaceError):
        await WorkspaceService().resolve_member(db_session, "open-u1")
```

- [ ] **Step 2: Run tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_workspace_service.py -q
```

Expected: FAIL because the governance package does not exist.

- [ ] **Step 3: Implement the service contract**

```python
@dataclass(frozen=True)
class WorkspaceContext:
    """已验证的工作空间成员上下文"""

    workspace_id: str
    member_id: int
    open_userid: str
    role: str
    research_approved_once: bool


class WorkspaceService:
    """解析并验证企业微信用户的工作空间身份"""

    async def resolve_member(
        self,
        db: AsyncSession,
        open_userid: str,
        workspace_id: str | None = None,
    ) -> WorkspaceContext:
        """解析活动成员身份

        参数:
            db: 异步数据库会话
            open_userid: 企业微信机器人用户标识
            workspace_id: 可选的显式工作空间 ID

        返回:
            WorkspaceContext: 已验证的工作空间上下文
        """
```

The query must require active workspace plus active membership. Zero matches
raise `WorkspaceAccessDeniedError`; multiple matches without `workspace_id`
raise `AmbiguousWorkspaceError`.

- [ ] **Step 4: Verify service tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_workspace_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/governance tests/test_workspace_service.py
git commit -m "feat: resolve workspace membership"
```

### Task 5: Add Permission Decisions and Hook Bus

**Files:**
- Create: `src/governance/permissions.py`
- Create: `src/governance/hooks.py`
- Modify: `src/governance/__init__.py`
- Test: `tests/test_permission_engine.py`
- Test: `tests/test_hook_bus.py`

- [ ] **Step 1: Write permission tests**

```python
def test_permission_engine_requires_first_use_approval():
    """验证首次研究需要审批"""
    decision = PermissionEngine().evaluate(
        PermissionRequest(
            operation="research.plan.execute",
            role="member",
            risk_level="internal_write",
            cost_class="medium",
            research_approved_once=False,
            workspace_matches=True,
        )
    )
    assert decision.effect == PermissionEffect.REQUIRE_APPROVAL
    assert decision.policy_id == "research.first_use"


def test_permission_engine_denies_cross_workspace():
    """验证跨工作空间操作始终拒绝"""
    decision = PermissionEngine().evaluate(
        PermissionRequest(
            operation="research.evidence.read",
            role="admin",
            risk_level="read",
            cost_class="low",
            research_approved_once=True,
            workspace_matches=False,
        )
    )
    assert decision.effect == PermissionEffect.DENY
```

- [ ] **Step 2: Write hook ordering tests**

```python
@pytest.mark.asyncio
async def test_hook_bus_runs_hooks_in_registration_order():
    """验证同一事件的 Hook 按注册顺序执行"""
    calls = []
    bus = HookBus()
    bus.register(HookEvent.BEFORE_RESEARCH, lambda ctx: record(calls, "a"))
    bus.register(HookEvent.BEFORE_RESEARCH, lambda ctx: record(calls, "b"))
    await bus.emit(HookEvent.BEFORE_RESEARCH, {"task_id": "R1"})
    assert calls == ["a", "b"]


@pytest.mark.asyncio
async def test_critical_hook_failure_is_fail_closed():
    """验证权限类 Hook 失败时阻止继续执行"""
    bus = HookBus()
    bus.register(HookEvent.BEFORE_TOOL, failing_hook, critical=True)
    with pytest.raises(CriticalHookError):
        await bus.emit(HookEvent.BEFORE_TOOL, {"tool": "web.search"})
```

- [ ] **Step 3: Run tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_permission_engine.py tests/test_hook_bus.py -q
```

Expected: FAIL because the contracts do not exist.

- [ ] **Step 4: Implement explicit governance types**

Use these stable enums and dataclasses:

```python
class PermissionEffect(StrEnum):
    """权限判定结果"""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True)
class PermissionRequest:
    """权限判定输入"""

    operation: str
    role: str
    risk_level: str
    cost_class: str
    research_approved_once: bool
    workspace_matches: bool


@dataclass(frozen=True)
class PermissionDecision:
    """结构化权限判定"""

    effect: PermissionEffect
    policy_id: str
    reason: str
```

Implement `PermissionEngine.evaluate()` in this order:

1. cross-workspace deny;
2. unknown dynamic tool deny;
3. first-use approval;
4. high-cost approval;
5. authorized read/internal write allow.

Implement hook types:

```python
class HookEvent(StrEnum):
    """研究生命周期 Hook 事件"""

    BEFORE_RESEARCH = "before_research"
    AFTER_PLAN = "after_plan"
    BEFORE_TOOL = "before_tool"
    AFTER_TOOL = "after_tool"
    ON_ERROR = "on_error"
    BEFORE_DELIVERY = "before_delivery"
    AFTER_RESEARCH = "after_research"
```

- [ ] **Step 5: Verify governance tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_permission_engine.py tests/test_hook_bus.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/governance tests/test_permission_engine.py tests/test_hook_bus.py
git commit -m "feat: add permission engine and research hooks"
```

### Task 6: Make Research Tasks Workspace-Scoped

**Files:**
- Modify: `src/models/research.py`
- Modify: `src/research/service.py`
- Modify: `src/research/submission.py`
- Modify: `src/main.py`
- Test: `tests/test_research_models.py`
- Test: `tests/test_research_service.py`
- Create: `tests/integration/test_workspace_isolation.py`

- [ ] **Step 1: Write failing workspace isolation tests**

Update service calls to require `WorkspaceContext`:

```python
task, created = await service.create_task(
    db_session,
    workspace=WorkspaceContext(
        workspace_id="ws-a",
        member_id=1,
        open_userid="open-u1",
        role="member",
        research_approved_once=True,
    ),
    source_msgid="msg-1",
    question="研究问题",
)
assert task.workspace_id == "ws-a"
```

Add a cross-workspace lookup test:

```python
assert await service.get_workspace_task(
    db_session,
    task.id,
    workspace_id="ws-b",
    requester_open_userid="open-u1",
) is None
```

- [ ] **Step 2: Run focused tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_models.py tests/test_research_service.py -q
```

Expected: FAIL because `workspace_id` and the new service contract are missing.

- [ ] **Step 3: Add workspace ownership**

Add to every research-owned table:

```python
workspace_id: Mapped[str] = mapped_column(
    ForeignKey("workspaces.id", ondelete="RESTRICT"),
    nullable=False,
    index=True,
)
```

For child tables, use composite uniqueness that includes `workspace_id`, and
ensure service queries always include it. Change `create_task` to accept
`workspace: WorkspaceContext` and persist an immutable access scope:

```python
access_scope={
    "workspace_id": workspace.workspace_id,
    "public": True,
    "user_id": workspace.open_userid,
    "group_ids": [],
    "web": True,
}
```

Change `ResearchSubmissionService` to inject `WorkspaceService` and resolve the
member before task creation. Inject `HookBus` and emit
`HookEvent.BEFORE_RESEARCH` after identity resolution but before task creation;
a critical hook failure returns a safe denial and does not write a task.

- [ ] **Step 4: Run isolation tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_models.py tests/test_research_service.py -q
TEST_DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  DEEPSEEK_API_KEY=test uv run pytest \
  tests/integration/test_workspace_isolation.py -q
```

Expected: PASS; a workspace-B query cannot return workspace-A data.

- [ ] **Step 5: Commit**

```bash
git add src/models/research.py src/research/service.py \
  src/research/submission.py src/main.py \
  tests/test_research_models.py tests/test_research_service.py \
  tests/integration/test_workspace_isolation.py
git commit -m "feat: scope research tasks to workspaces"
```

### Task 7: Make Knowledge Keyword Retrieval PostgreSQL-Compatible

**Files:**
- Create: `src/knowledge/keyword_search.py`
- Modify: `src/knowledge/service.py`
- Modify: `src/knowledge/__init__.py`
- Test: `tests/test_knowledge_service.py`
- Create: `tests/integration/test_postgres_knowledge_search.py`

- [ ] **Step 1: Write dialect behavior tests**

Add a unit test for the backend selection:

```python
def test_keyword_backend_selects_by_session_dialect():
    """验证关键词检索按数据库方言选择实现"""
    backend = KeywordSearchBackend()
    assert backend.strategy_for("sqlite") == "sqlite_fts5"
    assert backend.strategy_for("postgresql") == "postgres_tsvector"
```

Add a PostgreSQL integration test:

```python
@pytest.mark.asyncio
async def test_postgres_keyword_search_returns_matching_chunk(postgres_session):
    """验证 PostgreSQL 全文检索返回预期知识片段"""
    document, chunk = await seed_knowledge(
        postgres_session,
        title="Task Queue Guide",
        content="Taskiq is an async-native Python task queue.",
    )
    scores = await KeywordSearchBackend().search(
        postgres_session,
        "async task queue",
        limit=20,
    )
    assert chunk.id in scores
    assert scores[chunk.id] > 0
```

- [ ] **Step 2: Run focused tests**

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_knowledge_service.py -q
TEST_DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  DEEPSEEK_API_KEY=test uv run pytest \
  tests/integration/test_postgres_knowledge_search.py -q
```

Expected: PostgreSQL test FAILS because the current service always creates and
queries a SQLite FTS5 virtual table.

- [ ] **Step 3: Extract keyword search ownership**

Create:

```python
class KeywordSearchBackend:
    """按数据库方言执行知识关键词检索"""

    def strategy_for(self, dialect_name: str) -> str:
        """返回数据库对应的检索策略

        参数:
            dialect_name: SQLAlchemy 数据库方言名称

        返回:
            str: sqlite_fts5 或 postgres_tsvector
        """
        if dialect_name == "sqlite":
            return "sqlite_fts5"
        if dialect_name == "postgresql":
            return "postgres_tsvector"
        raise UnsupportedKnowledgeDialectError(dialect_name)

    async def index_chunk(
        self,
        db: AsyncSession,
        chunk: KnowledgeChunk,
        title: str,
    ) -> None:
        """维护需要显式写入的关键词索引

        参数:
            db: 异步数据库会话
            chunk: 已持久化知识片段
            title: 文档标题

        返回:
            None
        """

    async def search(
        self,
        db: AsyncSession,
        query: str,
        *,
        limit: int = 20,
    ) -> dict[int, float]:
        """返回 chunk_id 到相关性分数

        参数:
            db: 异步数据库会话
            query: 用户查询
            limit: 最大候选数

        返回:
            dict[int, float]: 关键词检索分数
        """
```

Retain the current FTS5 create/index/query logic only inside the SQLite
strategy. For PostgreSQL, do not create a side table. Query:

```sql
SELECT id,
       ts_rank_cd(
         to_tsvector(
           'simple',
           coalesce(content, '') || ' ' || coalesce(source, '')
         ),
         plainto_tsquery('simple', :query)
       ) AS rank
FROM knowledge_chunks
WHERE to_tsvector(
        'simple',
        coalesce(content, '') || ' ' || coalesce(source, '')
      ) @@ plainto_tsquery('simple', :query)
ORDER BY rank DESC
LIMIT :limit
```

`index_chunk()` is a no-op for PostgreSQL because the index is expression-based.

- [ ] **Step 4: Add PostgreSQL expression index in Alembic baseline**

The Phase 1 baseline migration creates:

```sql
CREATE INDEX ix_knowledge_chunks_search_vector
ON knowledge_chunks
USING gin (
  to_tsvector(
    'simple',
    coalesce(content, '') || ' ' || coalesce(source, '')
  )
);
```

The downgrade drops this index before dropping `knowledge_chunks`.

- [ ] **Step 5: Inject backend into KnowledgeService**

Add `keyword_search: KeywordSearchBackend | None = None` to the constructor,
default it to `KeywordSearchBackend()`, replace `_ensure_fts_table`,
`_index_fts_chunk`, and `_search_fts` calls with the backend, and remove those
private methods after tests pass.

- [ ] **Step 6: Verify both dialects**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_knowledge_service.py tests/test_knowledge_model.py -q
TEST_DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  DEEPSEEK_API_KEY=test uv run pytest \
  tests/integration/test_postgres_knowledge_search.py -q
```

Expected: both SQLite unit fixtures and PostgreSQL integration tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/knowledge/keyword_search.py src/knowledge/service.py \
  src/knowledge/__init__.py tests/test_knowledge_service.py \
  tests/integration/test_postgres_knowledge_search.py
git commit -m "feat: support postgres knowledge keyword search"
```

### Task 8: Establish Alembic Schema Ownership

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/20260613_0001_postgres_workspace_baseline.py`
- Create: `src/db/migrations.py`
- Modify: `src/main.py`
- Test: `tests/integration/test_postgres_schema.py`

- [ ] **Step 1: Initialize Alembic**

Run:

```bash
uv run alembic init alembic
```

Expected: Alembic creates its configuration and directory.

- [ ] **Step 2: Configure metadata and async URL**

Set `target_metadata = Base.metadata` after importing `src.models`. Read
`settings.database_url`; convert `postgresql+asyncpg://` to
`postgresql+psycopg://` only if the migration environment uses a synchronous
driver, otherwise use Alembic's async template with `async_engine_from_config`.

The selected plan is the async template:

```python
connectable = async_engine_from_config(
    configuration,
    prefix="sqlalchemy.",
    poolclass=pool.NullPool,
)
async with connectable.connect() as connection:
    await connection.run_sync(do_run_migrations)
```

- [ ] **Step 3: Generate and inspect the baseline**

Run:

```bash
DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  DEEPSEEK_API_KEY=test \
  uv run alembic revision --autogenerate \
  -m "postgres workspace baseline"
```

Expected: one revision containing all current application tables plus
`workspaces`, `workspace_members`, and workspace-scoped research columns.

Rename the generated file to the planned deterministic revision filename and
set:

```python
revision = "20260613_0001"
down_revision = None
```

- [ ] **Step 4: Add startup revision verification**

Implement:

```python
async def assert_database_at_head(engine: AsyncEngine) -> None:
    """验证数据库 Alembic 版本已达到代码要求

    参数:
        engine: 应用异步数据库引擎

    返回:
        None: 版本一致时正常返回，不一致时抛出 RuntimeError
    """
```

Use `MigrationContext.configure(connection)` and
`ScriptDirectory.from_config(config)` to compare current heads. In
`src/main.py`, remove `Base.metadata.create_all` from production lifespan and
call this check when `database_require_migrations` is true.

- [ ] **Step 5: Test upgrade, downgrade, and revision check**

Run:

```bash
DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  DEEPSEEK_API_KEY=test uv run alembic downgrade base
DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  DEEPSEEK_API_KEY=test uv run alembic upgrade head
DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  DEEPSEEK_API_KEY=test uv run alembic check
```

Expected: all commands exit `0`.

- [ ] **Step 6: Commit**

```bash
git add alembic.ini alembic src/db/migrations.py src/main.py \
  tests/integration/test_postgres_schema.py
git commit -m "feat: manage database schema with alembic"
```

### Task 9: Add One-Time SQLite-to-PostgreSQL Migration

**Files:**
- Create: `src/cli/migrate_sqlite_to_postgres.py`
- Modify: `pyproject.toml`
- Test: `tests/integration/test_sqlite_migration.py`

- [ ] **Step 1: Write a migration integration test**

The test creates a temporary SQLite source with representative rows, migrates
to disposable PostgreSQL, then asserts:

```python
assert result.table_counts["research_tasks"] == (1, 1)
assert result.table_counts["research_reports"] == (1, 1)
assert result.duplicate_source_msgids == []
assert result.orphaned_workspace_rows == []
```

- [ ] **Step 2: Run the test**

Run:

```bash
TEST_DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  DEEPSEEK_API_KEY=test uv run pytest \
  tests/integration/test_sqlite_migration.py -q
```

Expected: FAIL because the migration command does not exist.

- [ ] **Step 3: Implement explicit migration phases**

Expose:

```python
@dataclass(frozen=True)
class MigrationResult:
    """SQLite 到 PostgreSQL 迁移校验结果"""

    table_counts: dict[str, tuple[int, int]]
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
```

Copy parent tables before child tables in a constant ordered list. Preserve
primary keys. Backfill `workspace_id` on migrated research and authorization
rows. Reset PostgreSQL integer sequences after explicit ID inserts.

Register:

```toml
butler-migrate-sqlite-to-postgres = "src.cli.migrate_sqlite_to_postgres:run"
```

- [ ] **Step 4: Verify dry run and real migration**

Run:

```bash
DEEPSEEK_API_KEY=test uv run butler-migrate-sqlite-to-postgres \
  --source sqlite+aiosqlite:///butler.db \
  --target postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler \
  --workspace-id default \
  --workspace-name 'Default Workspace' \
  --dry-run
```

Expected: prints source/target counts and makes no writes.

Then run without `--dry-run` against a backup copy and expect all source and
target counts to match.

- [ ] **Step 5: Commit**

```bash
git add src/cli/migrate_sqlite_to_postgres.py pyproject.toml uv.lock \
  tests/integration/test_sqlite_migration.py
git commit -m "feat: migrate sqlite data to postgres"
```

### Task 10: Update Deployment and Architecture Documentation

**Files:**
- Modify: `.env.example`
- Modify: `deployment.md`
- Modify: `deployment.en.md`
- Modify: `docs/agent/config-variables.md`
- Modify: `docs/agent/decisions.md`
- Modify: `docs/agent/patterns.md`
- Modify: `docs/agent/active-context.md`
- Modify: `docs/agent/upgrade-roadmap.md`

- [ ] **Step 1: Document exact environment variables**

Use this documented shape:

```env
DATABASE_URL=postgresql+asyncpg://butler:change-me@127.0.0.1:5432/butler
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20
DATABASE_REQUIRE_MIGRATIONS=true
DEFAULT_WORKSPACE_ID=default
DEFAULT_WORKSPACE_NAME=Default Workspace
```

- [ ] **Step 2: Document operational commands**

Include:

```bash
uv run alembic upgrade head
uv run butler-migrate-sqlite-to-postgres --help
uv run uvicorn src.main:app --host 127.0.0.1 --port 8000
```

State clearly that the application refuses startup when migrations are behind
and that SQLite is no longer a production writer after cutover.

- [ ] **Step 3: Record architecture decisions**

Add ADRs for:

- PostgreSQL as authoritative team database;
- Alembic owning production schema;
- immutable workspace scope;
- application-owned permission and hook interfaces;
- one-time migration with no long-term dual write.

- [ ] **Step 4: Verify docs**

Run:

```bash
rg -n "sqlite\\+aiosqlite:///butler.db|create_all" \
  deployment.md deployment.en.md docs/agent .env.example
cmp -s CLAUDE.md AGENTS.md
```

Expected: SQLite appears only in migration/history explanations; root docs are
still byte-identical.

- [ ] **Step 5: Commit**

```bash
git add .env.example deployment.md deployment.en.md docs/agent
git commit -m "docs: document postgres governance foundation"
```

### Task 11: Phase 1 Verification

**Files:** no new files

- [ ] **Step 1: Run unit tests**

```bash
DEEPSEEK_API_KEY=test uv run pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run PostgreSQL integration tests**

```bash
TEST_DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  DEEPSEEK_API_KEY=test uv run pytest tests/integration -q
```

Expected: all PostgreSQL integration tests pass.

- [ ] **Step 3: Verify schema and docs**

```bash
DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  DEEPSEEK_API_KEY=test uv run alembic check
git diff --check
cmp -s CLAUDE.md AGENTS.md
```

Expected: all commands exit `0`.

- [ ] **Step 4: Commit verification metadata only if generated intentionally**

Do not commit database dumps, `.env`, PostgreSQL volumes, SQLite backups, or
Chroma data.
