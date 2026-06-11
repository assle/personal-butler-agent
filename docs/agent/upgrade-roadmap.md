# Upgrade Roadmap

> Prioritized upgrade items and future work. Load when planning future work or evaluating technical debt.

记录当前项目可升级的点，按优先级排列。每个条目包含当前状态、目标状态和预估工作量。

---

## 一、Agent 执行模式

### 1.1 Inline → Subagent-Driven 执行

- **当前**: 使用 `superpowers:executing-plans` 在当前会话中顺序执行所有任务
- **目标**: 使用 `superpowers:subagent-driven-development`，每个任务分派给独立子代理并行执行
- **收益**: 独立任务可并行，减少总耗时；每个子代理上下文更干净
- **工作量**: 小（仅改变执行技能选择，无需改代码）

### 1.2 测试驱动开发规范化

- **当前**: 实现时手动遵循 TDD（先写测试再写实现），但未强制
- **目标**: 每次实现前先调用 `superpowers:test-driven-development` 技能，确保红-绿-重构循环
- **收益**: 更严格的测试覆盖，减少回滚
- **工作量**: 小（流程改进）

---

## 二、定时调度

### 2.1 APScheduler 定时推送

- **当前**: 已支持企业微信群 webhook 主动推送，`SCHEDULER_TARGETS_FILE` 中每个群可配置独立 cron。
- **目标**: 继续完善 webhook 推送的失败观测、重试和群级配置管理。
- **收益**: 自动化群组通知，无需手动触发

### 2.2 定时提醒和摘要

- **当前**: 已支持私聊创建群 webhook 提醒；提醒默认 @ 私聊回调 `from.userid`，可通过 target 级 `mention_user_overrides` 覆盖；Scheduler 每分钟扫描到期任务并推送到配置群；私聊确认展示 target `display_name` 和本地时区时间。
- **下一步**: 增加群聊日报/周报等周期报告型提醒，复用现有 `SummaryAgent` 和 `WebhookComposerAgent` 生成正文。
- **剩余工作量**: 中

---

## 三、企业微信能力增强

### 3.1 多消息类型支持

- **当前**: 文本 + 语音消息已支持。语音消息使用企业微信内置语音识别结果（JSON `voice.content`），提取后走正常意图路由和 agent 管线，空识别静默忽略。图片、文件等其他类型仍回复"暂不支持"
- **目标**: 支持图片文字识别，并将识别结果交给当前私聊问答流程处理
- **工作量**: 中（需接入 OCR 服务，无需自建 ASR）

### 3.2 企业微信 OAuth 用户身份映射

- **当前**: 使用 `FromUserName`（OpenID）作为 `user_id`
- **目标**: 通过企业微信 OAuth 获取用户真实信息，建立 OpenID ↔ 用户档案映射
- **收益**: 用户身份识别更准确，支持跨会话用户数据关联
- **工作量**: 中

---

## 四、知识库与 RAG

### 4.1 知识库集成

- **当前**: Stage 2 QA-first 已支持 SQLite 知识库、public/user/group scope 隔离、PrivateButler 知识工具注入、本地 `.md`/`.txt` 导入脚本，以及关键词 + SQLite FTS + 向量嵌入的混合检索。向量嵌入已升级为 DashScope Qwen3-Embedding API（1024 维语义向量），本地哈希 embedding 作为 fallback。
- **下一步**: PDF/网页导入、文件上传 UI、持久化索引重建操作、可选外部向量库，并按需扩展到摘要或 webhook 内容生成。
- **收益**: 回答更专业、更个性化，减少 LLM 幻觉，同时保留多用户/多群聊知识隔离。
- **剩余工作量**: 中到大（主要取决于向量数据库、文件管理和后台索引重建需求）。

---

## 五、工程基础设施

### 5.1 依赖管理规范化

- **当前**: 运行依赖已移除重复的 `python-dotenv`/`websockets` 声明，`ipykernel` 已移入 `dev` extra；pytest 仍位于 `[project.optional-dependencies].dev`
- **目标**: 如 CI 或团队开发需要，迁移到 `[dependency-groups]` 并统一使用 `uv sync --group dev`
- **工作量**: 小（修改 `pyproject.toml`）

### 5.2 容器化部署

- **当前**: 本地 `uv run uvicorn` 启动，无容器化
- **目标**: 编写 Dockerfile，支持 `docker compose up` 一键启动
- **收益**: 部署一致性，方便在企业微信回调要求的公网环境部署
- **工作量**: 小（单文件 Dockerfile + compose.yml）

### 5.3 CI/CD

- **当前**: 无持续集成
- **目标**: GitHub Actions 自动化测试 + lint，PR 时自动运行
- **工作量**: 小（单文件 `.github/workflows/test.yml`）

### 5.4 端到端测试

- **当前**: 所有测试 mock 了 LLM 和数据库
- **目标**: 增加有限数量的端到端测试（真实 SQLite + 真实 DeepSeek 调用），在 CI 中手动触发
- **工作量**: 中

---

## 六、多用户与群聊

### 6.1 多用户群聊消息收集

- **当前**: 已实现 — 群聊消息通过智能机器人 URL 回调接收并被动收集到 `GroupMessage` 表；策略层分类后将结果传给 `GroupMentionAgent`
- **目标**: 增强多群支持、跨群用户身份映射、按用户/时间段聚合摘要
- **工作量**: 中

---

## 状态说明

| 标记 | 含义 |
|------|------|
| 小 | 预计 1 小时以内 |
| 中 | 预计 1-3 小时 |
| 大 | 预计半天以上 |

最后更新: 2026-06-11（新增群投票、翻译、个性化记忆、Qwen3 语义嵌入；升级 embedding 为 API 模式 + 本地 fallback）
