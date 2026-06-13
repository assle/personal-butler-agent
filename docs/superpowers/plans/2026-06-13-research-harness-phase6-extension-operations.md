# Research Harness Phase 6: Skills, Providers, Delivery, and Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add on-demand research skills, a stable provider extension boundary, production report delivery, quality evaluation, and operational release documentation.

**Architecture:** Skills provide declarative research guidance and are selected by the Supervisor; providers expose governed tools through the existing registry. The release keeps built-in providers enabled by default, treats future MCP as one adapter, and completes delivery/observability without creating a universal plugin platform.

**Tech Stack:** Pydantic v2, YAML/frontmatter parsing, Taskiq, Enterprise WeChat API, PostgreSQL events, pytest, GitHub Actions

---

## File Map

**New skill and provider modules**

- `src/research/skills/__init__.py`
- `src/research/skills/schemas.py`
- `src/research/skills/catalog.py`
- `src/research/skills/loader.py`
- `src/research/providers/__init__.py`
- `src/research/providers/builtin.py`
- `src/research/providers/mcp.py`: disabled adapter contract only.
- `research_skills/general/SKILL.md`: built-in general research method.

**New evaluation and operations**

- `src/research/evaluation/__init__.py`
- `src/research/evaluation/schemas.py`
- `src/research/evaluation/runner.py`
- `tests/fixtures/research_eval_cases.json`
- `src/cli/evaluate_research.py`
- `docs/operations/research-runbook.md`
- `.github/workflows/test.yml`

**Modified runtime**

- `src/research/supervisor/service.py`
- `src/research/tools/registry.py`
- `src/research/delivery.py`
- `src/research/submission.py`
- `src/wechat/app_client.py`
- `src/config.py`
- `src/main.py`
- `pyproject.toml`
- `uv.lock`

**Tests**

- `tests/test_research_skill_catalog.py`
- `tests/test_research_skill_loader.py`
- `tests/test_research_provider_registry.py`
- `tests/test_research_delivery.py`
- `tests/test_research_evaluation.py`
- `tests/test_research_observability.py`
- `tests/test_research_release_flow.py`

### Task 1: Define Research Skill Format

**Files:**
- Create: `src/research/skills/__init__.py`
- Create: `src/research/skills/schemas.py`
- Create: `research_skills/general/SKILL.md`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Test: `tests/test_research_skill_catalog.py`

- [ ] **Step 1: Add YAML dependency**

Add:

```toml
"pyyaml>=6.0",
```

Run:

```bash
uv lock
```

Expected: `uv.lock` contains PyYAML.

- [ ] **Step 2: Write manifest tests**

```python
def test_general_skill_manifest_is_valid():
    """验证内置通用研究 Skill 元数据完整"""
    skill = parse_skill(Path("research_skills/general/SKILL.md"))
    assert skill.manifest.name == "general-research"
    assert skill.manifest.version == "1.0.0"
    assert skill.manifest.allowed_tools == [
        "knowledge.search",
        "web.search",
        "web.fetch",
    ]
```

- [ ] **Step 3: Define manifest**

```python
class ResearchSkillManifest(BaseModel):
    """研究 Skill 元数据"""

    name: str
    version: str
    description: str
    applies_to: list[str]
    allowed_tools: list[str]
    evidence_policy: str
    report_schema: str
    reviewer_policy: str
```

- [ ] **Step 4: Create general skill**

Use frontmatter:

```yaml
---
name: general-research
version: 1.0.0
description: General internal and public-web research
applies_to: [factual, comparison, report]
allowed_tools: [knowledge.search, web.search, web.fetch]
evidence_policy: claim-level
report_schema: structured-report-v1
reviewer_policy: strict-citation-v1
---
```

The body contains the approved research method, source hierarchy, conflict
handling, and report expectations. It contains no secrets or environment
specific identifiers.

- [ ] **Step 5: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_skill_catalog.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/research/skills research_skills pyproject.toml uv.lock \
  tests/test_research_skill_catalog.py
git commit -m "feat: define on demand research skills"
```

### Task 2: Add Two-Level Skill Catalog and Loader

**Files:**
- Create: `src/research/skills/catalog.py`
- Create: `src/research/skills/loader.py`
- Modify: `src/research/supervisor/service.py`
- Test: `tests/test_research_skill_catalog.py`
- Test: `tests/test_research_skill_loader.py`

- [ ] **Step 1: Write catalog loading tests**

```python
def test_catalog_exposes_metadata_without_body():
    """验证基础 Prompt 只加载 Skill 目录"""
    catalog = ResearchSkillCatalog(Path("research_skills"))
    entries = catalog.list()
    assert entries[0].name == "general-research"
    assert "source hierarchy" not in entries[0].description.lower()


def test_loader_rejects_path_traversal():
    """验证 Skill 名称不能逃逸目录"""
    with pytest.raises(InvalidResearchSkillName):
        loader.load("../secret")
```

- [ ] **Step 2: Implement catalog and loader**

```python
class ResearchSkillCatalog:
    """扫描并提供研究 Skill 元数据目录"""

    def list(self) -> list[ResearchSkillSummary]:
        """返回可用 Skill 摘要"""


class ResearchSkillLoader:
    """按名称加载已登记 Skill 完整内容"""

    def load(self, name: str) -> LoadedResearchSkill:
        """加载并校验研究 Skill

        参数:
            name: Catalog 中的稳定 Skill 名称

        返回:
            LoadedResearchSkill: 元数据与正文
        """
```

Only names returned by the catalog can be loaded. Tool names in the manifest
must exist in the governed registry.

- [ ] **Step 3: Inject catalog then selected skill**

Supervisor base context contains skill summaries. After selecting a skill, its
full body is included in planning. Record selected name/version in the research
plan.

- [ ] **Step 4: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_skill_catalog.py \
  tests/test_research_skill_loader.py \
  tests/test_research_supervisor.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/research/skills src/research/supervisor/service.py \
  tests/test_research_skill_catalog.py tests/test_research_skill_loader.py \
  tests/test_research_supervisor.py
git commit -m "feat: load research skills on demand"
```

### Task 3: Consolidate Built-In Providers

**Files:**
- Create: `src/research/providers/__init__.py`
- Create: `src/research/providers/builtin.py`
- Modify: `src/research/tools/providers.py`
- Modify: `src/main.py`
- Test: `tests/test_research_provider_registry.py`

- [ ] **Step 1: Write provider registration tests**

```python
def test_builtin_provider_registers_expected_tools():
    """验证内置 Provider 注册受治理工具"""
    registry = ResearchToolRegistry(permission_engine=PermissionEngine())
    register_builtin_research_tools(registry, dependencies())
    assert registry.names() == {
        "knowledge.search",
        "web.search",
        "web.fetch",
    }
```

- [ ] **Step 2: Implement one provider assembly function**

```python
@dataclass(frozen=True)
class BuiltinResearchDependencies:
    """内置研究工具依赖"""

    source_gateway: ResearchSourceGateway
    web_fetcher: ResearchWebFetcher
    evidence_service: ResearchEvidenceService


def register_builtin_research_tools(
    registry: ResearchToolRegistry,
    dependencies: BuiltinResearchDependencies,
) -> None:
    """注册内置研究工具

    参数:
        registry: 受治理工具注册表
        dependencies: 内置工具依赖

    返回:
        None
    """
```

- [ ] **Step 3: Remove duplicate runtime wiring**

Both FastAPI and Taskiq worker processes call the same assembly function. They
may use process-local clients but must expose identical tool definitions.

- [ ] **Step 4: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_provider_registry.py \
  tests/test_research_tool_registry.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/research/providers src/research/tools/providers.py \
  src/main.py tests/test_research_provider_registry.py
git commit -m "refactor: assemble built in research providers"
```

### Task 4: Add Disabled-by-Default MCP Provider Contract

**Files:**
- Create: `src/research/providers/mcp.py`
- Modify: `src/config.py`
- Test: `tests/test_research_provider_registry.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write deny-by-default tests**

```python
def test_mcp_provider_is_disabled_by_default():
    """验证 MCP Provider 默认关闭"""
    settings = Settings(DEEPSEEK_API_KEY="test", _env_file=None)
    assert settings.research_mcp_enabled is False


def test_discovered_mcp_tool_requires_explicit_policy():
    """验证动态发现不等于授权"""
    provider = McpResearchProvider(approved_tools={})
    with pytest.raises(UnapprovedDynamicToolError):
        provider.definition_for(discovered_tool("search"))
```

- [ ] **Step 2: Add configuration contract**

```python
    research_mcp_enabled: bool = False
    research_mcp_config_file: str = ""
```

- [ ] **Step 3: Define adapter without enabling transport**

```python
class McpResearchProvider:
    """未来 MCP 研究工具适配器"""

    def __init__(self, approved_tools: dict[str, ApprovedDynamicTool]):
        """注入人工审核后的工具策略"""
```

The adapter translates approved tool metadata into
`ResearchToolDefinition`. Transport, OAuth, subscription, and automatic server
discovery remain out of scope and are not implemented.

- [ ] **Step 4: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_provider_registry.py tests/test_config.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/research/providers/mcp.py src/config.py \
  tests/test_research_provider_registry.py tests/test_config.py
git commit -m "feat: reserve governed mcp provider boundary"
```

### Task 5: Improve Enterprise WeChat Final Delivery

**Files:**
- Modify: `src/wechat/app_client.py`
- Modify: `src/research/delivery.py`
- Modify: `src/research/submission.py`
- Test: `tests/test_wecom_app_client.py`
- Test: `tests/test_research_delivery.py`

- [ ] **Step 1: Write segmented delivery tests**

```python
@pytest.mark.asyncio
async def test_long_report_sends_summary_then_numbered_segments():
    """验证长报告按 UTF-8 安全边界分段投递"""


@pytest.mark.asyncio
async def test_duplicate_delivery_uses_existing_wecom_msgids():
    """验证重复投递任务不会重复发送已成功分段"""
```

- [ ] **Step 2: Add message segmentation**

Expose:

```python
def split_text_utf8(
    content: str,
    *,
    max_bytes: int = 1900,
) -> list[str]:
    """按 UTF-8 字节与段落边界拆分文本

    参数:
        content: 待拆分报告文本
        max_bytes: 单段最大 UTF-8 字节数

    返回:
        list[str]: 保持字符完整的消息段
    """
```

- [ ] **Step 3: Persist per-segment delivery state**

Add `research_delivery_parts` through an Alembic revision with unique
`(workspace_id, task_id, part_index)`. Send summary first, then numbered report
parts. Mark each successful part so retry resumes from the first unsent part.

- [ ] **Step 4: Update user-facing status**

Submission response no longer says "Phase 1 unreviewed draft". It states:

```text
已创建研究任务 {task_id}。系统将规划检索范围；首次使用或高成本计划可能需要你批准。
```

Status output includes current stage, approval requirement, validated quality
status, and delivery state.

- [ ] **Step 5: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_wecom_app_client.py \
  tests/test_research_delivery.py \
  tests/test_research_submission.py -q
uv run alembic check
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/wechat/app_client.py src/research/delivery.py \
  src/research/submission.py tests/test_wecom_app_client.py \
  tests/test_research_delivery.py tests/test_research_submission.py \
  alembic/versions
git commit -m "feat: deliver validated research reports reliably"
```

### Task 6: Add Research Evaluation Runner

**Files:**
- Create: `src/research/evaluation/__init__.py`
- Create: `src/research/evaluation/schemas.py`
- Create: `src/research/evaluation/runner.py`
- Create: `tests/fixtures/research_eval_cases.json`
- Create: `src/cli/evaluate_research.py`
- Modify: `pyproject.toml`
- Test: `tests/test_research_evaluation.py`

- [ ] **Step 1: Define evaluation cases**

Fixture shape:

```json
[
  {
    "id": "comparison-001",
    "question": "Compare Taskiq and Celery for this async Python service.",
    "required_claim_topics": ["async support", "delivery semantics"],
    "required_source_types": ["knowledge", "web"],
    "forbidden_claims": ["Taskiq guarantees exactly-once execution"],
    "max_cost_microunits": 500000
  }
]
```

- [ ] **Step 2: Define metrics**

```python
class EvaluationResult(BaseModel):
    """单个研究评估结果"""

    case_id: str
    claim_topic_coverage: float
    citation_validity: float
    unsupported_material_claim_rate: float
    required_source_coverage: float
    estimated_cost_microunits: int
    latency_ms: int
```

- [ ] **Step 3: Implement offline scoring**

The default test runner scores stored fixture reports and reviews without live
LLM calls. A CLI flag `--live` may submit real tasks only when explicitly
requested.

Register:

```toml
butler-evaluate-research = "src.cli.evaluate_research:run"
```

- [ ] **Step 4: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_evaluation.py -q
DEEPSEEK_API_KEY=test uv run butler-evaluate-research \
  --cases tests/fixtures/research_eval_cases.json \
  --offline
```

Expected: tests pass and CLI prints deterministic JSON metrics.

- [ ] **Step 5: Commit**

```bash
git add src/research/evaluation src/cli/evaluate_research.py \
  tests/fixtures/research_eval_cases.json \
  tests/test_research_evaluation.py pyproject.toml uv.lock
git commit -m "feat: evaluate research quality and cost"
```

### Task 7: Verify Structured Observability

**Files:**
- Create: `src/research/observability.py`
- Modify: `src/research/events.py`
- Modify: `src/research/tasks.py`
- Test: `tests/test_research_observability.py`

- [ ] **Step 1: Write trace propagation tests**

```python
def test_trace_context_propagates_task_step_and_attempt():
    """验证 API、Worker 与工具日志共享追踪字段"""
    context = TraceContext(
        trace_id="trace-1",
        workspace_id="ws-a",
        task_id="R1",
        step_id="R1:1:web",
        attempt=2,
    )
    assert context.as_log_fields()["task_id"] == "R1"
```

- [ ] **Step 2: Implement trace context**

```python
@dataclass(frozen=True)
class TraceContext:
    """研究全链路追踪上下文"""

    trace_id: str
    workspace_id: str
    task_id: str
    step_id: str | None = None
    attempt: int | None = None

    def as_log_fields(self) -> dict[str, object]:
        """返回结构化日志字段"""
```

Use `contextvars.ContextVar` inside a process and explicit trace IDs in queue
payload metadata. Do not log prompts, secrets, or full source bodies.

On every terminal research or delivery outcome, emit
`HookEvent.AFTER_RESEARCH` with IDs, status, usage totals, validation outcome,
and delivery status. Metrics hook failure is non-critical and must not change a
completed task into failed.

- [ ] **Step 3: Verify metrics events**

Tests assert stage latency, token usage, estimated cost, provider state,
citation pass rate, repair rounds, and delivery status are representable from
events/usage rows.

- [ ] **Step 4: Commit**

```bash
git add src/research/observability.py src/research/events.py \
  src/research/tasks.py tests/test_research_observability.py
git commit -m "feat: trace research execution"
```

### Task 8: Add CI for Unit and PostgreSQL Integration Tests

**Files:**
- Create: `.github/workflows/test.yml`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add PostgreSQL and Redis services**

Workflow services:

```yaml
services:
  postgres:
    image: postgres:16
    env:
      POSTGRES_USER: butler
      POSTGRES_PASSWORD: butler
      POSTGRES_DB: butler_test
    ports:
      - 5432:5432
    options: >-
      --health-cmd "pg_isready -U butler"
      --health-interval 5s
      --health-timeout 5s
      --health-retries 10
  redis:
    image: redis:7
    ports:
      - 6379:6379
```

- [ ] **Step 2: Add verification steps**

```yaml
- run: uv sync --extra dev
- run: uv run alembic upgrade head
- run: uv run pytest -q
```

Environment includes placeholder DeepSeek key, test database URL, Redis URL,
and disables real external providers.

- [ ] **Step 3: Validate workflow syntax**

Run:

```bash
python3 - <<'PY'
from pathlib import Path
import yaml
yaml.safe_load(Path(".github/workflows/test.yml").read_text())
print("workflow yaml ok")
PY
```

Expected: `workflow yaml ok`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/test.yml pyproject.toml uv.lock
git commit -m "ci: test research harness with postgres and redis"
```

### Task 9: Write Operations Runbook and Final Documentation

**Files:**
- Create: `docs/operations/research-runbook.md`
- Modify: `.env.example`
- Modify: `deployment.md`
- Modify: `deployment.en.md`
- Modify: `docs/agent/active-context.md`
- Modify: `docs/agent/patterns.md`
- Modify: `docs/agent/decisions.md`
- Modify: `docs/agent/troubleshooting.md`
- Modify: `docs/agent/config-variables.md`
- Modify: `docs/agent/upgrade-roadmap.md`
- Modify: `CLAUDE.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Document process topology**

The runbook gives exact commands:

```bash
uv run alembic upgrade head
uv run uvicorn src.main:app --host 127.0.0.1 --port 8000
uv run taskiq worker --ack-type when_executed --workers 3 \
  --max-async-tasks 4 src.research.broker:broker src.research.tasks
```

- [ ] **Step 2: Document operational checks**

Include:

- PostgreSQL revision and connectivity;
- Redis connectivity and queue lag;
- stuck/expired leases;
- open provider circuits;
- approval backlog;
- citation validation failure rate;
- failed delivery parts;
- backup and rollback procedure.

- [ ] **Step 3: Update current architecture**

Root docs list Supervisor, specialists, governance, research tools, quality,
reliability, skills, evaluation, PostgreSQL, Redis, and Chroma boundaries.
Copy `CLAUDE.md` to `AGENTS.md`.

- [ ] **Step 4: Verify documentation**

```bash
rg -n "unreviewed_foundation|Phase 1 output|SQLite.*production" \
  README.md README.en.md deployment.md deployment.en.md \
  docs/agent CLAUDE.md AGENTS.md
cmp -s CLAUDE.md AGENTS.md
```

Expected: old Phase 1 language appears only in history/migration context;
root docs are identical.

- [ ] **Step 5: Commit**

```bash
git add docs/operations .env.example deployment.md deployment.en.md \
  docs/agent CLAUDE.md AGENTS.md README.md README.en.md
git commit -m "docs: add research harness operations runbook"
```

### Task 10: Release Candidate Verification

**Files:** no new files

- [ ] **Step 1: Run migrations from empty database**

```bash
DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  DEEPSEEK_API_KEY=test uv run alembic downgrade base
DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  DEEPSEEK_API_KEY=test uv run alembic upgrade head
uv run alembic check
```

Expected: all commands exit `0`.

- [ ] **Step 2: Run complete tests**

```bash
TEST_DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  DEEPSEEK_API_KEY=test uv run pytest -q
```

Expected: zero failures.

- [ ] **Step 3: Run offline quality evaluation**

```bash
DEEPSEEK_API_KEY=test uv run butler-evaluate-research \
  --cases tests/fixtures/research_eval_cases.json \
  --offline
```

Expected:

- unsupported material claim rate is `0`;
- citation validity is `1.0` for release fixtures;
- cost and latency fields are present.

- [ ] **Step 4: Audit requirements**

```bash
git diff --check
rg -n "TODO|TBD|FIXME" \
  src/research src/models docs/agent docs/operations \
  deployment.md deployment.en.md
cmp -s CLAUDE.md AGENTS.md
git status --short
```

Expected: no formatting errors or placeholders; root docs identical; only
intentional release changes are present.

- [ ] **Step 5: Request code review**

Invoke `superpowers:requesting-code-review`, address findings, rerun the full
release verification, then use `superpowers:finishing-a-development-branch`.
