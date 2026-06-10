# Enterprise Structure Cleanup Design

## Goal

在不改变当前企业微信回调、私聊、群聊和定时推送产品行为的前提下，完成一次可验证的仓库结构收口，使代码、测试、文档和构建配置描述同一套 scene-agent 架构。

## Scope

本阶段包含：

- 修复已移除 fitness/meal 私聊工具导致的失败测试。
- 移除当前运行链路中未使用的 QAAgent wiring 和旧兼容参数。
- 让群聊策略层生成的分类结果直接传给 GroupMentionAgent，避免重复分类。
- 把 `src/scheduler/__init__.py` 拆成配置模型、配置加载、HTTP 客户端和调度管理模块。
- 保留 `from src.scheduler import ...` 公共导入方式，避免调用方迁移。
- 将知识库导入脚本注册为安装后的 CLI 命令。
- 清理已提交的 IDE 部署元数据并补充 `.gitignore`。
- 移除已确认不再使用的运行时依赖。
- 更新 README 和 `docs/agent/`，使其与当前实现一致。

本阶段不包含：

- 不把顶级 Python 包从 `src` 迁移为 `personal_butler_agent`。这是破坏性导入路径迁移，应单独执行。
- 不引入 Alembic。当前 schema 迁移策略需要单独设计初始基线和已有 SQLite 数据处理。
- 不引入 Celery、Redis 或外部任务队列。当前单进程 MVP 的可靠任务迁移需要独立部署方案。
- 不删除 `fitness/`、`meal/`、`qa/` 源包及其领域测试；它们保留为未接入运行时的领域实现。
- 不删除未跟踪的个人文件 `txt` 和 `学习.ipynb`。
- 不修改 `i18n/` 历史镜像文档；本阶段将其明确标记为历史快照，避免继续被视为当前事实来源。

## Architecture

### Runtime Wiring

`src/main.py` 只创建实际运行所需的 scene agent、SummaryAgent、ReminderAgent 和服务对象。未接入当前消息链路的 QA/Fitness/Meal agent 不在应用启动时实例化。

### Group Message Flow

`apply_group_policy()` 继续负责持久化和确定性触发判断。它返回的 `category` 通过 `extra_state` 传给 `GroupMentionAgent`。Agent 分类节点优先使用该值，仅在直接调用 agent 且缺少预分类时执行自身分类。

### Scheduler Package

```text
src/scheduler/
├── __init__.py
├── models.py
├── config.py
├── client.py
└── manager.py
```

`__init__.py` 只重新导出既有公共 API。模块依赖保持单向：models -> config/client -> manager。

### CLI

知识库导入逻辑保留在 `scripts/ingest_knowledge.py` 的现有入口，同时在包内增加可安装入口模块，并通过 `[project.scripts]` 暴露 `butler-ingest-knowledge`。

## Verification

- 相关测试先验证旧预期失败，再更新为当前产品边界。
- `uv run pytest -q` 必须全绿。
- `uv run python -m compileall -q src scripts` 必须成功。
- `uv build` 必须成功，wheel 中应包含 CLI 模块。
- `git diff --check` 必须无格式错误。
- `AGENTS.md` 与 `CLAUDE.md` 必须保持字节一致。
