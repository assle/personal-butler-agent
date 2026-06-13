# Research Harness Phase 4: Synthesis and Citation Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate evidence-grounded reports, bind every material claim to persisted evidence, independently validate citations, and prevent unsupported claims from reaching delivery.

**Architecture:** The Synthesizer receives normalized evidence and emits a typed draft containing claims plus evidence IDs. A separate Citation Reviewer evaluates support and returns structured findings; a bounded repair coordinator either requests targeted retrieval, weakens/removes claims, or marks the task failed.

**Tech Stack:** Pydantic v2, LangChain structured output, SQLAlchemy async, LangGraph, Taskiq, pytest

---

## File Map

**New models**

- `src/models/research_quality.py`: claims, claim-evidence bindings, and review findings.

**New quality components**

- `src/research/synthesis/__init__.py`
- `src/research/synthesis/prompts.py`
- `src/research/synthesis/schemas.py`
- `src/research/synthesis/service.py`
- `src/research/review/__init__.py`
- `src/research/review/prompts.py`
- `src/research/review/schemas.py`
- `src/research/review/service.py`
- `src/research/quality.py`: quality gate and bounded repair coordinator.

**Modified runtime**

- `src/models/research.py`: report version and validation metadata.
- `src/research/tasks.py`: synthesis, validation, and repair Taskiq entries.
- `src/research/queue.py`: quality-stage dispatch methods.
- `src/research/service.py`: report version persistence and terminal transition.
- `src/research/delivery.py`: require final validated report.
- Alembic revision.

**Tests**

- `tests/test_research_quality_models.py`
- `tests/test_research_synthesizer.py`
- `tests/test_research_citation_reviewer.py`
- `tests/test_research_quality_gate.py`
- `tests/test_research_quality_flow.py`
- `tests/test_research_delivery.py`

### Task 1: Add Claim and Review Models

**Files:**
- Create: `src/models/research_quality.py`
- Modify: `src/models/research.py`
- Modify: `src/models/__init__.py`
- Create: Alembic revision
- Test: `tests/test_research_quality_models.py`

- [ ] **Step 1: Write metadata tests**

```python
def test_quality_tables_are_registered():
    """验证结论、证据绑定和审查结果表已注册"""
    assert {
        "research_claims",
        "research_claim_evidence",
        "research_review_findings",
    } <= set(Base.metadata.tables)


def test_claim_evidence_binding_is_unique():
    """验证同一结论与证据不能重复绑定"""
    table = Base.metadata.tables["research_claim_evidence"]
    assert has_unique_constraint(
        table,
        ("workspace_id", "claim_id", "evidence_id"),
    )
```

- [ ] **Step 2: Run tests**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_quality_models.py -q
```

Expected: FAIL because the tables do not exist.

- [ ] **Step 3: Add quality models**

```python
class ResearchClaim(Base):
    """研究报告中的可验证结论"""

    __tablename__ = "research_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    report_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    claim_key: Mapped[str] = mapped_column(String(128), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # fact | inference | uncertainty | recommendation
    material: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    validation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending"
    )


class ResearchClaimEvidence(Base):
    """结论与证据支持关系"""

    __tablename__ = "research_claim_evidence"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "claim_id",
            "evidence_id",
            name="uq_research_claim_evidence",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    claim_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    evidence_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    support_level: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # supports | partial | contradicts
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
```

Add `ResearchReviewFinding` with `finding_type`, `severity`, `claim_id`,
`evidence_id`, `message`, and `resolved`.

Extend `ResearchReport` with:

```python
report_status: Mapped[str] = mapped_column(
    String(32), nullable=False, default="draft"
)
validated_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=True), nullable=True
)
```

- [ ] **Step 4: Apply migration and verify**

```bash
DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  DEEPSEEK_API_KEY=test uv run alembic revision --autogenerate \
  -m "add research claims and review findings"
DATABASE_URL='postgresql+asyncpg://butler:butler@127.0.0.1:5432/butler_test' \
  DEEPSEEK_API_KEY=test uv run alembic upgrade head
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_quality_models.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/models/research_quality.py src/models/research.py \
  src/models/__init__.py tests/test_research_quality_models.py \
  alembic/versions
git commit -m "feat: add claim evidence quality models"
```

### Task 2: Define Structured Synthesis Output

**Files:**
- Create: `src/research/synthesis/__init__.py`
- Create: `src/research/synthesis/schemas.py`
- Create: `src/research/synthesis/prompts.py`
- Test: `tests/test_research_synthesizer.py`

- [ ] **Step 1: Write schema tests**

```python
def test_report_draft_rejects_unknown_evidence_id():
    """验证草稿不能引用输入证据集之外的 ID"""
    draft = ReportDraft(
        title="Report",
        summary="Summary",
        sections=[],
        claims=[
            ClaimDraft(
                key="c1",
                text="Unsupported",
                claim_type="fact",
                material=True,
                evidence_ids=[999],
            )
        ],
    )
    with pytest.raises(SynthesisValidationError):
        validate_report_draft(draft, allowed_evidence_ids={1, 2})
```

- [ ] **Step 2: Define schemas**

```python
class ClaimDraft(BaseModel):
    """待持久化报告结论"""

    key: str
    text: str
    claim_type: Literal["fact", "inference", "uncertainty", "recommendation"]
    material: bool = True
    evidence_ids: list[int]


class ReportSectionDraft(BaseModel):
    """结构化报告章节"""

    heading: str
    body: str
    claim_keys: list[str]


class ReportDraft(BaseModel):
    """Synthesizer 结构化报告草稿"""

    title: str
    summary: str
    sections: list[ReportSectionDraft]
    claims: list[ClaimDraft]
    limitations: list[str] = Field(default_factory=list)
```

- [ ] **Step 3: Write synthesis prompt**

The prompt must include:

```text
Use only the supplied evidence records.
Every material factual claim must cite one or more evidence IDs.
Do not invent URLs, authors, dates, evidence IDs, or retrieval activity.
Label inference, uncertainty, and recommendation explicitly.
Conflicting evidence must be surfaced, not silently resolved.
Return only the ReportDraft schema.
```

- [ ] **Step 4: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_synthesizer.py -q
```

Expected: schema-focused tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/research/synthesis tests/test_research_synthesizer.py
git commit -m "feat: define evidence grounded report drafts"
```

### Task 3: Implement Synthesizer Persistence

**Files:**
- Create: `src/research/synthesis/service.py`
- Modify: `src/research/service.py`
- Test: `tests/test_research_synthesizer.py`

- [ ] **Step 1: Write service test**

```python
@pytest.mark.asyncio
async def test_synthesizer_persists_report_claims_and_bindings(db_session):
    """验证综合结果在同一事务中保存报告、结论与证据绑定"""
    service = ReportSynthesisService(
        llm=llm_returning(report_draft()),
        task_service=ResearchTaskService(...),
    )
    report = await service.synthesize(db_session, task.id)
    assert report.report_status == "draft"
    assert await count_claims(db_session, report.id) == 2
    assert await count_bindings(db_session, report.id) == 3
```

- [ ] **Step 2: Implement service**

```python
class ReportSynthesisService:
    """基于持久化证据生成并保存报告草稿"""

    async def synthesize(
        self,
        db: AsyncSession,
        task_id: str,
    ) -> ResearchReport:
        """生成结构化报告草稿

        参数:
            db: 异步数据库会话
            task_id: 研究任务 ID

        返回:
            ResearchReport: 已保存的草稿版本
        """
```

Implementation order:

1. transition `running -> synthesizing`;
2. load evidence in workspace scope;
3. call structured LLM output;
4. validate evidence IDs and claim keys;
5. render markdown citations from persisted evidence;
6. persist report, claims, and bindings atomically;
7. append `report.drafted`.

- [ ] **Step 3: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_synthesizer.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/research/synthesis/service.py src/research/service.py \
  tests/test_research_synthesizer.py
git commit -m "feat: synthesize claim linked research reports"
```

### Task 4: Define Citation Review Output

**Files:**
- Create: `src/research/review/__init__.py`
- Create: `src/research/review/schemas.py`
- Create: `src/research/review/prompts.py`
- Test: `tests/test_research_citation_reviewer.py`

- [ ] **Step 1: Write review schema tests**

```python
def test_review_decision_requires_finding_for_rejected_claim():
    """验证拒绝结论必须给出结构化原因"""
    with pytest.raises(ValueError):
        CitationReview(
            decision="repair",
            claim_reviews=[
                ClaimReview(
                    claim_key="c1",
                    status="unsupported",
                    findings=[],
                )
            ],
        )
```

- [ ] **Step 2: Define reviewer schemas**

```python
class ReviewFindingDraft(BaseModel):
    """引用审查发现"""

    finding_type: Literal[
        "source_missing",
        "unsupported",
        "partial_support",
        "citation_mismatch",
        "conflict",
        "missing_citation",
    ]
    severity: Literal["info", "warning", "error"]
    evidence_id: int | None = None
    message: str


class ClaimReview(BaseModel):
    """单条结论审查结果"""

    claim_key: str
    status: Literal["supported", "partial", "unsupported", "conflicted"]
    findings: list[ReviewFindingDraft]


class CitationReview(BaseModel):
    """报告引用审查结果"""

    decision: Literal["pass", "repair", "fail"]
    claim_reviews: list[ClaimReview]
    missing_material_claims: list[str] = Field(default_factory=list)
```

- [ ] **Step 3: Write independent reviewer prompt**

The Reviewer receives claims and only their bound evidence. It must not receive
the Synthesizer's hidden conversation. Prompt rules:

```text
Judge whether each evidence excerpt supports the exact claim.
Do not infer support from source prestige or title alone.
Mark unsupported extrapolation.
Identify conflicting evidence and missing citations.
Return only CitationReview.
```

- [ ] **Step 4: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_citation_reviewer.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/research/review tests/test_research_citation_reviewer.py
git commit -m "feat: define independent citation review"
```

### Task 5: Implement Reviewer and Quality Gate

**Files:**
- Create: `src/research/review/service.py`
- Create: `src/research/quality.py`
- Test: `tests/test_research_citation_reviewer.py`
- Test: `tests/test_research_quality_gate.py`

- [ ] **Step 1: Write pass/fail gate tests**

```python
@pytest.mark.asyncio
async def test_quality_gate_validates_supported_report(db_session):
    """验证所有重要结论受支持时报告进入 validated"""


@pytest.mark.asyncio
async def test_quality_gate_never_validates_unsupported_material_claim(db_session):
    """验证未支持的重要结论不能进入最终报告"""
```

- [ ] **Step 2: Implement reviewer persistence**

`CitationReviewService.review()`:

1. transitions `synthesizing -> validating`;
2. loads draft claims and bound evidence;
3. invokes structured Reviewer;
4. persists findings;
5. updates claim validation statuses;
6. returns `QualityDecision`.

```python
@dataclass(frozen=True)
class QualityDecision:
    """引用质量门判定"""

    outcome: Literal["pass", "repair", "fail"]
    unsupported_claim_keys: tuple[str, ...]
    follow_up_queries: tuple[str, ...]
```

- [ ] **Step 3: Implement deterministic gate**

The local gate overrides an LLM `pass` when:

- any material claim has zero evidence bindings;
- any bound evidence row is missing;
- any material claim status is `unsupported`;
- any error-severity finding is unresolved.

- [ ] **Step 4: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_citation_reviewer.py \
  tests/test_research_quality_gate.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/research/review/service.py src/research/quality.py \
  tests/test_research_citation_reviewer.py \
  tests/test_research_quality_gate.py
git commit -m "feat: enforce citation quality gate"
```

### Task 6: Add Bounded Repair Loop

**Files:**
- Modify: `src/research/quality.py`
- Modify: `src/research/planning/service.py`
- Modify: `src/research/budgets.py`
- Test: `tests/test_research_quality_flow.py`

- [ ] **Step 1: Write repair tests**

```python
@pytest.mark.asyncio
async def test_repair_adds_targeted_steps_once():
    """验证引用失败只追加受限的补充检索"""


@pytest.mark.asyncio
async def test_second_failed_review_removes_or_fails_claims():
    """验证超过修复轮数后不无限检索"""
```

- [ ] **Step 2: Implement repair decision**

```python
class QualityRepairCoordinator:
    """协调引用失败后的有限修复"""

    async def handle(
        self,
        db: AsyncSession,
        task_id: str,
        decision: QualityDecision,
    ) -> QualityRepairResult:
        """处理质量门失败

        参数:
            db: 异步数据库会话
            task_id: 研究任务 ID
            decision: 审查判定

        返回:
            QualityRepairResult: 新增步骤、修订或终止结果
        """
```

Rules:

- if repair rounds remain and budget is available, append only targeted
  retrieval steps from reviewer queries;
- otherwise mark unsupported claims excluded and resynthesize;
- fail only when no usable material claims remain;
- never exceed `research_max_repair_rounds`.

- [ ] **Step 3: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_quality_flow.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/research/quality.py src/research/planning/service.py \
  src/research/budgets.py tests/test_research_quality_flow.py
git commit -m "feat: repair unsupported research claims"
```

### Task 7: Add Quality-Stage Queue Tasks

**Files:**
- Modify: `src/research/queue.py`
- Modify: `src/research/tasks.py`
- Test: `tests/test_research_tasks.py`
- Test: `tests/test_research_quality_flow.py`

- [ ] **Step 1: Extend dispatcher**

```python
async def enqueue_synthesis(self, task_id: str) -> None:
    """派发报告综合任务"""

async def enqueue_validation(self, task_id: str) -> None:
    """派发引用验证任务"""
```

- [ ] **Step 2: Register tasks**

```python
@broker.task(task_name="research.synthesize")
async def synthesize_research_task(task_id: str) -> None:
    """Taskiq 报告综合入口"""


@broker.task(task_name="research.validate")
async def validate_research_task(task_id: str) -> None:
    """Taskiq 引用验证入口"""
```

The final retrieval step enqueues synthesis. Synthesis enqueues validation.
Validation either enqueues repair steps, resynthesis, or delivery.

- [ ] **Step 3: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_tasks.py tests/test_research_quality_flow.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/research/queue.py src/research/tasks.py \
  tests/test_research_tasks.py tests/test_research_quality_flow.py
git commit -m "feat: queue synthesis and citation validation"
```

### Task 8: Block Delivery Until Validation Passes

**Files:**
- Modify: `src/research/delivery.py`
- Modify: `src/research/service.py`
- Test: `tests/test_research_delivery.py`

- [ ] **Step 1: Write delivery gate test**

```python
@pytest.mark.asyncio
async def test_delivery_rejects_draft_or_unvalidated_report(db_session):
    """验证未通过引用质量门的报告不能投递"""
    with pytest.raises(ReportNotValidatedError):
        await delivery.deliver(db_session, draft_report.task_id)
    app_client.send_text.assert_not_awaited()
```

- [ ] **Step 2: Require validated report snapshot**

Change report lookup to:

```python
select(ResearchReport).where(
    ResearchReport.task_id == task_id,
    ResearchReport.report_status == "validated",
).order_by(ResearchReport.version.desc())
```

Before sending, emit `BeforeDelivery`; after success transition
`completed -> delivering -> delivered`.

- [ ] **Step 3: Verify**

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_research_delivery.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/research/delivery.py src/research/service.py \
  tests/test_research_delivery.py
git commit -m "feat: deliver only validated research reports"
```

### Task 9: Phase 4 Documentation and Verification

**Files:**
- Modify: `docs/agent/active-context.md`
- Modify: `docs/agent/patterns.md`
- Modify: `docs/agent/decisions.md`
- Modify: `docs/agent/upgrade-roadmap.md`

- [ ] **Step 1: Document quality statuses**

Document:

```text
draft -> validating -> validated
validation failure -> repair retrieval or resynthesis
unsupported material claims -> excluded or task failure
```

- [ ] **Step 2: Run Phase 4 gate**

```bash
DEEPSEEK_API_KEY=test uv run pytest \
  tests/test_research_synthesizer.py \
  tests/test_research_citation_reviewer.py \
  tests/test_research_quality_gate.py \
  tests/test_research_quality_flow.py \
  tests/test_research_delivery.py -q
DEEPSEEK_API_KEY=test uv run pytest -q
uv run alembic check
```

Expected: all commands exit `0`.

- [ ] **Step 3: Commit**

```bash
git add docs/agent
git commit -m "docs: document claim level citation validation"
```
