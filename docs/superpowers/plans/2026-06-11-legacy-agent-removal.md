# Legacy Agent Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 非破坏性删除不会恢复的 Fitness、Meal、QA 独立 Agent 及其专用模型和基础设施，同时保留现有 SQLite 文件中的历史数据。

**Architecture:** 当前 scene-agent 运行链路保持不变。删除未被运行时导入的代码和 ORM metadata 注册，知识库 domain 收敛为 `global/qa/summary`；不执行数据库迁移或任何 `DROP TABLE`。

**Tech Stack:** Python 3.13、FastAPI、LangGraph、SQLAlchemy 2 async、SQLite、uv、pytest

---

### Task 1: Remove Legacy Agent Packages

**Files:**
- Delete: `src/agents/fitness/`
- Delete: `src/agents/meal/`
- Delete: `src/agents/qa/`
- Delete: `src/agents/base.py`
- Delete: `src/agents/registry.py`
- Delete: `tests/test_fitness.py`
- Delete: `tests/test_meal.py`
- Delete: `tests/test_qa.py`
- Modify: `src/agents/summary/graph.py`

- [ ] **Step 1: Record the focused legacy test baseline**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_fitness.py tests/test_meal.py tests/test_qa.py -q
```

Expected: all legacy-agent tests pass before deletion.

- [ ] **Step 2: Delete the legacy packages and dedicated tests**

Delete the listed agent directories, shared registry/base modules, and their dedicated test files. Do not modify `src/main.py`; it already imports only current runtime agents.

- [ ] **Step 3: Remove the stale registry description from SummaryAgent**

Replace the `AgentRegistry.get(...)` workflow text in `src/agents/summary/graph.py` with:

```text
场景 Agent 或工具调用 SummaryAgent.handle()
→ handle() 构建初始状态 → _graph.ainvoke() → AgentResponse
```

- [ ] **Step 4: Verify no executable code imports deleted modules**

Run:

```bash
rg -n "FitnessAgent|MealAgent|QAAgent|AgentRegistry|BaseGraphAgent|src\.agents\.(fitness|meal|qa|registry|base)" src tests
```

Expected: no matches.

### Task 2: Remove Legacy ORM Metadata And Knowledge Domains

**Files:**
- Delete: `src/models/training.py`
- Delete: `src/models/preference.py`
- Modify: `src/models/__init__.py`
- Modify: `src/knowledge/schemas.py`
- Modify: `src/cli/ingest_knowledge.py`
- Modify: `tests/test_db.py`
- Modify: `tests/test_knowledge_model.py`
- Modify: `tests/test_knowledge_service.py`

- [ ] **Step 1: Remove legacy model registration**

Delete the two model files and remove these imports and exports from `src/models/__init__.py`:

```python
from src.models.training import TrainingRecord
from src.models.preference import UserPreference
```

```python
"TrainingRecord",
"UserPreference",
```

- [ ] **Step 2: Assert current metadata excludes retired tables**

Update `test_base_metadata_has_tables()` to verify current tables remain registered and retired tables are absent:

```python
table_names = set(Base.metadata.tables)
assert {"group_messages", "knowledge_documents", "inbound_messages", "reminders"} <= table_names
assert "training_records" not in table_names
assert "user_preferences" not in table_names
```

This checks Python metadata only and does not inspect or modify `butler.db`.

- [ ] **Step 3: Restrict supported knowledge domains**

Set:

```python
VALID_DOMAINS = {"global", "qa", "summary"}
```

Set the CLI choices to:

```python
choices=["global", "qa", "summary"]
```

- [ ] **Step 4: Keep generic knowledge tests domain-valid**

In `tests/test_knowledge_model.py`, replace fitness-specific sample titles, sources, content, and `domain="fitness"` with summary-oriented examples using `domain="summary"`.

In `tests/test_knowledge_service.py`, keep the domain isolation test but ingest a `summary` document and search only `qa`:

```python
domain="summary"
```

Expected: the QA-domain search returns no results.

- [ ] **Step 5: Run focused database and knowledge tests**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_db.py tests/test_knowledge_model.py tests/test_knowledge_service.py tests/test_butler_tools.py -q
```

Expected: all selected tests pass.

### Task 3: Synchronize Current Documentation

**Files:**
- Modify: `README.md`
- Modify: `README.en.md`
- Modify: `docs/agent/active-context.md`
- Modify: `docs/agent/patterns.md`
- Modify: `docs/agent/decisions.md`
- Modify: `docs/agent/troubleshooting.md`
- Modify: `docs/agent/upgrade-roadmap.md`

- [ ] **Step 1: Remove legacy packages from README trees**

The current agent tree must list only:

```text
private_butler/
group_mention/
webhook_composer/
summary/
reminder/
```

Keep user-facing statements that training and meal requests are unavailable or rejected; those statements describe current product behavior.

- [ ] **Step 2: Update active context**

Remove `training_records` and `user_preferences` from current persistence. Remove deferred-work statements that legacy Agent packages remain. Describe Stage 2 RAG as private-butler knowledge-tool injection rather than QAAgent injection.

- [ ] **Step 3: Retire historical ADRs without erasing history**

Add a status note to ADR-002, ADR-004, and ADR-010:

```text
Status: Retired from the current runtime on 2026-06-11.
```

Explain that their ORM mappings were removed, while old SQLite files may retain unmapped historical tables until a future Alembic migration.

Update ADR-007 examples so they refer only to current scene/domain agents.

- [ ] **Step 4: Remove obsolete patterns and roadmap dependencies**

Remove fitness/meal-specific preference guidance. Change periodic report planning to reuse `SummaryAgent` and `WebhookComposerAgent`; remove OCR training-record wording because that capability is no longer planned.

- [ ] **Step 5: Update troubleshooting**

Remove `training_records` from the current required-table example and remove the training-extraction JSON failure case. Keep group rejection troubleshooting because it remains current behavior.

- [ ] **Step 6: Scan current documentation**

Run:

```bash
rg -n "FitnessAgent|MealAgent|QAAgent|AgentRegistry|BaseGraphAgent|training_records|user_preferences|src/agents/(fitness|meal|qa)" README.md README.en.md docs/agent
```

Expected: only explicitly retired historical ADR notes may mention old table or class names.

### Task 4: Full Verification And Commit

**Files:**
- Verify all changed files

- [ ] **Step 1: Run the complete test suite**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest -q
```

Expected: all remaining tests pass.

- [ ] **Step 2: Compile and build**

Run:

```bash
DEEPSEEK_API_KEY=test uv run python -m compileall -q src scripts
rm -rf /tmp/personal-butler-legacy-removal-dist
uv build --out-dir /tmp/personal-butler-legacy-removal-dist
```

Expected: compile and wheel/sdist build exit successfully.

- [ ] **Step 3: Verify repository invariants**

Run:

```bash
git diff --check
cmp -s AGENTS.md CLAUDE.md
rg -n "FitnessAgent|MealAgent|QAAgent|AgentRegistry|BaseGraphAgent|src\.agents\.(fitness|meal|qa|registry|base)|src\.models\.(training|preference)" src tests README.md README.en.md docs/agent
```

Expected: formatting and root-doc checks pass; residual matches exist only in retired ADR history where intentionally documented.

- [ ] **Step 4: Confirm data safety**

Run:

```bash
git diff --name-only | rg '(^|/)(butler\.db|.*\.db(-shm|-wal)?)$'
```

Expected: no output. No SQLite data file is changed or staged.

- [ ] **Step 5: Commit the deletion**

```bash
git add -u
git add README.md README.en.md docs/agent src tests
git commit -m "refactor: remove retired domain agents"
```
