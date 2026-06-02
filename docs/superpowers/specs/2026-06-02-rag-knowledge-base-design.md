# RAG & Knowledge Base Design

> 为 Personal Butler Agent 增加多租户知识库与 RAG 能力，让不同企业微信用户和群聊拥有可隔离的私有知识，同时保留公共知识和后续向量检索扩展空间。

## Overview

当前系统的 QA、Fitness、Meal agent 主要依赖 LLM 内置知识、用户偏好、训练记录和对话记忆。下一阶段要加入知识库，让 agent 能从用户或群聊上传/维护的资料中检索事实依据，再生成回答。

本设计采用：

1. **一套共享知识库底座**：统一存储文档、切块和检索索引。
2. **多租户 scope 过滤**：区分公共知识、用户私有知识、群聊私有知识。
3. **agent domain 过滤**：不同 agent 只检索自己需要的领域资料。
4. **第一版 SQLite FTS/关键词检索**：保持 MVP 轻量，后续再接向量检索。

知识库不是 conversation memory 的替代品。conversation memory 记录用户和助手的历史交互；knowledge base 记录可引用的事实资料、规则、文档和长期知识。

## Scope

### In Scope

- 新增知识库数据模型：文档表、切块表，以及可选 SQLite FTS 索引。
- 新增 `src/knowledge/` 模块，封装文档切块、入库、检索、权限过滤。
- 支持 `public`、`user`、`group` 三种知识作用域。
- 支持 `global`、`qa`、`fitness`、`meal`、`summary` 五类领域标签。
- 第一阶段接入 `QAAgent`，在生成回复前检索知识片段。
- 为后续接入 `FitnessAgent`、`MealAgent` 保留同一检索接口。
- 测试越权隔离、领域过滤、QA prompt 注入和无检索结果时的降级行为。

### Out of Scope

- PDF、图片、网页抓取和文件上传 UI。
- 后台任务、索引重建队列、管理后台。
- Chroma、PGVector 或其他外部向量数据库。
- 群聊中自动读取发言人的个人私有知识库。
- 用知识库替换现有用户偏好、训练记录、群聊消息或 conversation memory。

## Core Design

### 1. Multi-Tenant Knowledge Scope

每份文档和每个 chunk 都必须带作用域字段：

| 字段 | 值 | 说明 |
|------|----|------|
| `scope_type` | `public` / `user` / `group` | 知识可见范围 |
| `scope_id` | `NULL` / `user_id` / `chat_id` | 私有知识所属用户或群聊 |
| `domain` | `global` / `qa` / `fitness` / `meal` / `summary` | 领域标签 |

检索服务必须统一执行可见性过滤：

```text
可见知识 =
  public
  OR 当前 user_id 对应的 user 私有知识
  OR 当前 chat_id 对应的 group 私有知识
```

第一版规则：

- 私聊检索：`public + 当前 user_id 私有知识`
- 群聊检索：`public + 当前 chat_id 私有知识`
- 群聊中不自动混用发言人的个人私有知识，避免隐私泄露。
- 若未来确实需要群聊中调用个人知识，需要新增显式开关，例如 `include_user_private_in_group=True`，并加测试覆盖。

### 2. Domain Filtering

检索时除了 scope，还必须按 agent 的领域过滤：

| Agent | 默认检索 domain |
|-------|-----------------|
| `QAAgent` | `global`, `qa` |
| `FitnessAgent` | `global`, `fitness` |
| `MealAgent` | `global`, `meal` |
| `SummaryAgent` | 默认不检索；需要模板化总结时可启用 `global`, `summary` |

domain 过滤由 `KnowledgeService.search()` 接收参数，不让每个 agent 自己拼查询条件。

### 3. Database Model

新增 `src/models/knowledge.py`。

**knowledge_documents**

| 列 | 类型 | 说明 |
|----|------|------|
| `id` | INTEGER PK | 自增主键 |
| `title` | TEXT NOT NULL | 文档标题 |
| `source` | TEXT NOT NULL | 文件名、URL 或手动来源 |
| `scope_type` | TEXT NOT NULL | `public` / `user` / `group` |
| `scope_id` | TEXT NULL | `user_id` / `chat_id` / NULL |
| `domain` | TEXT NOT NULL | 领域标签 |
| `checksum` | TEXT NOT NULL | 内容校验，用于避免重复导入 |
| `created_by` | TEXT NULL | 创建者 user_id |
| `created_at` | TEXT NOT NULL | ISO 时间戳 |
| `updated_at` | TEXT NOT NULL | ISO 时间戳 |

建议索引：

- `(scope_type, scope_id, domain)`
- `(checksum)`

**knowledge_chunks**

| 列 | 类型 | 说明 |
|----|------|------|
| `id` | INTEGER PK | 自增主键 |
| `document_id` | INTEGER FK | 所属文档 |
| `chunk_index` | INTEGER NOT NULL | 文档内序号 |
| `content` | TEXT NOT NULL | chunk 内容 |
| `scope_type` | TEXT NOT NULL | 冗余作用域，便于过滤 |
| `scope_id` | TEXT NULL | 冗余作用域 ID |
| `domain` | TEXT NOT NULL | 冗余领域，便于过滤 |
| `token_count` | INTEGER NULL | 估算 token 数 |
| `source` | TEXT NOT NULL | 来源快照 |
| `created_at` | TEXT NOT NULL | ISO 时间戳 |

建议索引：

- `(document_id, chunk_index)`
- `(scope_type, scope_id, domain)`

**knowledge_chunks_fts**

第一版若启用 SQLite FTS，可建立 FTS 虚拟表保存 `content`，并通过 `rowid` 或 `chunk_id` 与 `knowledge_chunks` 关联。所有权限和 domain 条件仍以 `knowledge_chunks` 为准，FTS 只负责文本匹配。

### 4. Knowledge Module

新增模块结构：

```text
src/knowledge/
  __init__.py
  chunking.py
  retriever.py
  schemas.py
  service.py
```

**`chunking.py`**

- 负责把 `.md` / `.txt` 文档切成 chunk。
- 第一版使用简单规则：按段落聚合，目标 500-800 中文字，保留标题上下文。
- 返回结构化 chunk 列表，不直接访问数据库。

**`schemas.py`**

定义轻量结构：

```python
KnowledgeChunkResult(
    content: str,
    title: str,
    source: str,
    score: float,
    scope_type: str,
    domain: str,
)
```

**`retriever.py`**

- 封装 SQLite FTS 或关键词检索。
- 输入已过滤后的候选范围参数。
- 输出按分数排序的 chunk 结果。

**`service.py`**

对 agent 暴露唯一入口：

```python
async def search(
    query: str,
    user_id: str,
    chat_type: str = "private",
    chat_id: str | None = None,
    domains: list[str] | None = None,
    limit: int = 5,
    db: AsyncSession,
) -> list[KnowledgeChunkResult]:
    ...
```

关键要求：

- `search()` 内部强制执行 scope 过滤。
- agent 只能传 `query/user_id/chat_type/chat_id/domains/limit`，不能绕过权限条件。
- 没有命中时返回空列表，不抛异常。

### 5. QAAgent Integration

第一阶段只接入 `QAAgent`。

当前流程：

```text
fetch_preferences -> generate_qa_response -> format_qa_response
```

改为：

```text
fetch_preferences -> retrieve_knowledge -> generate_qa_response -> format_qa_response
```

`retrieve_knowledge` 节点：

- 从 state 读取 `message`、`user_id`、`chat_type`、`chat_id`。
- 调用 `KnowledgeService.search(domains=["global", "qa"])`。
- 写回 `knowledge_context`。
- 检索失败时写 `knowledge_error`，但不阻断 QA 回复。

`QAState` 新增字段：

```python
knowledge_context: list[dict]
knowledge_error: str | None
chat_type: str
chat_id: str | None
```

`generate_qa_response` prompt 增加知识库段落：

```text
以下是可参考的知识库资料。优先使用这些资料回答；资料不足时要明确说不知道，不要编造。

[1] {title} - {source}
{content}

[2] ...
```

回答可以在文本中自然提到来源。第一版不强制生成正式引用格式，避免影响微信消息可读性。

### 6. Future Agent Integration

`FitnessAgent` 后续只在 `today_plan`、健身知识问答类路径检索：

- domain: `global`, `fitness`
- 仍然优先使用训练记录和用户偏好。
- 知识库用于动作说明、训练原则、注意事项。

`MealAgent` 后续在生成饮食方案时检索：

- domain: `global`, `meal`
- 仍然优先使用饮食偏好和禁忌。
- 知识库用于食材、营养原则、菜谱资料。

`SummaryAgent` 默认不接 RAG，因为群聊总结应主要基于群聊原文。只有当用户需要固定会议模板或项目背景约束时，再加入 `summary` domain。

## Request Flow

私聊 QA：

```text
POST /api/debug/message 或 WeChat private message
-> IntentRouter.route()
-> AgentRegistry.get("qa"|"unknown")
-> QAAgent.handle()
-> ConversationMemory.get_context()
-> StateGraph:
   fetch_preferences
   -> retrieve_knowledge(public + user scope, global/qa domains)
   -> generate_qa_response
   -> format_qa_response
-> ConversationMemory.save_exchange()
-> AgentResponse
```

群聊 QA：

```text
WeChat group message
-> chat_type="group", chat_id=<群 ID>
-> QAAgent.handle()
-> retrieve_knowledge(public + group scope, global/qa domains)
-> reply
```

## Error Handling

| 场景 | 行为 |
|------|------|
| 没有知识命中 | 正常调用 LLM，prompt 中不注入知识库资料 |
| 检索服务异常 | 记录 `knowledge_error`，QA 回复继续生成 |
| 文档重复导入 | 根据 checksum 跳过或替换，第一版默认跳过 |
| scope_type 非法 | 入库阶段拒绝 |
| domain 非法 | 入库阶段拒绝 |
| 群聊缺失 chat_id | 只检索 public，不检索 group 私有知识 |
| 用户 A 查询用户 B 私有知识 | 永远不可见，测试必须覆盖 |
| 群 A 查询群 B 私有知识 | 永远不可见，测试必须覆盖 |

## Testing

新增测试重点：

1. `KnowledgeService.search()` 返回 public 知识。
2. 用户 A 能检索自己的 user 私有知识。
3. 用户 A 不能检索用户 B 的 user 私有知识。
4. 群 A 能检索自己的 group 私有知识。
5. 群 A 不能检索群 B 的 group 私有知识。
6. 私聊不检索任何 group 私有知识。
7. 群聊第一版不检索发言人的 user 私有知识。
8. domain 过滤生效：QA 不拿到 fitness-only chunk。
9. `QAAgent.handle()` 会把知识片段注入 LLM messages。
10. 检索为空时 QA 正常回复。
11. 检索异常时 QA 不崩溃。

回归验证继续使用：

```bash
DEEPSEEK_API_KEY=test uv run pytest -q
```

## Migration Plan

建议分三阶段实施。

### Stage 1: SQLite Knowledge MVP

- 建 `src/models/knowledge.py`。
- 建 `src/knowledge/` 服务模块。
- 支持 `.md` / `.txt` 文档切块和手动入库接口。
- 支持 scope/domain 过滤和关键词/FTS 检索。
- 接入 `QAAgent`。
- 完成权限隔离和 QA 注入测试。

### Stage 2: Hybrid Retrieval

- 增加 embedding client 和向量存储适配层。
- 保留 `KnowledgeService.search()` 接口不变。
- 检索策略升级为 FTS 精确匹配 + 向量语义检索。
- 加 rerank 或简单分数融合。

### Stage 3: Knowledge Operations

- 增加文件上传、文档列表、删除、重建索引。
- 支持 PDF/网页导入。
- 支持后台重建索引和失败重试。
- 支持按企业、用户、群聊管理知识库权限。

## Design Decisions

1. **共享物理库，不按用户/群聊拆库。**
   - 减少重复存储和重复索引。
   - 通过 scope 过滤保证隔离。

2. **第一版不用外部向量数据库。**
   - 当前项目是单进程 SQLite MVP，几十个文档用 FTS/关键词检索更轻。
   - `KnowledgeService` 保留抽象接口，后续可替换检索实现。

3. **知识库不替代业务数据。**
   - 训练记录仍在 `training_records`。
   - 饮食和健身偏好仍在 `user_preferences`。
   - 群聊消息仍在 `group_messages`。
   - 对话上下文仍由 `ConversationMemory` 管理。

4. **权限过滤集中在 service 层。**
   - agent 不直接访问知识库表。
   - 所有检索都经过 `KnowledgeService.search()`。

## Open Follow-Up

实施前需要确认第一版文档导入入口：

- 方案 A：先写内部 Python service/API 测试，不提供外部上传接口。
- 方案 B：给 debug API 增加一个本地知识导入端点。
- 方案 C：先做命令行导入脚本，适合本地维护资料。

推荐先采用方案 C，便于本地开发和测试；等知识库管理需求稳定后再加 API 或 UI。
