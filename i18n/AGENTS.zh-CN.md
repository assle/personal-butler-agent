# Personal Butler Agent说明

<!-- 保持此文件和 CLAUDE.md 逐字节相同。 -->
<!-- 模板2风格：简洁的根指导加上按需项目记忆文档。 -->

## 项目概况

- 名称： Personal Butler Agent
- 技术栈：Python 3.13+、FastAPI、LangChain、LangGraph、langchain-openai、SQLAlchemy 2 异步、SQLite、Pydantic v2、uv、pytest
- 用途：企业微信风格自然语言工作流程的AI 私人管家：健身记录和计划、膳食计划、群聊摘要和个性化问答。
- 运行时入口：`src.main:app`
- 当前接口：`POST /api/debug/message`，用于本地调试； `GET/POST /api/wechat/callback` 企业微信自建应用消息路由。

## 构建、测试和验证

- 安装依赖项：`uv sync`
- 运行开发服务器：`uv run uvicorn src.main:app --host 0.0.0.0 --port 8000`
- 运行所有测试：`DEEPSEEK_API_KEY=test uv run pytest -q`
- 运行重点测试：`DEEPSEEK_API_KEY=test uv run pytest tests/test_fitness.py -v`
- 启动服务器后手动测试 API：
  `curl -X POST http://localhost:8000/api/debug/message -H "Content-Type: application/json" -d '{"user_id":"assle","message":"打卡 今天练胸 卧推80kg5组8次"}'`

## 代码风格和约定

- 遵循`src/`和`tests/`中现有的Python风格；保持变更小且局部化。
- 使用异步 SQLAlchemy 会话进行数据库工作。不要引入同步数据库访问。
- 将 Pydantic 请求/响应模式保留在 `src/schemas/` 中；将 ORM 模型保留在 `src/models/` 中。
- 保留当前代理边界：意图路由选择一个意图，AgentRegistry 解析为图智能体，handle() 构建状态并运行 StateGraph，返回 `AgentResponse`。
- 新代理遵循以下模式：`state.py`（TypedDict）+ `nodes.py`（异步节点函数）+ `graph.py`（StateGraph 组装 + 智能体类）。
- 优先选择确定性规则来实现稳定的意图匹配，然后选择 LLM 后备来处理不明确的消息。
- 通过使用模拟 LLM 客户端和 `DEEPSEEK_API_KEY=test` 将测试与真实的 DeepSeek 调用隔离。
- 所有函数和方法都必须包含中文注释，描述：（1）函数做什么，（2）输入参数，（3）返回值。每个 `.py` 文件必须以中文注释块开头，解释文件的用途和总体工作流程。

## 架构

- `src/main.py`：FastAPI 应用、lifespan 数据库初始化、单例装配、AgentRegistry 注册。
- `src/router/`：API 路由 — 调试消息端点和条件微信回调路由器。
- `src/wechat/`：企业微信集成 — AES-256-CBC 加密、XML 消息解析、群机器人 Webhook 推送客户端。
- `src/intent/`：具有 LLM 后备的规则优先意图分类。
- `src/agents/`：健身、总结、用餐和问答的业务代理——每个代理都是一个 LangGraph StateGraph 包。
- `src/agents/registry.py`：中央意图到代理映射；新代理在此注册。
- `src/graph/`：共享图形实用程序，MemorySaver 检查点实例。
- `src/db/`：异步 SQLAlchemy 引擎、会话工厂、声明性基础。
- `src/models/`：用于训练记录和用户偏好的 SQLite ORM 模型。
- `src/llm/`：LangChain ChatOpenAI 包装器指向 DeepSeek。
- `tests/`：模式、配置、数据库、意图路由、代理和 API 冒烟流程的 pytest 覆盖范围。

---

## 核心规则

**调查和准确性：**
- 永远不要猜测你没有读过的代码。在提出索赔之前，请阅读文件并使用 `rg` 进行使用。
- 如果用户引用文件，请在回答之前阅读该文件。
- 如果不确定，请说明并提出如何验证的建议。请勿伪造 API、路径或行为。

**范围纪律：**
- 做所要求的事；仅此而已。
- 当意图不明确时，默认进行研究和建议。仅在明确要求时进行编辑。
- 仅进行请求的更改。不要重构相邻代码或为一种用途创建抽象。
- 按照字面上的“仅”、“只是”和“完全”等范围词进行操作。

**验证和安全：**
- 在宣布完成之前，重新检查需求，运行相关测试，并说明哪些内容发生了变化，哪些内容无法验证。
- 在破坏性或难以逆转的操作之前询问：删除文件或分支、强制推送、硬重置或 `--no-verify`。
- 在可行的地方编辑现有文件。除非需要，否则不要创建临时文件，并清理它们。
- 切勿提交秘密或真实的 `.env` 值。

**效率和工具：**
- 并行独立读取和搜索；序列化相关步骤。
- 使用 `rg` 代替 `grep` 和 `rg --files` 代替递归 `find` 进行仓库探索。
- 在合理的情况下，使用结构化解析器和项目 API，而不是临时文本操作。

---

## 项目内存文档

按需阅读。仅加载与当前任务相关的文档。

| 文件 | 目的 | 阅读时间 |
|------|---------|-----------|
| `docs/agent/active-context.md` | 当前状态、MVP 完成情况、近期路线图 | 在会议开始时或计划专题工作之前 |
| `docs/agent/patterns.md` | 既定的实施模式 | 添加或更改代码之前 |
| `docs/agent/decisions.md` | 架构决策和约束 | 在设计选择或范围变更之前 |
| `docs/agent/troubleshooting.md` | 已知问题和经过验证的检查 | 调试失败时 |
| `docs/agent/config-variables.md` | 环境变量和配置行为 | 当接触配置、LLM、DB 或运行时设置时 |

| `docs/agent/upgrade-roadmap.md` | 升级点和改进重点 | 在规划未来工作或评估技术债务时 |

所有文件都是共享项目文档的一部分。如果您更新一个根条目文件，请更新另一个根条目文件，以便 `CLAUDE.md` 和 `AGENTS.md` 保持相同。

### 内存工作流程

1. 会话开始：读取 `docs/agent/active-context.md` 以保持连续性。
2. 实现前：阅读`docs/agent/patterns.md`及相关源文件。
3. 在架构更改之前：阅读 `docs/agent/decisions.md`。
4. 调试时：读取`docs/agent/troubleshooting.md`，然后根据当前代码进行验证。
5. 重大工作之后：仅当用户要求维护项目文档时才更新相关的 `docs/agent/*.md` 文件，否则更改会使文档产生误导。
