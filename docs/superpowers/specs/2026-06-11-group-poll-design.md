# 群投票功能设计

> 在企业微信群聊中通过智能机器人创建投票、成员投票、自动公布结果。

## 一、可行性约束

企业微信智能机器人在群聊中的硬性限制：

- **只能收到 @自己的消息**，无法监听全部群聊
- **只能通过 response_url 被动回复**，不能主动向群发消息
- 群 webhook 可主动推送，项目已有 `WebhookPushClient` 和 APScheduler

结论：创建/投票/查看通过 @bot 触发，到期公布通过 webhook + scheduler 主动推送。

## 二、数据模型

### Poll

```python
class Poll(Base):
    __tablename__ = "polls"

    id = Column(Integer, primary_key=True)
    chat_id = Column(String, nullable=False, index=True)          # 群聊 ID
    creator_user_id = Column(String, nullable=False)              # 创建者
    title = Column(String, nullable=False)                        # 投票标题
    options = Column(JSON, nullable=False)                        # ["香山", "故宫", "颐和园"]
    end_time = Column(DateTime, nullable=True)                    # 到期时间，空=手动结束
    status = Column(String, nullable=False, default="active")     # active / ended
    created_at = Column(DateTime, nullable=False)
```

### PollVote

```python
class PollVote(Base):
    __tablename__ = "poll_votes"

    id = Column(Integer, primary_key=True)
    poll_id = Column(Integer, ForeignKey("polls.id"), nullable=False, index=True)
    user_id = Column(String, nullable=False)                      # 投票人
    option_index = Column(Integer, nullable=False)                # 选项序号，0-based
    updated_at = Column(DateTime, nullable=False)

    __table_args__ = (UniqueConstraint("poll_id", "user_id"),)    # 一人一票
```

### GroupWebhook

```python
class GroupWebhook(Base):
    __tablename__ = "group_webhooks"

    chat_id = Column(String, primary_key=True)                    # 群聊 ID
    webhook_url = Column(String, nullable=False)                   # webhook 地址
    display_name = Column(String, nullable=True)                   # 展示用群名
```

## 三、交互流程

### 3.1 创建投票

```
用户: @bot 创建投票：周末团建去哪？A.香山 B.故宫 C.颐和园，明天下午5点结束

Bot:  📊 投票已创建「周末团建去哪？」
      A. 香山   B. 故宫   C. 颐和园
      ⏰ 截止：2026-06-12 17:00
      回复 @bot + 选项字母即可投票
```

- 选项用正则匹配 `A.xxx B.xxx` 格式
- 结束时间用 LLM 解析自然语言（"明天下午5点"→datetime），可选
- 解析失败时回复提示，不创建

### 3.2 投票

```
用户: @bot A

Bot:   ✅ 已记录：你投了「A.香山」
```

- 同一群有多个 active poll 时，默认投最近创建的
- 多个 poll 时回复提示："当前有2个进行中的投票，请指明：@bot 投票1 A 或 @bot 给「标题」投A"
- 改票：直接投另一个选项即可，自动覆盖旧票（UPSERT）

### 3.3 查看结果

```
用户: @bot 投票结果

Bot:   📊 当前投票「周末团建去哪？」
      A.香山 3票 | B.故宫 5票 | C.颐和园 2票
      共10人参与
```

### 3.4 结束投票

```
用户: @bot 结束投票

Bot:   📊 投票结束「周末团建去哪？」
      B.故宫 5票 🏆 获胜
      共10人参与
      [同时通过 webhook 推送同样内容到群]
```

- 手动结束时若已注册 scheduler 任务，需取消
- 有 webhook URL 时推送结果，否则仅通过 response_url 回复
- 标记 poll.status = "ended"

### 3.5 自动到期

- 创建投票指定了结束时间 → 注册 APScheduler 一次性任务
- 到期触发 → 统计结果 → WebhookPushClient 推送 → 标记 ended
- webhook URL 查不到 → 降级为等待手动查看

## 四、PollAgent 内部设计

### 4.1 状态

```python
class PollState(TypedDict, total=False):
    intent: str        # create_poll / cast_vote / view_results / end_poll
    message: str
    user_id: str
    chat_id: str
    reply: str
    data: dict
    error: str
```

### 4.2 图结构

```
START → classify_poll_intent
           ├─ create_poll   → create_poll_node   → END
           ├─ cast_vote     → cast_vote_node     → END
           ├─ view_results  → view_results_node  → END
           └─ end_poll      → end_poll_node      → END
```

### 4.3 节点职责

| 节点 | 实现方式 |
|------|----------|
| classify_poll_intent | 关键词优先，兜底 LLM |
| create_poll_node | 正则解析选项 + LLM 解析时间 → 写 DB → 注册 scheduler |
| cast_vote_node | 查 active polls → UPSERT PollVote → 回复确认 |
| view_results_node | COUNT GROUP BY → 排名 → 格式化 |
| end_poll_node | 标记 ended → 取消 scheduler → 推 webhook |

## 五、集成点

### 5.1 group_policy.py 修改

新增触发分类：

- 关键词 "创建投票""发起投票""投票" → `category="poll_create"`
- 关键词 "投票结果""查看投票" → `category="poll_view"`
- 关键词 "结束投票""关闭投票" → `category="poll_end"`
- 群有 active poll 且消息为短文本（1-5字符）→ `category="poll_vote"`

### 5.2 GroupMentionAgent 修改

`route_by_category` 新增 `"poll_create"` / `"poll_vote"` / `"poll_view"` / `"poll_end"` 分支，统一路由到 `PollAgent.handle()`。

### 5.3 main.py 修改

- 初始化时 `Base.metadata.create_all` 自动建 `polls`/`poll_votes`/`group_webhooks` 表
- 实例化 `PollAgent`，注入 `LLMClient`、`WebhookPushClient`、`SchedulerManager`
- 传入 `GroupMentionAgent` 构造函数

### 5.4 scheduler 修改

`SchedulerManager` 新增两个方法：

- `schedule_poll_end(poll_id, end_time)` → `add_job` 一次性任务
- `cancel_poll_end(poll_id)` → `remove_job`

## 六、文件布局

```
新增:
  src/models/poll.py              # Poll + PollVote ORM
  src/models/group_webhook.py     # GroupWebhook ORM
  src/agents/poll/
  ├── __init__.py
  ├── state.py                    # PollState
  ├── nodes.py                    # classify + 4 个操作节点
  └── graph.py                    # PollAgent 类 + handle()

修改:
  src/messaging/group_policy.py   # 新增投票触发分类
  src/agents/group_mention/       # route_by_category 加 poll 分支
  src/scheduler/manager.py        # 新增动态 add_job / remove_job
  src/main.py                     # 注册 PollAgent，建表

不变:
  src/wechat/                     # 回调入口不变
  src/messaging/dispatch.py       # 分发逻辑不变
  src/scheduler/client.py         # WebhookPushClient 直接复用
```

## 七、错误处理

| 场景 | 处理 |
|------|------|
| 选项解析失败 | 回复"请用格式：A.选项1 B.选项2" |
| 时间解析失败 | 回复"无法识别结束时间，请重新指定" |
| 无 active poll 时投票 | 回复"当前没有进行中的投票" |
| 多个 active poll 投票歧义 | 列出所有 active poll，让用户指明 |
| webhook URL 未配置 | 降级为等待手动查看，回复中提示 |
| scheduler 任务失败 | 不影响投票创建，到期后可通过手动结束查看 |
