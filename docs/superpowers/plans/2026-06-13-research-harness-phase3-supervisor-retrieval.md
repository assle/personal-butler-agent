# Research Harness Phase 3: Supervisor and Retrieval Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixture planner with a structured LLM Supervisor, execute isolated knowledge and public-web retrieval steps, and persist normalized evidence with provenance.

**Architecture:** The Supervisor produces validated `PlanDraft` JSON and never calls retrieval directly. Step executors resolve tools from a governed registry; retrieval specialists receive minimum context and write evidence through one evidence service.

**Tech Stack:** LangChain ChatOpenAI, LangGraph, Pydantic v2, SQLAlchemy async, ChromaDB, Tavily/httpx, Taskiq, pytest

---

## File Map

**New evidence and tools**

- `src/models/research_evidence.py`: normalized evidence rows.
- `src/research/tools/schemas.py`: tool metadata and execution contracts.
- `src/research/tools/registry.py`: governed tool registration and lookup.
- `src/research/tools/providers.py`: provider protocol.
- `src/research/evidence.py`: deduplication and persistence.
- `src/research/sources.py`: workspace-authorized source gateway.

**New Supervisor and specialists**

- `src/research/supervisor/__init__.py`
- `src/research/supervisor/prompts.py`
- `src/research/supervisor/planner.py`
- `src/research/supervisor/service.py`
- `src/research/specialists/__init__.py`
- `src/research/specialists/knowledge.py`
- `src/research/specialists/web.py`
- `src/research/specialists/schemas.py`

**Modified runtime**

- `src/llm/client.py`: typed structured-output invocation.
- `src/research/tasks.py`: real planning and step executors.
- `src/research/service.py`: task stage transitions.
- `src/knowledge/service.py`: explicit research scope input.
- `src/search/service.py`: provider error classification.
- `src/main.py`: construct registry and Supervisor dependencies.
- Alembic revision for evidence.

**Tests**

- `tests/test_research_tool_registry.py`
- `tests/test_research_evidence_service.py`
- `tests/test_research_source_gateway.py`
- `tests/test_research_supervisor.py`
- `tests/test_research_specialists.py`
- `tests/test_research_retrieval_flow.py`

### Task 1: Add Structured LLM Output Support

**Files:**
- Modify: `src/llm/client.py`
- Test: `tests/test_llm.py`

- [ ] **Step 1: Write failing typed-output test**

```python
@pytest.mark.asyncio
async def test_ainvoke_structured_returns_validated_model():
    """验证结构化调用返回 Pydantic 模型"""
    client = LLMClient()
    client._model = fake_structured_model({"objective": "compare", "steps": []})
    result = await client.ainvoke_structured(
        messages=[{"role": "user", "content": "compare"}],
        schema=PlanDraft,
        temperature=0.1,
    )
    assert isinstance(result, PlanDraft)
```

- [ ] **Step 2: Run test**

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_llm.py -q
```

Expected: FAIL because `ainvoke_structured` is missing.

- [ ] **Step 3: Implement structured invocation**

```python
async def ainvoke_structured(
    self,
    messages: list[dict[str, str]] | list[BaseMessage],
    *,
    schema: type[BaseModel],
    temperature: float = 0.1,
) -> BaseModel:
    """调用模型并按 Pydantic Schema 校验输出

    参数:
        messages: 模型消息
        schema: 目标 Pydantic 模型类型
        temperature: 生成温度

    返回:
        BaseModel: 已通过 Schema 校验的结构化结果
    """
    runnable = self._model.with_structured_output(schema)
    return await runnable.ainvoke(messages, temperature=temperature)
```

- [ ] **Step 4: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_llm.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/llm/client.py tests/test_llm.py
git commit -m "feat: support structured llm outputs"
```

### Task 2: Add Evidence Model and Service

**Files:**
- Create: `src/models/research_evidence.py`
- Create: `src/research/evidence.py`
- Modify: `src/models/__init__.py`
- Create: Alembic revision
- Test: `tests/test_research_evidence_service.py`

- [ ] **Step 1: Write evidence deduplication tests**

```python
@pytest.mark.asyncio
async def test_evidence_is_deduplicated_by_workspace_and_content_hash(db_session):
    """验证同工作空间相同来源片段只保存一次"""
    service = ResearchEvidenceService()
    first = await service.store(db_session, evidence_input())
    second = await service.store(db_session, evidence_input())
    assert second.id == first.id


@pytest.mark.asyncio
async def test_same_hash_in_different_workspace_is_isolated(db_session):
    """验证不同工作空间的证据不会互相复用"""
```

- [ ] **Step 2: Add evidence schema**

```python
class ResearchEvidence(Base):
    """可追溯研究证据"""

    __tablename__ = "research_evidence"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "content_hash",
            name="uq_research_evidence_hash",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    step_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(2048), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    publisher: Mapped[str | None] = mapped_column(String(512), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
```

- [ ] **Step 3: Implement normalized input**

```python
class EvidenceInput(BaseModel):
    """研究证据写入输入"""

    workspace_id: str
    task_id: str
    step_id: str
    source_type: Literal["knowledge", "web"]
    source_ref: str
    title: str
    publisher: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    excerpt: str
    query: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    metadata: dict = Field(default_factory=dict)
```

Hash normalized `source_ref + "\n" + excerpt`; trim empty excerpts and reject
evidence without a stable source reference.

- [ ] **Step 4: Apply migration and verify**

```bash
DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  DEEPSEEK_API_KEY=test uv run alembic revision --autogenerate \
  -m "add research evidence"
DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  DEEPSEEK_API_KEY=test uv run alembic upgrade head
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_evidence_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/models/research_evidence.py src/models/__init__.py \
  src/research/evidence.py tests/test_research_evidence_service.py \
  alembic/versions
git commit -m "feat: persist normalized research evidence"
```

### Task 3: Add Governed Research Tool Registry

**Files:**
- Create: `src/research/tools/__init__.py`
- Create: `src/research/tools/schemas.py`
- Create: `src/research/tools/providers.py`
- Create: `src/research/tools/registry.py`
- Test: `tests/test_research_tool_registry.py`

- [ ] **Step 1: Write registry tests**

```python
def test_registry_rejects_duplicate_tool_names():
    """验证工具名称不可重复注册"""
    registry = ResearchToolRegistry()
    registry.register(tool_definition("knowledge.search"))
    with pytest.raises(DuplicateResearchToolError):
        registry.register(tool_definition("knowledge.search"))


@pytest.mark.asyncio
async def test_registry_checks_permission_before_provider_call():
    """验证工具执行前先经过权限引擎"""
    permission = Mock(return_value=deny_decision())
    provider = AsyncMock()
    registry = ResearchToolRegistry(permission_engine=permission)
    registry.register(tool_definition("web.search", provider=provider))
    with pytest.raises(ResearchToolDeniedError):
        await registry.execute(tool_context(), "web.search", {"query": "x"})
    provider.execute.assert_not_awaited()
```

- [ ] **Step 2: Define tool contracts**

```python
class ResearchToolDefinition(BaseModel):
    """研究工具注册信息"""

    name: str
    description: str
    risk_level: Literal["read", "internal_write", "external_action"]
    data_scope: Literal["user", "workspace", "public_web"]
    cost_class: Literal["low", "medium", "high"]
    timeout_seconds: int = Field(ge=1, le=300)
    max_attempts: int = Field(ge=1, le=5)
    provider_name: str
    provider_version: str


class ResearchToolProvider(Protocol):
    """研究工具提供者接口"""

    async def execute(
        self,
        context: ToolExecutionContext,
        arguments: dict,
    ) -> ToolExecutionResult:
        """执行工具并返回结构化结果"""
```

- [ ] **Step 3: Implement execution order**

`ResearchToolRegistry.execute()` performs:

1. definition lookup;
2. `BeforeTool` hooks;
3. permission decision;
4. timeout-wrapped provider execution;
5. `AfterTool` hooks;
6. usage/event recording.

- [ ] **Step 4: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_tool_registry.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/research/tools tests/test_research_tool_registry.py
git commit -m "feat: register governed research tools"
```

### Task 4: Add Workspace-Authorized Source Gateway

**Files:**
- Create: `src/research/sources.py`
- Modify: `src/knowledge/service.py`
- Test: `tests/test_research_source_gateway.py`

- [ ] **Step 1: Write authorization tests**

```python
@pytest.mark.asyncio
async def test_gateway_passes_immutable_scope_to_knowledge_service():
    """验证知识检索使用任务固定权限范围"""
    knowledge = AsyncMock()
    gateway = ResearchSourceGateway(knowledge=knowledge, web=AsyncMock())
    await gateway.search_knowledge(
        source_context(
            workspace_id="ws-a",
            user_id="open-u1",
            group_ids=["group-1"],
        ),
        query="policy",
        limit=5,
    )
    knowledge.search_research.assert_awaited_once()


@pytest.mark.asyncio
async def test_gateway_rejects_group_not_in_access_scope():
    """验证任务不能扩大群知识范围"""
```

- [ ] **Step 2: Add explicit research scope**

```python
class ResearchAccessScope(BaseModel):
    """研究任务不可变数据范围"""

    workspace_id: str
    user_id: str
    include_public: bool = True
    group_ids: tuple[str, ...] = ()
    allow_web: bool = True
```

Add `KnowledgeService.search_research(query, access_scope, db, domains, limit,
llm)` rather than overloading chat-type semantics. It builds explicit public,
user, and authorized-group filters.

- [ ] **Step 3: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_source_gateway.py tests/test_knowledge_service.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/research/sources.py src/knowledge/service.py \
  tests/test_research_source_gateway.py tests/test_knowledge_service.py
git commit -m "feat: authorize research source access"
```

### Task 5: Implement Structured Supervisor Planning

**Files:**
- Create: `src/research/supervisor/__init__.py`
- Create: `src/research/supervisor/prompts.py`
- Create: `src/research/supervisor/planner.py`
- Create: `src/research/supervisor/service.py`
- Modify: `src/research/tasks.py`
- Test: `tests/test_research_supervisor.py`

- [ ] **Step 1: Write planning contract tests**

```python
@pytest.mark.asyncio
async def test_supervisor_generates_and_validates_plan():
    """验证 Supervisor 输出经过本地校验后才持久化"""
    llm = AsyncMock()
    llm.ainvoke_structured.return_value = valid_plan_draft()
    supervisor = ResearchSupervisor(
        llm=llm,
        validator=PlanValidator({"knowledge.search", "web.search"}),
        plan_service=AsyncMock(),
        approval_policy=ApprovalPolicy(250_000),
    )
    result = await supervisor.plan(task_snapshot())
    assert result.plan.objective
    supervisor._plan_service.persist.assert_awaited_once()


@pytest.mark.asyncio
async def test_supervisor_does_not_execute_tools_while_planning():
    """验证规划阶段不能调用检索工具"""
```

- [ ] **Step 2: Write the planning prompt**

The system prompt must state:

```text
You are a research planning supervisor.
Return only the PlanDraft schema.
Do not claim to have searched sources.
Do not invoke retrieval during planning.
Use only tools listed in ALLOWED_TOOLS.
Every step must have a verifiable output and bounded dependencies.
```

Inject task question, immutable access scope summary, available tool catalog,
and budget limits.

- [ ] **Step 3: Implement Supervisor service**

`plan(task_id)` transitions `submitted -> planning`, requests structured output,
validates it, persists it, evaluates approval, then transitions to either
`awaiting_approval` or `running` and activates root steps. Emit
`HookEvent.AFTER_PLAN` after local validation and before activation; critical
hook failure leaves the task failed without running retrieval.

- [ ] **Step 4: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_supervisor.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/research/supervisor src/research/tasks.py \
  tests/test_research_supervisor.py
git commit -m "feat: plan research with a structured supervisor"
```

### Task 6: Implement Knowledge Research Specialist

**Files:**
- Create: `src/research/specialists/__init__.py`
- Create: `src/research/specialists/schemas.py`
- Create: `src/research/specialists/knowledge.py`
- Test: `tests/test_research_specialists.py`

- [ ] **Step 1: Write specialist test**

```python
@pytest.mark.asyncio
async def test_knowledge_specialist_returns_evidence_inputs_only():
    """验证知识 Specialist 不生成最终结论"""
    gateway = AsyncMock()
    gateway.search_knowledge.return_value = [knowledge_result()]
    specialist = KnowledgeResearcher(gateway)
    result = await specialist.execute(step_context(), {"query": "policy"})
    assert result.summary == "1 internal evidence item"
    assert len(result.evidence) == 1
    assert result.evidence[0].source_type == "knowledge"
```

- [ ] **Step 2: Implement specialist result**

```python
class RetrievalResult(BaseModel):
    """检索 Specialist 结构化结果"""

    summary: str
    evidence: list[EvidenceInput]
    follow_up_queries: list[str] = Field(default_factory=list)
    degraded: bool = False
    degradation_reason: str | None = None
```

The specialist maps `KnowledgeChunkResult` to evidence and never writes report
prose.

- [ ] **Step 3: Register `knowledge.search`**

Definition:

```python
ResearchToolDefinition(
    name="knowledge.search",
    description="Search authorized internal knowledge and return evidence",
    risk_level="read",
    data_scope="workspace",
    cost_class="low",
    timeout_seconds=30,
    max_attempts=2,
    provider_name="builtin.knowledge",
    provider_version="1",
)
```

- [ ] **Step 4: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_specialists.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/research/specialists tests/test_research_specialists.py
git commit -m "feat: retrieve internal research evidence"
```

### Task 7: Implement Public Web Research Specialist

**Files:**
- Create: `src/research/specialists/web.py`
- Modify: `src/search/service.py`
- Test: `tests/test_research_specialists.py`
- Test: `tests/test_web_search_service.py`

- [ ] **Step 1: Make search failures explicit**

Add:

```python
class WebSearchUnavailableError(RuntimeError):
    """联网搜索供应商暂时不可用"""


async def search_strict(self, query: str) -> list[SearchResult]:
    """执行研究级联网搜索

    参数:
        query: 研究查询

    返回:
        list[SearchResult]: 归一化搜索结果
    """
```

Unlike chat search, `search_strict` raises typed provider errors instead of
silently returning an empty list on transport failure.

- [ ] **Step 2: Write web specialist tests**

```python
@pytest.mark.asyncio
async def test_web_specialist_preserves_url_and_retrieval_time():
    """验证网页证据保留 URL 与获取时间"""


@pytest.mark.asyncio
async def test_web_specialist_marks_provider_outage_as_degraded():
    """验证搜索故障被明确标记而不是伪造结果"""
```

- [ ] **Step 3: Register `web.search`**

Use `risk_level="read"`, `data_scope="public_web"`, `cost_class="medium"`,
timeout `30`, max attempts `3`.

Phase 3 stores search snippets as evidence. Full page fetching is added behind
the secured fetcher in Phase 5, so no unrestricted URL fetch is introduced
here.

- [ ] **Step 4: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_specialists.py tests/test_web_search_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/research/specialists/web.py src/search/service.py \
  tests/test_research_specialists.py tests/test_web_search_service.py
git commit -m "feat: retrieve public web research evidence"
```

### Task 8: Execute Retrieval Steps and Persist Evidence

**Files:**
- Modify: `src/research/tasks.py`
- Modify: `src/research/steps.py`
- Create: `src/research/execution.py`
- Test: `tests/test_research_retrieval_flow.py`

- [ ] **Step 1: Write end-to-end retrieval test**

```python
@pytest.mark.asyncio
async def test_ready_knowledge_and_web_steps_complete_independently(db_session):
    """验证知识与网页步骤独立执行并写入证据"""
    result = await execute_ready_steps(
        task=seed_planned_task(),
        registry=registry_with_fake_retrievers(),
        max_concurrency=2,
    )
    assert result.completed_kinds == {"knowledge_retrieval", "web_retrieval"}
    assert result.evidence_count == 2
```

- [ ] **Step 2: Implement step executor**

```python
class ResearchStepExecutor:
    """执行已认领的研究工具步骤"""

    async def execute(
        self,
        db: AsyncSession,
        step_id: str,
        worker_id: str,
    ) -> StepExecutionResult:
        """执行单个研究步骤

        参数:
            db: 异步数据库会话
            step_id: 已派发步骤 ID
            worker_id: Worker 唯一标识

        返回:
            StepExecutionResult: 结果引用与解锁步骤列表
        """
```

It verifies lease ownership, executes the registry tool, stores each evidence
item, sets `result_ref` to `evidence:<comma-separated-ids>`, completes the step,
and returns newly ready dependent IDs.

- [ ] **Step 3: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_retrieval_flow.py \
  tests/test_research_tasks.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/research/execution.py src/research/tasks.py \
  src/research/steps.py tests/test_research_retrieval_flow.py \
  tests/test_research_tasks.py
git commit -m "feat: execute parallel research retrieval steps"
```

### Task 9: Wire Runtime and Document Phase 3

**Files:**
- Modify: `src/main.py`
- Modify: `src/research/__init__.py`
- Modify: `docs/agent/active-context.md`
- Modify: `docs/agent/patterns.md`
- Modify: `docs/agent/decisions.md`
- Modify: `CLAUDE.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Construct dependencies once per process**

Create the tool registry from existing `KnowledgeService`,
`WebSearchService`, governance, event, usage, and evidence services. Worker
modules must build their own process-local clients.

- [ ] **Step 2: Update architecture docs**

Add Supervisor, specialist, tools, and evidence modules to Architecture.
Copy `CLAUDE.md` to `AGENTS.md` after edits.

- [ ] **Step 3: Run Phase 3 gate**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_supervisor.py \
  tests/test_research_source_gateway.py \
  tests/test_research_specialists.py \
  tests/test_research_evidence_service.py \
  tests/test_research_retrieval_flow.py -q
DEEPSEEK_API_KEY=test uv run pytest -q
cmp -s CLAUDE.md AGENTS.md
```

Expected: all commands exit `0`.

- [ ] **Step 4: Commit**

```bash
git add src/main.py src/research/__init__.py docs/agent CLAUDE.md AGENTS.md
git commit -m "docs: record supervisor retrieval architecture"
```
