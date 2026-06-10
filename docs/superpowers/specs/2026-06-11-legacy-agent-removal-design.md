# Legacy Agent Removal Design

## Goal

在不修改现有 SQLite 数据文件的前提下，删除已经确认不会恢复的 Fitness、Meal、QA 独立 Agent 及其专用基础设施，使仓库只保留当前 scene-agent 运行架构。

## Scope

本次删除：

- `src/agents/fitness/`、`src/agents/meal/`、`src/agents/qa/`。
- 未被当前运行链路使用的 `src/agents/base.py` 和 `src/agents/registry.py`。
- 只服务于上述 Agent 的 `TrainingRecord`、`UserPreference` ORM 模型及其模型注册。
- 上述 Agent 和模型的专用测试。
- 知识库中不再有消费者的 `fitness`、`meal` domain。
- README 和 `docs/agent/` 中关于遗留 Agent、训练记录表和用户偏好表仍属于当前实现的陈述。

本次保留：

- 知识库 `qa` domain。当前 `PrivateButlerAgent.search_local_knowledge` 仍使用 `global + qa` 作为私聊知识检索范围。
- 群聊中对训练和饮食请求的拒绝规则。它们是当前产品边界，不依赖遗留 Agent。
- 历史 `docs/superpowers/` 设计和计划，作为项目演进记录。
- `i18n/` 历史快照。
- 未跟踪的 `txt`、`学习.ipynb` 和 `i18n/README.md`。

## Data Safety

删除 ORM 模型和 `Base.metadata` 注册不会删除已有 SQLite 表。本次不得：

- 执行 `DROP TABLE training_records` 或 `DROP TABLE user_preferences`。
- 删除、重建或修改现有 `butler.db`。
- 运行会对生产或本地持久化数据库调用 `drop_all()` 的命令。

旧数据库中的 `training_records` 和 `user_preferences` 表暂时保留为未映射历史数据。后续引入 Alembic 时，再通过显式迁移决定保留、导出或删除这些表。

## Knowledge Domains

`VALID_DOMAINS` 和知识导入 CLI 调整为：

```text
global
qa
summary
```

现有数据库中已经保存的 `fitness` 或 `meal` 知识文档不在本次物理删除。它们将无法通过新 CLI 导入，也不会被当前运行 Agent 检索；后续索引迁移时统一处理历史数据。

## Documentation

- README 项目树删除遗留 Agent 目录。
- `active-context.md` 删除遗留 Agent 和旧表的当前状态描述。
- `patterns.md` 删除 fitness/meal 专用偏好模式。
- `upgrade-roadmap.md` 的周期报告改为复用当前运行中的 `SummaryAgent` 和 `WebhookComposerAgent`。
- `decisions.md` 保留 ADR-002、ADR-004 和 ADR-010，但标记为已退役，解释旧数据库中历史表的来源。
- `troubleshooting.md` 不再把训练记录表列为当前必需表。

## Verification

- 删除后的完整测试必须通过。
- `uv run python -m compileall -q src scripts` 必须成功。
- `uv build` 必须成功。
- `git diff --check` 必须无格式错误。
- 当前源码、测试、README 和 `docs/agent/` 中不得再引用已删除的类、包或 ORM 模型。
- `AGENTS.md` 与 `CLAUDE.md` 必须保持字节一致。
