# 深度个性化记忆系统设计

> 将记忆系统从"被动检索的文本库"升级为 bot 的认知模型——用户说的每一句话都被持续提炼成画像，画像反过来指导 bot 的行为方式。

## 一、当前状态与目标

### 1.1 当前状态

记忆系统是一个"被动记事本"：
- 用户说"记住：xxx" → 存一条 fact，生成向量
- 用户下次说话 → 语义检索 top-3 相似 facts → 塞进 prompt
- 记忆和 bot 的其他行为是割裂的——记忆只是"被检索到的文本片段"

### 1.2 目标

| 维度 | 当前 | 目标 |
|------|------|------|
| 记忆来源 | 用户主动说"记住" | 每条回调消息附带提取，用户不需要刻意标记 |
| 记忆结构 | 扁平 text + 向量 | 多类型结构化记忆（偏好、事实、习惯、关系） |
| 记忆演化 | 写入后不变 | 新信息强化更新，矛盾主动澄清，过时自然衰减 |
| 记忆价值 | 相关时被检索到 | 主动指导 bot 的行为（语气、回答方式、自我反馈） |
| 记忆生命周期 | 永不过期 | 重要性评分 + 衰减 + 遗忘 |

### 1.3 不做的事

- 不做用户间的记忆共享
- 不做群聊记忆（群聊只收 @ 消息，数据量不足以支撑画像构建）
- 不改变现有 EmbeddingService 基础设施

## 二、记忆类型

| 类型 | 说明 | 例子 | 典型来源 |
|------|------|------|----------|
| preference | 喜欢/不喜欢什么 | "不喝咖啡"、"喜欢短回复" | 隐式提取为主 |
| fact | 客观信息 | "在杭州工作"、"后端工程师"、"用 Rust" | 隐式 + 显式 |
| habit | 反复出现的行为 | "早上查天气"、"开会前确认时间" | 纯隐式，多次出现才确认 |
| relationship | 与他人的关联 | "同事张三(产品经理)"、"领导李四" | 隐式提取 |

## 三、记忆来源

### 3.1 显式记忆

用户主动表达记忆意图 → 直接写入确认画像（source=explicit）：

```
用户: "记住：我不喝咖啡"
→ LLM 标准化 → 写入 user_profile（confidence=1.0, source=explicit）
```

### 3.2 隐式提取

每次 URL 回调消息，bot 在正常处理流程中**旁路异步**提取画像碎片：

```
用户消息进入 PrivateButlerAgent
  │
  ├─→ [主路径] 正常意图处理 → 回复用户（不变，不阻塞）
  │
  └─→ [旁路] 异步轻量提取
        │
        1. 判断是否值得提取
        │  - 纯事实查询跳过（"今天天气"、"总结群聊"）
        │  - 含个人信息、偏好、习惯信号 → 继续
        │
        2. LLM 轻量调用（独立小 prompt）
        │  输入: 用户原话 + 已有画像摘要
        │  输出: [{type, content, signal_strength}]
        │
        3. 结果进入 memory_fragments（碎片池）
        │  - 新信号: 插入新碎片
        │  - 已有信号: 增加 occurrences，更新 last_seen_at
        │  - 矛盾信号: 标记冲突，降低旧记忆置信度
        │
        4. 聚合检查
           - 同一信号出现 ≥ 3 次 → 升级为 user_profile
           - 矛盾信号 → 暂存，下次对话中自然澄清
```

关键设计决策：
- 旁路异步：提取不阻塞主回复路径，失败不影响主要功能
- 不需要"对话结束"概念：每条消息独立提取，碎片池跨时间自然聚合
- 判断是否值得提取：避免每条消息都调 LLM，降低成本和延迟

## 四、数据模型

### 4.1 memory_fragments（碎片池）

每次隐式提取的原始信号，未确认的低置信度信息暂存于此：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| user_id | str | 用户标识 |
| type | str | preference / fact / habit / relationship |
| content | str | 提取出的原始碎片文本 |
| signal_strength | float | 信号强度 0.0~1.0 |
| occurrences | int | 相同信号出现次数 |
| last_seen_at | datetime | 最近一次出现时间 |
| created_at | datetime | 首次出现时间 |

### 4.2 user_profile（确认画像）

碎片聚合后升级的确认记忆，或显式记忆直接写入：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | 主键 |
| user_id | str | 用户标识 |
| type | str | preference / fact / habit / relationship |
| content | str | 画像条目文本 |
| confidence | float | 置信度 0.0~1.0 |
| importance | float | 重要性 0.0~1.0 |
| source | str | explicit / implicit |
| embedding_vector | json | 向量（复用 EmbeddingService） |
| related_profile_ids | json | 关联的其他画像条目 ID 列表 |
| created_at | datetime | 首建时间 |
| updated_at | datetime | 最后更新时间 |
| decayed_at | datetime | 衰减到阈值以下的时间（null=有效） |

### 4.3 聚合规则

```
每次提取后扫描 memory_fragments：
  同一 user_id + 同一 type + content 语义相似（cosine ≥ 0.85）
    → occurrences += 1
    → 如果 occurrences ≥ 3 且尚不存在对应 user_profile：
        升级写入 user_profile
    → 如果已有对应 user_profile：
        更新 confidence、刷新 updated_at
```

### 4.4 现有 user_memories 表

保留，后续显式记忆（source=explicit）直接写 user_profile，user_memories 数据迁移后清理。

## 五、重要性计算

重要性由三个因子加权计算：

| 因子 | 权重 | 计算方式 |
|------|------|----------|
| 来源权重 | 0.4 | explicit=1.0，implicit=0.5 |
| 置信度 | 0.4 | occurrences 折算（1次=0.2, 3次=0.6, 5次以上=1.0） |
| 信号强度 | 0.2 | preference=0.9, fact=0.5, relationship=0.4, habit=0.3 |

公式：`importance = source_weight × 0.4 + confidence × 0.4 + signal_strength × 0.2`

重要性影响：
- **衰减速度**：高重要性记忆衰减慢，低的几个月淡出
- **检索排序**：重要性高的排在前面，优先注入 prompt

## 六、应用层——记忆如何改变 bot 行为

### 6.1 结构化注入 prompt

当前（扁平文本注入）：
```
"关于该用户的已知信息：- 用户不喝咖啡 - 用户在杭州工作"
```

目标（分类结构化注入）：
```
[用户画像]
- 偏好: 不喝咖啡、喜欢短回复、不吃辣
- 事实: 杭州工作、后端工程师、常用 Rust/Python
- 习惯: 早上常查天气
- 关系: 同事张三(产品经理)

[行为指导]
- 推荐饮品时避开咖啡
- 讨论技术时优先用 Rust/Python 举例
- 早上可主动提供天气信息
```

### 6.2 主动应用

不在等用户问了才检索，bot 根据意图类型主动调用记忆：

| 触发场景 | 应用方式 |
|----------|----------|
| 用户问推荐类问题 | 检索偏好 → 排除用户不喜欢的 → 优先匹配用户喜欢的 |
| 用户提到技术问题 | 检索事实 → 用用户熟悉的语言/框架举例 |
| 用户提到人名 | NER 检测 → 检索关系 → "是你之前提过的产品经理张三吗？" |
| 用户情绪低落 | 检索习惯/偏好 → 用用户偏好的互动风格回应 |

### 6.3 自我反馈——bot 主动维护记忆

| 行为 | 触发条件 | 表现 |
|------|----------|------|
| 澄清矛盾 | 新信号与已有画像 confidence ≥ 0.6 的记忆冲突 | "你之前说喜欢早起，今天说9点才起，作息改了吗？" |
| 主动确认 | 碎片池中某信号 occurrences=2 | "听你提到两次杭州了，是在杭州工作吗？" |
| 内部遗忘 | 重要记忆衰减到阈值以下 | 不提醒用户，内部标记 decayed，下次相关对话时重新提取 |

## 七、实现分阶段

### 阶段 1：数据层
- 新增 `MemoryFragment`、`UserProfile` ORM 模型
- 重写 `MemoryService`：碎片写入、聚合、画像 CRUD、重要性计算、检索
- 建表（通过 FastAPI lifespan create_all）

### 阶段 2：提取引擎
- 新增隐式提取 prompt + LLM 调用逻辑
- 旁路集成到 `PrivateButlerAgent`（主路径回复后触发）
- 碎片池 → 画像升级的聚合逻辑
- 判断"是否值得提取"的轻量规则

### 阶段 3：应用层
- 结构化画像注入 prompt（替换当前的扁平 facts 注入）
- 主动应用 hook（推荐、技术、人名等意图触发记忆检索）
- 自我反馈（矛盾检测 + 主动确认）
- 画像衰减和遗忘逻辑

## 八、文件布局

```
新增/重写:
  src/agents/memory/
  ├── __init__.py           # 导出 MemoryService
  ├── models.py             # MemoryFragment + UserProfile ORM
  ├── service.py            # 碎片管理 + 聚合 + 画像 CRUD + 检索 + 衰减
  └── extractor.py          # 隐式提取 prompt + LLM 调用

修改:
  src/agents/private_butler/
  ├── tools.py              # 更新 memory tools（适配新模型）
  ├── graph.py              # prompt 注入改为结构化画像 + 旁路提取钩子
  └── nodes.py              # 主路径结束后触发旁路提取
  src/main.py               # 实例化新 MemoryService + 建表
```

## 九、与现有记忆系统的兼容

| 现有 | 处理 |
|------|------|
| `user_memories` 表 | 保留，阶段 3 后将现有数据迁移到 `user_profile`，之后删除 |
| 5 个 memory tools | 保留接口名称，内部实现切换到新模型 |
| `EmbeddingService` | 不变，继续复用 |
| 记忆注入 prompt | 从扁平 facts 改为结构化画像 |
