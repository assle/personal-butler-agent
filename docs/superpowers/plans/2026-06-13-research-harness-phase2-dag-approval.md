# Research Harness Phase 2: Durable DAG and Approval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add versioned research plans, dependency-aware steps, PostgreSQL leases, budget enforcement, cancellation, and first-use/high-cost approval without yet invoking specialist agents.

**Architecture:** Store plans and steps in PostgreSQL and let Taskiq workers claim ready step IDs through an application-owned service. Planning is side-effect free; plan policy evaluation determines whether steps activate immediately or wait for explicit private-chat approval.

**Tech Stack:** SQLAlchemy 2 async, PostgreSQL row locks, Taskiq, Redis Streams, Pydantic v2, pytest

---

## File Map

**New models and schemas**

- `src/models/research_execution.py`: plans, steps, dependencies, approvals,
  usage, and events.
- `src/research/planning/schemas.py`: typed plan and step drafts.
- `src/research/budgets.py`: budget limits and accounting.
- `src/research/events.py`: append-only event writer.
- `src/research/usage.py`: model/tool usage and cost persistence.

**New services**

- `src/research/planning/validator.py`: DAG, tool, and budget validation.
- `src/research/planning/service.py`: versioned plan persistence.
- `src/research/steps.py`: readiness, claims, leases, retries, and completion.
- `src/research/approvals.py`: approval policy and state transitions.

**Modified runtime**

- `src/research/schemas.py`: expanded task and step statuses.
- `src/research/service.py`: compare-and-set task transitions.
- `src/research/queue.py`: step execution dispatch.
- `src/research/tasks.py`: step worker entry and lease recovery entry.
- `src/research/submission.py`: approval/rejection commands.
- `src/agents/private_butler/graph.py`: deterministic approval routing.
- `src/config.py`: plan, budget, lease, and approval thresholds.
- `src/models/__init__.py`: model registration.
- Alembic revision under `alembic/versions/`.

**Tests**

- `tests/test_research_plan_validator.py`
- `tests/test_research_plan_service.py`
- `tests/test_research_step_service.py`
- `tests/test_research_budget.py`
- `tests/test_research_approval.py`
- `tests/test_research_events.py`
- `tests/test_research_usage.py`
- `tests/test_research_submission.py`
- `tests/integration/test_research_step_claims.py`
- `tests/integration/test_research_lease_recovery.py`

The approved phase plan explicitly authorizes these tests.

### Task 1: Expand Research Status Contracts

**Files:**
- Modify: `src/research/schemas.py`
- Modify: `src/models/research.py`
- Test: `tests/test_research_models.py`
- Test: `tests/test_research_service.py`

- [ ] **Step 1: Write failing status tests**

```python
def test_research_task_status_contains_harness_states():
    """验证研究主任务包含完整 Harness 状态"""
    assert {status.value for status in ResearchTaskStatus} == {
        "submitted",
        "planning",
        "awaiting_approval",
        "running",
        "synthesizing",
        "validating",
        "completed",
        "delivering",
        "delivered",
        "retrying",
        "failed",
        "cancelled",
    }


def test_active_statuses_block_second_task():
    """验证未终止状态都会阻止同用户重复提交"""
    assert ACTIVE_RESEARCH_STATUSES == {
        "submitted",
        "planning",
        "awaiting_approval",
        "running",
        "synthesizing",
        "validating",
        "retrying",
    }
```

- [ ] **Step 2: Run tests**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_models.py tests/test_research_service.py -q
```

Expected: FAIL because Phase 1 statuses are still in use.

- [ ] **Step 3: Define task and step enums**

```python
class ResearchTaskStatus(StrEnum):
    """研究主任务状态"""

    SUBMITTED = "submitted"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    SYNTHESIZING = "synthesizing"
    VALIDATING = "validating"
    COMPLETED = "completed"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    RETRYING = "retrying"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResearchStepStatus(StrEnum):
    """研究步骤状态"""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

Map legacy rows in the Alembic revision:

```text
queued -> submitted
running -> running
timed_out -> failed
completed -> completed
failed -> failed
cancelled -> cancelled
```

- [ ] **Step 4: Add compare-and-set transition service**

Expose:

```python
async def transition(
    self,
    db: AsyncSession,
    task_id: str,
    workspace_id: str,
    *,
    expected: set[ResearchTaskStatus],
    target: ResearchTaskStatus,
    error: str | None = None,
) -> ResearchTask:
    """按期望状态原子转换研究任务

    参数:
        db: 异步数据库会话
        task_id: 研究任务 ID
        workspace_id: 工作空间 ID
        expected: 允许的来源状态
        target: 目标状态
        error: 可选错误摘要

    返回:
        ResearchTask: 转换后的任务
    """
```

Use one SQL `UPDATE ... WHERE status IN (...) RETURNING` statement. Zero rows
raise `InvalidResearchTransitionError`.

- [ ] **Step 5: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_models.py tests/test_research_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/research/schemas.py src/models/research.py \
  src/research/service.py tests/test_research_models.py \
  tests/test_research_service.py alembic/versions
git commit -m "feat: add research harness task states"
```

### Task 2: Add Plan, Step, Approval, Usage, and Event Models

**Files:**
- Create: `src/models/research_execution.py`
- Modify: `src/models/__init__.py`
- Create: Alembic revision
- Test: `tests/test_research_models.py`

- [ ] **Step 1: Write metadata and constraint tests**

```python
def test_research_execution_tables_are_registered():
    """验证研究执行表全部注册"""
    expected = {
        "research_plans",
        "research_steps",
        "research_step_dependencies",
        "research_approvals",
        "research_usage",
        "research_events",
    }
    assert expected <= set(Base.metadata.tables)


def test_step_idempotency_is_workspace_scoped():
    """验证步骤幂等键在工作空间内唯一"""
    table = Base.metadata.tables["research_steps"]
    assert has_unique_constraint(
        table,
        ("workspace_id", "idempotency_key"),
    )
```

- [ ] **Step 2: Run model tests**

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_research_models.py -q
```

Expected: FAIL because the tables are missing.

- [ ] **Step 3: Add focused ORM models**

Use these core columns:

```python
class ResearchPlan(Base):
    """版本化研究计划"""

    __tablename__ = "research_plans"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "task_id",
            "version",
            name="uq_research_plan_version",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    completion_criteria: Mapped[list] = mapped_column(JSON, nullable=False)
    estimated_cost_microunits: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_plan: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class ResearchStep(Base):
    """研究 DAG 步骤与租约"""

    __tablename__ = "research_steps"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_research_step_idempotency",
        ),
        Index(
            "ix_research_steps_claim",
            "status",
            "available_at",
            "lease_expires_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    plan_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    input_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False)
    owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    result_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Also define:

- `ResearchStepDependency(step_id, depends_on_step_id)`;
- `ResearchApproval(task_id, plan_id, policy_id, status, decided_by, reason)`;
- `ResearchUsage(task_id, step_id, provider, model, input_tokens,
  output_tokens, estimated_cost_microunits, latency_ms)`;
- `ResearchEvent(task_id, step_id, event_type, payload, created_at)`.

- [ ] **Step 4: Generate and apply migration**

```bash
DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  DEEPSEEK_API_KEY=test uv run alembic revision --autogenerate \
  -m "add research execution graph"
DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  DEEPSEEK_API_KEY=test uv run alembic upgrade head
```

Expected: migration succeeds.

- [ ] **Step 5: Verify model tests**

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_research_models.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/models/research_execution.py src/models/__init__.py \
  tests/test_research_models.py alembic/versions
git commit -m "feat: add durable research execution models"
```

### Task 3: Define Plan Drafts and DAG Validation

**Files:**
- Create: `src/research/planning/__init__.py`
- Create: `src/research/planning/schemas.py`
- Create: `src/research/planning/validator.py`
- Test: `tests/test_research_plan_validator.py`

- [ ] **Step 1: Write validator tests**

```python
def test_validator_rejects_cycle():
    """验证循环依赖被拒绝"""
    draft = PlanDraft(
        objective="compare",
        completion_criteria=["cover cost"],
        estimated_tokens=1000,
        estimated_cost_microunits=100,
        steps=[
            StepDraft(
                key="a",
                kind="knowledge_retrieval",
                tool_name="knowledge.search",
                input_payload={},
                depends_on=["b"],
            ),
            StepDraft(
                key="b",
                kind="web_retrieval",
                tool_name="web.search",
                input_payload={},
                depends_on=["a"],
            ),
        ],
    )
    with pytest.raises(PlanValidationError, match="cycle"):
        PlanValidator(allowed_tools={"knowledge.search", "web.search"}).validate(
            draft,
            limits=BudgetLimits.default(),
        )


def test_validator_rejects_unknown_tool_and_budget_overflow():
    """验证未知工具与预算超限被拒绝"""
```

- [ ] **Step 2: Run tests**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_plan_validator.py -q
```

Expected: FAIL because planning schemas do not exist.

- [ ] **Step 3: Add immutable plan contracts**

```python
class StepDraft(BaseModel):
    """待持久化的研究步骤"""

    key: str
    kind: str
    tool_name: str
    input_payload: dict
    depends_on: list[str] = Field(default_factory=list)
    max_attempts: int = Field(default=3, ge=1, le=5)


class PlanDraft(BaseModel):
    """Supervisor 输出的结构化研究计划"""

    objective: str
    completion_criteria: list[str]
    estimated_tokens: int = Field(ge=0)
    estimated_cost_microunits: int = Field(ge=0)
    steps: list[StepDraft]
```

The validator checks unique keys, existing dependencies, no self-dependency,
acyclic graph, allowed tools, max steps, token budget, cost budget, and maximum
dependency depth.

- [ ] **Step 4: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_plan_validator.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/research/planning tests/test_research_plan_validator.py
git commit -m "feat: validate structured research plans"
```

### Task 4: Add Budget Accounting

**Files:**
- Create: `src/research/budgets.py`
- Modify: `src/config.py`
- Test: `tests/test_research_budget.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write budget tests**

```python
def test_budget_classifies_soft_and_hard_limits():
    """验证软硬预算边界"""
    budget = ResearchBudget(
        limits=BudgetLimits(
            max_tokens=20_000,
            soft_tokens=15_000,
            max_cost_microunits=500_000,
            soft_cost_microunits=350_000,
            max_steps=12,
            max_concurrent_steps=3,
            max_replans=2,
            max_repair_rounds=1,
        )
    )
    budget.record(tokens=15_001, cost_microunits=100)
    assert budget.state == BudgetState.SOFT_LIMIT
    budget.record(tokens=5_000, cost_microunits=500_000)
    assert budget.state == BudgetState.HARD_LIMIT
```

- [ ] **Step 2: Add settings**

```python
    research_max_steps: int = 12
    research_max_concurrent_steps: int = 3
    research_soft_token_budget: int = 15_000
    research_hard_token_budget: int = 20_000
    research_soft_cost_microunits: int = 350_000
    research_hard_cost_microunits: int = 500_000
    research_max_replans: int = 2
    research_max_repair_rounds: int = 1
    research_step_lease_seconds: int = 120
    research_high_cost_approval_microunits: int = 250_000
```

- [ ] **Step 3: Implement budget types**

```python
class BudgetState(StrEnum):
    """研究预算状态"""

    AVAILABLE = "available"
    SOFT_LIMIT = "soft_limit"
    HARD_LIMIT = "hard_limit"
```

`ResearchBudget.record()` is deterministic and never silently permits a hard
limit overrun.

- [ ] **Step 4: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_budget.py tests/test_config.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/research/budgets.py src/config.py \
  tests/test_research_budget.py tests/test_config.py
git commit -m "feat: enforce research budgets"
```

### Task 5: Persist Plans, Usage, and Events

**Files:**
- Create: `src/research/planning/service.py`
- Create: `src/research/events.py`
- Create: `src/research/usage.py`
- Test: `tests/test_research_plan_service.py`
- Test: `tests/test_research_events.py`
- Test: `tests/test_research_usage.py`

- [ ] **Step 1: Write plan persistence tests**

```python
@pytest.mark.asyncio
async def test_persist_plan_creates_versioned_steps_and_dependencies(db_session):
    """验证计划、步骤和依赖在同一事务中持久化"""
    plan = await PlanService().persist(
        db_session,
        workspace_id="ws-a",
        task_id=task.id,
        draft=valid_plan_draft(),
    )
    assert plan.version == 1
    assert await count_steps(db_session, task.id) == 2
    assert await count_dependencies(db_session, task.id) == 1
```

- [ ] **Step 2: Write event redaction tests**

```python
@pytest.mark.asyncio
async def test_event_writer_redacts_secret_fields(db_session):
    """验证事件载荷不保存密钥和访问令牌"""
    event = await EventWriter().append(
        db_session,
        workspace_id="ws-a",
        task_id="R1",
        event_type="tool.called",
        payload={"api_key": "secret", "query": "safe"},
    )
    assert event.payload == {"api_key": "[REDACTED]", "query": "safe"}
```

- [ ] **Step 3: Write usage accounting tests**

```python
@pytest.mark.asyncio
async def test_usage_recorder_persists_tokens_cost_and_latency(db_session):
    """验证模型与工具用量可累计到任务预算"""
    usage = await ResearchUsageRecorder().record(
        db_session,
        workspace_id="ws-a",
        task_id="R1",
        step_id="R1:1:web",
        provider="deepseek",
        model="deepseek-chat",
        input_tokens=100,
        output_tokens=50,
        estimated_cost_microunits=1200,
        latency_ms=800,
    )
    assert usage.input_tokens == 100
    totals = await ResearchUsageRecorder().totals(db_session, "ws-a", "R1")
    assert totals.total_tokens == 150
    assert totals.estimated_cost_microunits == 1200
```

- [ ] **Step 4: Implement atomic persistence**

`PlanService.persist()` must:

1. lock the parent task;
2. calculate next version;
3. insert plan;
4. insert steps with deterministic IDs `${task_id}:${version}:${key}`;
5. insert dependencies;
6. mark root steps `ready` only when approval is not required;
7. append `plan.created`.

- [ ] **Step 5: Implement usage recorder**

Expose:

```python
@dataclass(frozen=True)
class ResearchUsageTotals:
    """研究任务累计用量"""

    total_tokens: int
    estimated_cost_microunits: int
    total_latency_ms: int
    tool_calls: int


class ResearchUsageRecorder:
    """持久化并汇总研究模型与工具用量"""

    async def record(
        self,
        db: AsyncSession,
        *,
        workspace_id: str,
        task_id: str,
        step_id: str | None,
        provider: str,
        model: str | None,
        input_tokens: int,
        output_tokens: int,
        estimated_cost_microunits: int,
        latency_ms: int,
    ) -> ResearchUsage:
        """保存一次用量记录"""
```

Budget checks must use persisted totals plus the proposed next operation, not
process-local counters.

- [ ] **Step 6: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_plan_service.py \
  tests/test_research_events.py \
  tests/test_research_usage.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/research/planning/service.py src/research/events.py \
  src/research/usage.py tests/test_research_plan_service.py \
  tests/test_research_events.py tests/test_research_usage.py
git commit -m "feat: persist research plans usage and events"
```

### Task 6: Implement Atomic Step Claims and Lease Recovery

**Files:**
- Create: `src/research/steps.py`
- Test: `tests/test_research_step_service.py`
- Test: `tests/integration/test_research_step_claims.py`
- Test: `tests/integration/test_research_lease_recovery.py`

- [ ] **Step 1: Write concurrent claim test**

```python
@pytest.mark.asyncio
async def test_two_workers_claim_different_ready_steps(postgres_session_factory):
    """验证并发 Worker 不会认领同一步骤"""
    first, second = await asyncio.gather(
        claim_one(postgres_session_factory, "worker-a"),
        claim_one(postgres_session_factory, "worker-b"),
    )
    assert first.id != second.id
    assert {first.owner, second.owner} == {"worker-a", "worker-b"}
```

- [ ] **Step 2: Write lease recovery test**

```python
@pytest.mark.asyncio
async def test_expired_lease_returns_step_to_ready(postgres_session):
    """验证过期租约可恢复为待执行"""
    step = await seed_running_step(
        postgres_session,
        lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    recovered = await ResearchStepService().recover_expired_leases(
        postgres_session,
        limit=100,
    )
    assert recovered == [step.id]
```

- [ ] **Step 3: Implement claim query**

Use a transaction containing:

```python
query = (
    select(ResearchStep)
    .where(
        ResearchStep.status == ResearchStepStatus.READY.value,
        ResearchStep.available_at <= now,
    )
    .order_by(ResearchStep.available_at, ResearchStep.id)
    .with_for_update(skip_locked=True)
    .limit(1)
)
```

After claim, set `running`, increment attempts, set owner and lease expiration,
then commit before executing external work.

- [ ] **Step 4: Implement dependency unblocking**

After completion, update pending dependents to `ready` only when every
dependency is `completed`. Cancel dependents when a required predecessor is
terminally failed.

- [ ] **Step 5: Verify**

```bash
TEST_DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_step_service.py \
  tests/integration/test_research_step_claims.py \
  tests/integration/test_research_lease_recovery.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/research/steps.py tests/test_research_step_service.py \
  tests/integration/test_research_step_claims.py \
  tests/integration/test_research_lease_recovery.py
git commit -m "feat: claim research steps with leases"
```

### Task 7: Add Approval Policy and Private Commands

**Files:**
- Create: `src/research/approvals.py`
- Modify: `src/research/submission.py`
- Modify: `src/agents/private_butler/graph.py`
- Test: `tests/test_research_approval.py`
- Test: `tests/test_research_submission.py`
- Test: `tests/test_butler_agent.py`

- [ ] **Step 1: Add deterministic command patterns**

Use:

```python
_RESEARCH_APPROVE_PATTERN = re.compile(
    r"^批准研究任务\s+(R\d{8}-[A-F0-9]{8})$",
    re.IGNORECASE,
)
_RESEARCH_REJECT_PATTERN = re.compile(
    r"^拒绝研究任务\s+(R\d{8}-[A-F0-9]{8})(?:[：:]\s*(.+))?$",
    re.IGNORECASE | re.DOTALL,
)
```

Tests must prove group chat cannot invoke them and another user cannot approve
the request.

- [ ] **Step 2: Write approval policy tests**

```python
def test_first_use_or_high_cost_requires_approval():
    """验证首次或高成本计划需要审批"""
    policy = ApprovalPolicy(high_cost_microunits=250_000)
    assert policy.evaluate(first_use=True, estimated_cost=1).required is True
    assert policy.evaluate(first_use=False, estimated_cost=250_001).required is True
    assert policy.evaluate(first_use=False, estimated_cost=10).required is False
```

- [ ] **Step 3: Implement approval transitions**

Expose:

```python
async def approve(
    self,
    db: AsyncSession,
    *,
    workspace: WorkspaceContext,
    task_id: str,
    reason: str = "",
) -> ResearchApproval:
    """批准当前用户可管理的研究计划

    参数:
        db: 异步数据库会话
        workspace: 已验证工作空间上下文
        task_id: 研究任务 ID
        reason: 可选审批备注

    返回:
        ResearchApproval: 已持久化审批记录
    """
```

Approval activates root steps, marks membership
`research_approved_once=True`, transitions task to `running`, and appends
`approval.approved`. Rejection cancels all nonterminal steps and the task.

- [ ] **Step 4: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_approval.py \
  tests/test_research_submission.py \
  tests/test_butler_agent.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/research/approvals.py src/research/submission.py \
  src/agents/private_butler/graph.py \
  tests/test_research_approval.py tests/test_research_submission.py \
  tests/test_butler_agent.py
git commit -m "feat: approve first-use and high-cost research plans"
```

### Task 8: Dispatch Step IDs Through Taskiq

**Files:**
- Modify: `src/research/queue.py`
- Modify: `src/research/tasks.py`
- Modify: `src/research/broker.py`
- Test: `tests/test_research_queue.py`
- Test: `tests/test_research_tasks.py`

- [ ] **Step 1: Extend dispatcher protocol**

```python
class ResearchDispatcher(Protocol):
    """研究任务派发接口"""

    async def enqueue_planning(self, task_id: str) -> None:
        """派发计划生成任务"""

    async def enqueue_step(self, step_id: str) -> None:
        """派发单个研究步骤"""

    async def enqueue_delivery(self, task_id: str) -> None:
        """派发独立报告投递任务"""
```

- [ ] **Step 2: Write worker envelope tests**

```python
@pytest.mark.asyncio
async def test_execute_step_job_claims_specific_step_and_renews_lease():
    """验证步骤 Worker 仅处理指定 ID 并维护租约"""
```

The injected executor returns `StepExecutionResult(result_ref="evidence:1")`;
the service records completion and enqueues newly unblocked step IDs.

- [ ] **Step 3: Add Taskiq entries**

Register:

```python
@broker.task(task_name="research.plan")
async def plan_research_task(task_id: str) -> None:
    """Taskiq 研究规划入口"""


@broker.task(task_name="research.step")
async def run_research_step(step_id: str) -> None:
    """Taskiq 研究步骤入口"""


@broker.task(task_name="research.recover_leases")
async def recover_research_leases() -> None:
    """Taskiq 过期步骤租约恢复入口"""
```

Phase 2 uses a deterministic fixture planner in tests; the LLM Supervisor is
introduced in Phase 3.

- [ ] **Step 4: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_queue.py tests/test_research_tasks.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/research/queue.py src/research/tasks.py src/research/broker.py \
  tests/test_research_queue.py tests/test_research_tasks.py
git commit -m "feat: dispatch durable research steps"
```

### Task 9: Phase 2 Documentation and Verification

**Files:**
- Modify: `docs/agent/active-context.md`
- Modify: `docs/agent/patterns.md`
- Modify: `docs/agent/decisions.md`
- Modify: `docs/agent/config-variables.md`
- Modify: `.env.example`

- [ ] **Step 1: Document task graph and approval behavior**

Document the two deterministic user commands:

```text
批准研究任务 R20260613-ABCDEF12
拒绝研究任务 R20260613-ABCDEF12：预算过高
```

Document that planning is side-effect free and approval activates persisted
steps.

- [ ] **Step 2: Run Phase 2 gate**

```bash
TEST_DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_plan_service.py \
  tests/test_research_step_service.py \
  tests/test_research_approval.py \
  tests/integration/test_research_step_claims.py \
  tests/integration/test_research_lease_recovery.py -q
DEEPSEEK_API_KEY=test uv run pytest -q
uv run alembic check
```

Expected: all commands exit `0`.

- [ ] **Step 3: Commit**

```bash
git add docs/agent .env.example
git commit -m "docs: document research dag and approvals"
```
