# ADR-014: 调度器按目标独立配置消息与 Intent

## 背景

当前 ADScheduler 定时推送中，所有目标共享同一个 `SCHEDULER_MESSAGE` 和 `SCHEDULER_INTENT`。用户希望不同的人/群推送不同内容，并且允许 LLM 自动判定 intent 而不必须手动指定。

## 设计

### 配置格式

所有四个字段 `TARGET_TYPE`、`TARGET_ID`、`MESSAGE`、`INTENT` 统一使用 `|` 分隔符（避免英文逗号与消息文本潜在冲突），按位置配对：

```env
SCHEDULER_CRON=0 9 * * *
SCHEDULER_TARGET_TYPE=single|single|group
SCHEDULER_TARGET_ID=user1|user2|chatid1
SCHEDULER_MESSAGE=今日训练建议|今天吃什么？|总结最近群聊
SCHEDULER_INTENT=today_plan||summarize_group
```

### 解析规则

| 字段 | 单值（无 `|`） | 多值 | 空位 |
|------|:---:|:---:|:---:|
| TARGET_TYPE | — | 必须与 TARGET_ID 数量一致 | 不允许 |
| TARGET_ID | 历史兼容 | 必须与 TARGET_TYPE 数量一致 | 不允许 |
| MESSAGE | 所有目标共享 | 数量必须与目标数一致 | 不允许 |
| INTENT | 所有目标共享 | 数量必须与目标数一致 | 允许，空位走自动路由 |

### 运行时行为

```
_scheduled_push (定时触发)
  └─ for type, id, msg, intent in _targets:
       ├─ intent 有值 → agent_registry.get(intent) → agent.handle()
       ├─ intent 为空 → intent_router.route(msg)
       │     ├─ 关键词规则命中 → agent_registry.get(intent)
       │     ├─ 规则未命中 → LLM 分类 → agent_registry.get(intent)
       │     └─ LLM 失败 → unknown → QA agent 兜底
       └─ ws_client.push_message()
```

### 改动范围

- `src/scheduler/__init__.py`：`|` 分隔解析；per-target message/intent；新增 `intent_router` 参数
- `src/main.py`：传 `intent_router` 给 `SchedulerManager`
- `tests/test_scheduler.py`：适配新分隔符 + 新增 per-target/intent 路由测试
- `docs/agent/config-variables.md`：更新
- `.env.example`：更新
- `docs/agent/decisions.md`：本 ADR

### 向后兼容

- 单值格式保持原有行为
- 原有 `SCHEDULER_INTENT` 非空 → 行为不变（跳过路由）
- 原有 `SCHEDULER_INTENT` 为空 → 从"走 QA fallback"改为"走 IntentRouter 自动判定"（能正确路由到更合适的 agent，同时保留了 QA 作为 unknown 兜底）
