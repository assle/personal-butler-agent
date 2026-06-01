# Upgrade Roadmap

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

## 二、会话记忆持久化

### 2.1 MemorySaver → SqliteSaver

- **当前**: 使用 LangGraph 的 `MemorySaver`（进程内内存），重启即丢失对话历史
- **目标**: 升级为 `SqliteSaver`，将 checkpoint 持久化到 SQLite，跨重启保留多轮对话上下文
- **收益**: 用户对话历史持久化，断电/重启不影响体验
- **工作量**: 中（替换 `src/graph/memory.py` 中的 saver 实现，迁移 checkpoint 表结构）
- **参考**: `docs/agent/decisions.md` ADR-007

---

## 三、定时调度

### 3.1 APScheduler 定时推送

- **当前**: 群机器人 webhook 推送客户端已实现（`src/wechat/webhook.py`），且通过单元测试验证。但缺少定时调度和 agent 集成——`_webhook_client` 在 `main.py` 启动时创建但未被任何模块实际调用，主动推送功能尚未启用
- **目标**: 接入 APScheduler（已在 `pyproject.toml` 依赖中），实现每日定时推送训练计划、每周饮食报告等
- **收益**: 自动化群组通知，无需手动触发
- **工作量**: 中（新增 scheduler 模块，定义 job 函数，在 lifespan 中启动）
- **依赖**: 2.1（推送内容可能需要从持久化记忆中获取上下文）

### 3.2 定时提醒和摘要

- **当前**: 无
- **目标**: APScheduler 驱动的个人提醒（喝水、训练）和日报/周报摘要
- **工作量**: 中

---

## 四、企业微信能力增强

### 4.1 异步客服消息回复

- **当前**: 智能机器人回调已通过 `response_url` 实现主动回复（`src/wechat/robot_router.py`），不受 5 秒限制。自建应用回调（`src/wechat/router.py`）仍使用同步被动 XML 回复，LLM 调用可能超时
- **目标**: 自建应用回调也升级为异步回复，通过企业微信"客服消息"API 或 webhook 推送
- **收益**: 解决自建应用场景下 LLM 延迟导致的超时问题
- **工作量**: 中（新增客服消息 API 客户端，改造自建应用 router 回复逻辑）
- **备注**: 智能机器人回调已是主动回复模式，可作为参考实现

### 4.2 多消息类型支持

- **当前**: 仅支持文本消息（image/voice 等回复"暂不支持"）
- **目标**: 支持图片消息（OCR 识别训练记录）、语音消息（转文字后路由）
- **工作量**: 大（需要接入 OCR/ASR 服务）

### 4.3 企业微信 OAuth 用户身份映射

- **当前**: 使用 `FromUserName`（OpenID）作为 `user_id`
- **目标**: 通过企业微信 OAuth 获取用户真实信息，建立 OpenID ↔ 用户档案映射
- **收益**: 用户身份识别更准确，支持跨会话用户数据关联
- **工作量**: 中

---

## 五、知识库与 RAG

### 5.1 知识库集成

- **当前**: QA agent 完全依赖 LLM 内置知识
- **目标**: 接入向量数据库（如 Chroma/PGVector），存储健身知识、饮食数据库、历史对话摘要，增强回答质量
- **收益**: 回答更专业、更个性化，减少 LLM 幻觉
- **工作量**: 大（需要选择向量数据库、设计 embedding pipeline、改造 QA agent）

---

## 六、工程基础设施

### 6.1 依赖管理规范化

- **当前**: `pytest` 等开发依赖在 `[project.optional-dependencies]` 中，`uv sync` 不会自动安装，每次需手动 `uv pip install`
- **目标**: 迁移到 `[dependency-groups]` 或使用 `uv sync --dev` 支持的格式
- **工作量**: 小（修改 `pyproject.toml`）

### 6.2 容器化部署

- **当前**: 本地 `uv run uvicorn` 启动，无容器化
- **目标**: 编写 Dockerfile，支持 `docker compose up` 一键启动
- **收益**: 部署一致性，方便在企业微信回调要求的公网环境部署
- **工作量**: 小（单文件 Dockerfile + compose.yml）

### 6.3 CI/CD

- **当前**: 无持续集成
- **目标**: GitHub Actions 自动化测试 + lint，PR 时自动运行
- **工作量**: 小（单文件 `.github/workflows/test.yml`）

### 6.4 端到端测试

- **当前**: 所有测试 mock 了 LLM 和数据库
- **目标**: 增加有限数量的端到端测试（真实 SQLite + 真实 DeepSeek 调用），在 CI 中手动触发
- **工作量**: 中

---

## 七、多用户与群聊

### 7.1 多用户群聊消息收集

- **当前**: 已实现 — 群聊消息被动收集到 `GroupMessage` 表，触发词检测后调用 LLM 生成摘要。支持自建应用和智能机器人两种回调渠道
- **目标**: 增强多群支持、跨群用户身份映射、按用户/时间段聚合摘要
- **工作量**: 中

---

## 状态说明

| 标记 | 含义 |
|------|------|
| 小 | 预计 1 小时以内 |
| 中 | 预计 1-3 小时 |
| 大 | 预计半天以上 |

最后更新: 2026-06-01（区分机器人回调与主动推送 webhook 当前状态，修正 webhook 推送能力描述，明确 APScheduler 集成尚未开始）
