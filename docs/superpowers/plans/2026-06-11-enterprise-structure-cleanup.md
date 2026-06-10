# Enterprise Structure Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收口当前 scene-agent 项目的代码、测试、目录、脚本和文档结构，并恢复绿色验证基线。

**Architecture:** 保持现有业务接口和 `src.*` 导入路径不变；删除无效 wiring，复用群聊预分类结果，把 scheduler 大文件按职责拆分，并通过公共导出维持兼容。

**Tech Stack:** Python 3.13、FastAPI、LangGraph、SQLAlchemy async、APScheduler、uv、pytest

---

### Task 1: Restore The Current Test Contract

**Files:**
- Modify: `tests/test_butler_tools.py`
- Modify: `src/main.py`
- Modify: `src/agents/private_butler/graph.py`
- Modify: `src/agents/private_butler/tools.py`

- [x] 删除仍要求 fitness/meal 私聊工具的测试参数，增加工具集合精确断言。
- [x] 运行 `uv run pytest tests/test_butler_tools.py -q`，确认当前失败来自旧预期。
- [x] 移除 QAAgent 未使用实例和 PrivateButlerToolContext 旧兼容参数。
- [x] 重新运行相关测试并确认通过。

### Task 2: Reuse Group Preclassification

**Files:**
- Modify: `src/messaging/dispatch.py`
- Modify: `src/agents/group_mention/state.py`
- Modify: `src/agents/group_mention/nodes.py`
- Modify: `src/agents/group_mention/graph.py`
- Modify: `tests/test_messaging.py`
- Modify: `tests/test_group_mention_agent.py`

- [x] 添加失败测试，证明 dispatch 应传递 `group_category`。
- [x] 添加失败测试，证明 GroupMentionAgent 有预分类时不再次调用分类器。
- [x] 实现状态字段和分类节点短路逻辑。
- [x] 运行两组相关测试并确认通过。

### Task 3: Split Scheduler Responsibilities

**Files:**
- Create: `src/scheduler/models.py`
- Create: `src/scheduler/config.py`
- Create: `src/scheduler/client.py`
- Create: `src/scheduler/manager.py`
- Modify: `src/scheduler/__init__.py`
- Modify: `tests/test_scheduler.py`

- [x] 记录现有 scheduler 测试基线。
- [x] 按职责移动代码，不改变类名、函数名或公共导入路径。
- [x] 明确 `weather_query` 仅支持 `raw` mode，避免 compose 配置静默退化为 raw。
- [x] 更新测试 monkeypatch 路径，使其指向实际定义模块。
- [x] 运行 `uv run pytest tests/test_scheduler.py -q`。

### Task 4: Clean Repository And Packaging Metadata

**Files:**
- Modify: `.gitignore`
- Delete: tracked `.idea/` files
- Modify: `pyproject.toml`
- Create: `src/cli/__init__.py`
- Create: `src/cli/ingest_knowledge.py`
- Modify: `scripts/ingest_knowledge.py`

- [x] 忽略 IDE 元数据和 Jupyter checkpoint。
- [x] 停止跟踪 `.idea/` 中已提交的项目/部署文件，保留本地忽略的 workspace 配置。
- [x] 删除重复的 `websockets` 和显式 `python-dotenv` 声明，将 `ipykernel` 移入开发依赖。
- [x] 注册 `butler-ingest-knowledge` CLI，并让旧脚本调用同一实现。
- [x] 验证 CLI `--help` 和 wheel 构建。

### Task 5: Synchronize Current Documentation

**Files:**
- Modify: `README.md`
- Modify: `README.en.md`
- Modify: `docs/agent/active-context.md`
- Modify: `docs/agent/patterns.md`
- Modify: `docs/agent/decisions.md`
- Modify: `docs/agent/upgrade-roadmap.md`
- Modify: `docs/agent/troubleshooting.md`

- [x] 修正当前运行 agent、工具列表、天气命名和业务流程。
- [x] 记录 scheduler 模块边界和群聊预分类传递模式。
- [x] 标记 `i18n/` 为历史快照，不作为当前运行事实来源。
- [x] 保留 `AGENTS.md` 和 `CLAUDE.md` 不变并验证完全一致。

### Task 6: Full Verification

**Files:**
- Verify only

- [x] 运行 `uv run pytest -q`。
- [x] 运行 `uv run python -m compileall -q src scripts`。
- [x] 运行 `uv build --out-dir /tmp/personal-butler-review-dist`。
- [x] 运行 `git diff --check`。
- [x] 运行 `cmp -s AGENTS.md CLAUDE.md`。
- [x] 检查 `git status --short`，确认未覆盖用户原有未提交功能改动。
