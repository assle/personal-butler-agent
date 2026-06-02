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

- **当前**: 群机器人 webhook 推送客户端已实现（`src/wechat/webhook.py`），且通过单元测试验证。但缺少定时调度和 agent 集成——`_webhook_client` 在 `main.py` 启动时创建但未被任何模块实际调用，主动推送功能尚未启用
- **目标**: 接入 APScheduler（已在 `pyproject.toml` 依赖中），实现每日定时推送训练计划、每周饮食报告等
- **收益**: 自动化群组通知，无需手动触发
- **工作量**: 中（新增 scheduler 模块，定义 job 函数，在 lifespan 中启动）

### 2.2 定时提醒和摘要

- **当前**: 无
- **目标**: APScheduler 驱动的个人提醒（喝水、训练）和日报/周报摘要
- **工作量**: 中

---

## 三、企业微信能力增强

### 3.1 异步客服消息回复

- **当前**: 智能机器人回调已通过 `response_url` 实现主动回复（`src/wechat/robot_router.py`），不受 5 秒限制。自建应用回调（`src/wechat/router.py`）仍使用同步被动 XML 回复，LLM 调用可能超时
- **目标**: 自建应用回调也升级为异步回复，通过企业微信"客服消息"API 或 webhook 推送
- **收益**: 解决自建应用场景下 LLM 延迟导致的超时问题
- **工作量**: 中（新增客服消息 API 客户端，改造自建应用 router 回复逻辑）
- **备注**: 智能机器人回调已是主动回复模式，可作为参考实现

### 3.2 多消息类型支持

- **当前**: 文本 + 语音消息已支持。语音消息使用企业微信内置语音识别结果（XML `<Recognition>` / JSON `voice.content`），提取后走正常意图路由和 agent 管线，空识别静默忽略。自建应用和智能机器人两个回调渠道均已覆盖。图片、文件等其他类型仍回复"暂不支持"
- **目标**: 支持图片消息（OCR 识别训练记录）
- **工作量**: 中（语音已实现；剩余图片 OCR 需接入 OCR 服务，无需自建 ASR）

### 3.3 企业微信 OAuth 用户身份映射

- **当前**: 使用 `FromUserName`（OpenID）作为 `user_id`
- **目标**: 通过企业微信 OAuth 获取用户真实信息，建立 OpenID ↔ 用户档案映射
- **收益**: 用户身份识别更准确，支持跨会话用户数据关联
- **工作量**: 中

---

## 四、知识库与 RAG

### 4.1 知识库集成

- **当前**: Stage 1 已支持 SQLite 知识库、public/user/group scope 隔离、QAAgent RAG 注入、本地 `.md`/`.txt` 导入脚本。
- **下一步**: 接入混合检索（FTS + embedding）、PDF/网页导入、文件上传 UI，并逐步扩展到 FitnessAgent 和 MealAgent。
- **收益**: 回答更专业、更个性化，减少 LLM 幻觉，同时保留多用户/多群聊知识隔离。
- **剩余工作量**: 中到大（主要取决于向量数据库、文件管理和后台索引重建需求）。

---

## 五、工程基础设施

### 5.1 依赖管理规范化

- **当前**: `pytest` 等开发依赖在 `[project.optional-dependencies]` 中，`uv sync` 不会自动安装，每次需手动 `uv pip install`
- **目标**: 迁移到 `[dependency-groups]` 或使用 `uv sync --dev` 支持的格式
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

最后更新: 2026-06-01（移除会话记忆持久化升级条目，MemorySaver 已满足当前 MVP 需求；修正章节编号）
