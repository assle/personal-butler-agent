# 个性化记忆功能设计

> 让 bot 记住用户偏好和事实，跨会话持久化，后续对话自动引用。

## 一、与现有对话记忆的区别

| | 对话记忆（现有） | 个性化记忆（新增） |
|------|-----------|-----------|
| **粒度** | 6 轮对话窗口 | 单条事实/偏好 |
| **生命周期** | 压缩后丢弃原始消息 | 永久保留，直到用户删除 |
| **依赖上下文** | 强依赖最近对话 | 不依赖上下文，跨会话可用 |
| **检索方式** | 全量注入 prompt | 语义向量检索 top-K |
| **管理** | 自动 | 用户可查看、修改、删除 |

## 二、数据模型

```sql
user_memories
├── id            INTEGER PK 自增
├── user_id       TEXT 索引，记忆归属
├── content       TEXT 记忆文本，如"用户不喝咖啡，偏好喝茶"
├── embedding     BLOB 向量嵌入
├── source        TEXT explicit / extracted
├── created_at    DATETIME
└── updated_at    DATETIME
```

一人多行，每行一条独立记忆。embedding 字段用于语义检索。

## 三、生命周期

### 3.1 创建

**显式创建**（用户主动）：
```
用户: "记住：我不喝咖啡，偏好喝茶"
Bot:   "已记住：你偏好喝茶，不喜欢咖啡"
```
→ LLM 标准化 → 生成 embedding → 写入 user_memories → 回复确认

**自动提取**（对话后扫描）：
- 每轮对话后，LLM 扫描本轮内容
- 提取"可能值得记住的用户事实"
- 与已有记忆做去重/合并
- 静默存入（不打扰用户）
- 可配置开关（默认关闭，用户可选开启）

### 3.2 检索

```
用户发新消息
  → embedding 检索 top-3 相关记忆（相似度阈值过滤）
  → 注入 PrivateButlerAgent system prompt:
    "关于该用户的已知信息：
     - 用户不喝咖啡，偏好喝茶
     - 用户在北京朝阳区工作"
  → LLM 在对话中自然引用
```

### 3.3 查看

```
用户: "我有什么记忆？" / "你记得我什么？"
Bot:   "我记得以下关于你的信息：
       1. 不喝咖啡，偏好喝茶
       2. 在北京朝阳区工作
       3. 喜欢短回复"
```

### 3.4 修改

```
用户: "改为：我现在喝咖啡了"
Bot:   "已更新：从'不喝咖啡' → '现在喝咖啡'"
```
→ 语义匹配找到相关记忆 → 更新 content → 重新生成 embedding

### 3.5 删除

```
用户: "忘记关于咖啡的事" / "删除我的咖啡偏好"
Bot:   "已删除关于咖啡的记忆"
```
→ 语义匹配 → 校验 user_id → 确认后删除

## 四、权限控制

- **记忆归属**：每条记忆绑定 `user_id`
- **私聊**：只能管理自己的记忆
- **群聊**：不暴露记忆管理能力（群聊中不能查看/修改/删除记忆）
- **自动提取**：只在私聊场景启用（群聊不提取）

## 五、检索策略

```
用户消息 → embedding → 与所有记忆算余弦相似度
  → 取 top-3（阈值 > 0.6）
  → 注入 system prompt 的 memory context 段
  → 阈值以下或结果为空 → 不注入（不带来噪声）
```

## 六、组件集成

```
新增:
  src/agents/memory/
  ├── __init__.py
  ├── models.py          # UserMemory ORM
  ├── service.py          # CRUD + 检索 + 自动提取
  └── （复用 src/knowledge/embedding.py）

修改:
  src/agents/private_butler/
  ├── tools.py            # 新增 memory 相关 tools
  └── （prompt 层新增 memory context 段）
  src/main.py             # 初始化 memory service

不需要:
  新独立 agent、新 scheduler job
```

## 七、文件布局

```
新增:
  src/agents/memory/
  ├── __init__.py           # 导出 MemoryService
  ├── models.py             # UserMemory ORM
  └── service.py            # add / search / list / update / delete / extract_facts

修改:
  src/agents/private_butler/tools.py  # 新增 5 个 memory tools
  src/agents/private_butler/graph.py  # system prompt 新增 memory context 注入
  src/main.py                         # 初始化 MemoryService + 建表
```
