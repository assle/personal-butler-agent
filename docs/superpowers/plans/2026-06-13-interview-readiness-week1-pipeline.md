# Week 1 Executable Research Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the asynchronous research path execute from persisted submission through validated Enterprise WeChat delivery.

**Architecture:** Correct the tool-provider contract so providers receive the active database session, assemble real providers in the worker, atomically claim ready steps before enqueue, and use task-state compare-and-set transitions as stage idempotency guards.

**Tech Stack:** Python, SQLAlchemy async, PostgreSQL, Taskiq, LangChain structured output, pytest

---

## File Map

**Modify**

- `tests/test_llm.py`
- `tests/test_research_provider_registry.py`
- `tests/test_research_tool_registry.py`
- `tests/test_research_tasks.py`
- `tests/test_research_delivery.py`
- `src/research/tools/providers.py`
- `src/research/tools/registry.py`
- `src/research/providers/builtin.py`
- `src/research/execution.py`
- `src/research/steps.py`
- `src/research/tasks.py`
- `src/research/synthesis/service.py`
- `src/research/review/service.py`
- `src/research/delivery.py`

**Create**

- `src/research/specialists/fetch.py`
- `src/research/dispatch.py`
- `src/research/pipeline.py`
- `tests/test_research_dispatch.py`
- `tests/test_research_pipeline.py`

## Task 1: Restore the Green Baseline

- [ ] **Step 1: Correct the structured-output mock**

Modify `tests/test_llm.py` so the factory is synchronous and the returned
runnable is asynchronous:

```python
fake_model = MagicMock()
structured_runnable = AsyncMock()
structured_runnable.ainvoke.return_value = _FakePlanDraft(
    objective="compare",
    steps=[],
)
fake_model.with_structured_output.return_value = structured_runnable
client._model = fake_model
```

- [ ] **Step 2: Verify the failure is gone**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_llm.py::test_ainvoke_structured_returns_validated_model \
  -q
```

Expected: `1 passed`.

- [ ] **Step 3: Run the full baseline**

```bash
DEEPSEEK_API_KEY=test uv run pytest -q
```

Expected: all current tests pass; integration tests may remain explicitly
skipped when `TEST_DATABASE_URL` is absent.

- [ ] **Step 4: Commit**

```bash
git add tests/test_llm.py
git commit -m "test: repair structured output baseline"
```

## Task 2: Correct the Provider Execution Contract

- [ ] **Step 1: Write the failing registry test**

Update `tests/test_research_tool_registry.py`:

```python
@pytest.mark.asyncio
async def test_registry_passes_database_session_to_provider():
    """验证注册表把当前数据库会话传给工具提供者"""
    db = AsyncMock()
    provider = AsyncMock()
    provider.execute.return_value = ToolExecutionResult(
        success=True,
        data={"result": "ok"},
    )
    registry = ResearchToolRegistry()
    registry.register(
        ResearchToolDefinition(name="knowledge.search"),
        provider=provider,
    )

    result = await registry.execute(
        db,
        _ctx(),
        "knowledge.search",
        {"query": "test"},
    )

    assert result.success is True
    provider.execute.assert_awaited_once_with(
        db,
        _ctx(),
        {"query": "test"},
    )
```

Also update existing calls in this test file to pass `AsyncMock()` as the first
argument.

- [ ] **Step 2: Verify the test fails**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_tool_registry.py::test_registry_passes_database_session_to_provider \
  -q
```

Expected: failure because `ResearchToolRegistry.execute()` does not accept
`db`.

- [ ] **Step 3: Change the provider protocol**

Replace the protocol method in `src/research/tools/providers.py`:

```python
class ResearchToolProvider(Protocol):
    """研究工具提供者接口"""

    async def execute(
        self,
        db: AsyncSession,
        context: ToolExecutionContext,
        arguments: dict,
    ) -> ToolExecutionResult:
        """使用当前事务执行工具并返回结构化结果"""
        ...
```

Import `AsyncSession` from `sqlalchemy.ext.asyncio`.

- [ ] **Step 4: Change registry execution**

Change `src/research/tools/registry.py`:

```python
async def execute(
    self,
    db: AsyncSession,
    context: ToolExecutionContext,
    tool_name: str,
    arguments: dict,
) -> ToolExecutionResult:
    ...
    result = await provider.execute(db, context, arguments)
```

Import `AsyncSession`. Keep permission and hook checks before provider
execution.

- [ ] **Step 5: Change the step executor**

Modify `src/research/execution.py`:

```python
tool_result = await self._registry.execute(
    db,
    context,
    step.tool_name,
    step.input_payload,
)
```

- [ ] **Step 6: Run affected tests**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_tool_registry.py \
  tests/test_research_retrieval_flow.py \
  tests/test_research_specialists.py -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/research/tools/providers.py src/research/tools/registry.py \
  src/research/execution.py tests/test_research_tool_registry.py
git commit -m "refactor: pass database session to research providers"
```

## Task 3: Assemble Executable Built-In Providers

- [ ] **Step 1: Write provider assembly tests**

Replace definition-only expectations in
`tests/test_research_provider_registry.py` with:

```python
def test_builtin_provider_assembly_registers_executable_tools():
    """验证内置工具同时注册定义和可执行提供者"""
    registry = ResearchToolRegistry()
    dependencies = BuiltinResearchDependencies(
        source_gateway=AsyncMock(),
        web_search_service=AsyncMock(),
        web_fetcher=AsyncMock(),
    )

    register_builtin_research_tools(registry, dependencies)

    assert {tool.name for tool in registry.list_tools()} == {
        "knowledge.search",
        "web.search",
        "web.fetch",
    }
    assert registry.has_provider("knowledge.search")
    assert registry.has_provider("web.search")
    assert registry.has_provider("web.fetch")
```

- [ ] **Step 2: Add provider introspection**

Add to `src/research/tools/registry.py`:

```python
def has_provider(self, name: str) -> bool:
    """返回指定工具是否绑定可执行提供者"""
    return name in self._providers
```

- [ ] **Step 3: Add the secured fetch specialist**

Create `src/research/specialists/fetch.py`:

```python
"""
研究网页全文抓取 Specialist。

Workflow:
1. 接收已规划的 URL。
2. 通过 SecuredFetcher 执行 SSRF 和响应大小控制。
3. 返回带 URL 和正文摘录的标准证据。
"""
from datetime import datetime, timezone

from src.research.evidence import EvidenceInput
from src.research.tools.schemas import ToolExecutionContext, ToolExecutionResult


class WebFetchResearcher:
    """抓取经过安全校验的公开网页并生成证据"""

    def __init__(self, fetcher):
        """注入安全网页抓取器

        参数:
            fetcher: 提供异步 fetch(url) 方法的抓取器

        返回:
            None
        """
        self._fetcher = fetcher

    async def execute(self, db, context, arguments) -> ToolExecutionResult:
        """抓取 URL 并返回标准化证据

        参数:
            db: 当前数据库会话，本工具不直接写入
            context: 研究工具执行上下文
            arguments: 必须包含 url，可选 title 和 query

        返回:
            ToolExecutionResult: 包含一条网页全文证据
        """
        url = str(arguments.get("url", "")).strip()
        if not url:
            return ToolExecutionResult(success=False, error="缺少 url 参数")
        content = await self._fetcher.fetch(url)
        evidence = EvidenceInput(
            workspace_id=context.workspace_id,
            task_id=context.task_id,
            step_id=context.step_id,
            source_type="web_page",
            source_ref=url,
            title=str(arguments.get("title") or url),
            excerpt=content[:2000],
            query=str(arguments.get("query") or ""),
            retrieved_at=datetime.now(timezone.utc),
            confidence=None,
        )
        return ToolExecutionResult(
            success=True,
            data={"evidence": [evidence.model_dump(mode="json")]},
        )
```

- [ ] **Step 4: Replace built-in provider assembly**

Update `src/research/providers/builtin.py` so dependencies and providers are
bound together:

```python
@dataclass(frozen=True)
class BuiltinResearchDependencies:
    source_gateway: object
    web_search_service: object
    web_fetcher: object


def register_builtin_research_tools(
    registry: ResearchToolRegistry,
    deps: BuiltinResearchDependencies,
) -> None:
    """注册内置研究工具定义及其可执行提供者"""
    registry.register(
        ResearchToolDefinition(
            name="knowledge.search",
            description="Search authorized internal knowledge",
            risk_level="read",
            data_scope="workspace",
            cost_class="low",
            timeout_seconds=30,
            max_attempts=2,
            provider_name="builtin.knowledge",
            provider_version="1",
        ),
        provider=KnowledgeResearcher(deps.source_gateway),
    )
    registry.register(
        ResearchToolDefinition(
            name="web.search",
            description="Search public web",
            risk_level="read",
            data_scope="public_web",
            cost_class="medium",
            timeout_seconds=30,
            max_attempts=3,
            provider_name="builtin.web_search",
            provider_version="1",
        ),
        provider=WebResearcher(deps.web_search_service),
    )
    registry.register(
        ResearchToolDefinition(
            name="web.fetch",
            description="Fetch validated public page content",
            risk_level="read",
            data_scope="public_web",
            cost_class="medium",
            timeout_seconds=15,
            max_attempts=2,
            provider_name="builtin.web_fetch",
            provider_version="1",
        ),
        provider=WebFetchResearcher(deps.web_fetcher),
    )
```

- [ ] **Step 5: Run provider tests**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_provider_registry.py \
  tests/test_research_specialists.py \
  tests/test_research_web_fetch.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/research/providers/builtin.py src/research/specialists/fetch.py \
  src/research/tools/registry.py tests/test_research_provider_registry.py
git commit -m "feat: assemble executable research providers"
```

## Task 4: Implement Ready-Step Claim and Dispatch

- [ ] **Step 1: Write dispatcher failure tests**

Create `tests/test_research_dispatch.py` covering:

```python
@pytest.mark.asyncio
async def test_dispatch_ready_claims_before_enqueue(db_session):
    """验证步骤先持久化认领，再发送到队列"""
    ...
    count = await service.dispatch_ready(task_id="R1")
    assert count == 1
    assert (await db_session.get(ResearchStep, "R1:1:a")).status == "running"
    queue.enqueue_step.assert_awaited_once_with("R1:1:a")


@pytest.mark.asyncio
async def test_enqueue_failure_releases_claim(db_session):
    """验证队列发送失败后步骤恢复为 ready"""
    ...
    queue.enqueue_step.side_effect = RuntimeError("redis down")
    with pytest.raises(RuntimeError, match="redis down"):
        await service.dispatch_ready(task_id="R1")
    step = await db_session.get(ResearchStep, "R1:1:a")
    assert step.status == "ready"
    assert step.owner is None
```

Use a session factory that opens a fresh SQLAlchemy session rather than reusing
the same fixture transaction.

- [ ] **Step 2: Add task-scoped claiming**

Change `ResearchStepService.claim_next()` in `src/research/steps.py`:

```python
async def claim_next(
    self,
    db: AsyncSession,
    *,
    owner: str,
    limit: int = 1,
    task_id: str | None = None,
) -> list[ResearchStep]:
    ...
    conditions = [
        ResearchStep.status == ResearchStepStatus.READY.value,
        ResearchStep.available_at <= now,
    ]
    if task_id is not None:
        conditions.append(ResearchStep.task_id == task_id)
    query = (
        select(ResearchStep)
        .where(*conditions)
        .order_by(ResearchStep.available_at, ResearchStep.id)
        .limit(limit)
    )
```

Build all filters before `ORDER BY` and `LIMIT`; do not append a `WHERE`
clause to an already limited SQLAlchemy statement.

- [ ] **Step 3: Add claim release**

Add to `src/research/steps.py`:

```python
async def release_claim(
    self,
    db: AsyncSession,
    step_id: str,
    *,
    owner: str,
) -> bool:
    """队列发送失败时释放指定所有者的步骤租约"""
    result = await db.execute(
        update(ResearchStep)
        .where(
            ResearchStep.id == step_id,
            ResearchStep.status == ResearchStepStatus.RUNNING.value,
            ResearchStep.owner == owner,
        )
        .values(
            status=ResearchStepStatus.READY.value,
            owner=None,
            lease_expires_at=None,
            updated_at=datetime.now(timezone.utc),
        )
    )
    await db.flush()
    return result.rowcount == 1
```

- [ ] **Step 4: Create the dispatcher service**

Create `src/research/dispatch.py` with `ResearchStepDispatcher`. Its
`dispatch_ready(task_id)` method must:

1. open a session;
2. claim up to `max_concurrent_steps` using owner
   `dispatch:{uuid.uuid4().hex}`;
3. commit;
4. enqueue each step;
5. release only the failed step claim in a new session;
6. return the successfully enqueued count.

The enqueue loop must re-raise the first queue error after releasing the claim.

- [ ] **Step 5: Run dispatcher tests**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_dispatch.py \
  tests/test_research_step_service.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/research/dispatch.py src/research/steps.py \
  tests/test_research_dispatch.py tests/test_research_step_service.py
git commit -m "feat: claim and dispatch ready research steps"
```

## Task 5: Add Stage Coordination and Idempotency

- [ ] **Step 1: Write coordinator tests**

Create `tests/test_research_pipeline.py` for:

- `queue_synthesis_if_complete()` transitions `running -> synthesizing` once;
- duplicate calls enqueue synthesis once;
- `queue_validation()` transitions `synthesizing -> validating` once;
- `complete_and_queue_delivery()` transitions `validating -> completed` and
  enqueues delivery once;
- repair transitions `validating -> running` and calls ready-step dispatcher.

- [ ] **Step 2: Create pipeline coordinator**

Create `src/research/pipeline.py` with:

```python
class ResearchPipelineCoordinator:
    """使用任务状态转换协调研究阶段和队列派发"""

    async def queue_synthesis_if_complete(
        self,
        db: AsyncSession,
        task_id: str,
    ) -> bool:
        """全部步骤完成时原子进入综合阶段并派发一次"""
        ...

    async def queue_validation(
        self,
        db: AsyncSession,
        task_id: str,
    ) -> bool:
        """报告草稿落库后进入验证阶段并派发一次"""
        ...

    async def complete_and_queue_delivery(
        self,
        db: AsyncSession,
        task_id: str,
    ) -> bool:
        """报告通过质量门后完成任务并派发投递"""
        ...
```

Each method catches `InvalidResearchTransitionError` and returns `False` for a
duplicate queue message. It must not swallow other exceptions.

The target task status is the durable dispatch intent. Commit the compare-and-
set transition before calling Taskiq. If enqueue raises synchronously, record
the error and re-raise; Week 2 adds reconciliation that replays target states
left behind by a process crash. Do not claim exactly-once queue delivery.

- [ ] **Step 3: Move transition ownership out of services**

Change `ReportSynthesisService.synthesize()`:

- require the task to already be `synthesizing`;
- remove its `running -> synthesizing` transition.

Change `CitationReviewService.review()`:

- require the task to already be `validating`;
- remove its `synthesizing -> validating` transition.

- [ ] **Step 4: Wire worker tasks**

Update `src/research/tasks.py`:

- instantiate real `KnowledgeService`, `ResearchSourceGateway`,
  `WebSearchService`, and `SecuredFetcher`;
- call `register_builtin_research_tools()` with those dependencies;
- instantiate `ResearchStepDispatcher` and
  `ResearchPipelineCoordinator`;
- after planning commit, call `dispatch_ready(task_id)`;
- in `run_research_step`, pass the persisted `step.owner` to the executor;
- after step commit, dispatch newly ready dependents, then ask the coordinator
  to queue synthesis;
- after synthesis commit, queue validation;
- after validation pass, mark the report validated and queue delivery;
- after repair steps persist, return to `running` and dispatch them.

Every stage worker must verify the expected durable task status. Before an
expensive LLM call, check whether the expected report or review artifact
already exists and return it for duplicate queue messages.

- [ ] **Step 5: Fix delivery content**

Change `src/research/delivery.py`:

```python
content = (
    f"研究任务 {snapshot.task_id} 已完成\n"
    f"问题：{snapshot.question}\n"
    f"质量状态：{snapshot.quality_status}\n\n"
    f"{snapshot.body}"
)
```

Remove the Phase 1 disclaimer from validated reports.

- [ ] **Step 6: Add delivery body assertion**

Update `tests/test_research_delivery.py` to assert that:

- the report body is present;
- `"当前为 Phase 1"` is absent.

- [ ] **Step 7: Run pipeline tests**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_pipeline.py \
  tests/test_research_tasks.py \
  tests/test_research_delivery.py \
  tests/test_research_synthesizer.py \
  tests/test_research_citation_reviewer.py -q
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/research/pipeline.py src/research/tasks.py \
  src/research/synthesis/service.py src/research/review/service.py \
  src/research/delivery.py tests/test_research_pipeline.py \
  tests/test_research_tasks.py tests/test_research_delivery.py
git commit -m "fix: complete research pipeline stage handoffs"
```

## Task 6: Add a Deterministic Full-Pipeline Test

- [ ] **Step 1: Add the test**

Extend `tests/test_research_pipeline.py` with one test that uses:

- real ORM models and services;
- fake structured Supervisor output with knowledge and web steps;
- fake providers returning two evidence records;
- fake synthesizer output with evidence bindings;
- fake citation review returning `pass`;
- fake WeChat client.

Assert:

```python
assert task.status == "completed"
assert report.report_status == "validated"
assert delivery.status == "delivered"
assert len(evidence_rows) == 2
assert fake_wecom.send_text.await_count == 1
```

Add a second scenario where planning requires approval, approval resumes the
task, and the same dispatcher completes the remaining pipeline.

- [ ] **Step 2: Run the deterministic path**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_pipeline.py::test_full_research_pipeline_reaches_delivery \
  -q
```

Expected: `1 passed`.

- [ ] **Step 3: Run the Week 1 gate**

```bash
DEEPSEEK_API_KEY=test uv run pytest -q
```

Expected: no failures.

- [ ] **Step 4: Update project state**

Update:

- `docs/agent/active-context.md`;
- `docs/agent/troubleshooting.md`;
- `docs/agent/upgrade-roadmap.md`.

State only the pipeline behavior proven by the tests. Keep MCP, live
evaluation, and distributed tracing described as reserved or incomplete.

- [ ] **Step 5: Commit**

```bash
git add tests/test_research_pipeline.py docs/agent/active-context.md \
  docs/agent/troubleshooting.md docs/agent/upgrade-roadmap.md
git commit -m "test: verify end to end research pipeline"
```
