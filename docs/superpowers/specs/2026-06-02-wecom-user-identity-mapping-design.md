# WeCom OAuth User Identity Mapping — Design Spec

> Status: approved | Date: 2026-06-02

## Overview

为 Bot 消息处理流程增强用户身份信息：通过企业微信服务端 API（`corp_id` + `corp_secret` → `access_token` → `/cgi-bin/user/get`）获取用户的姓名、部门、头像等详细信息，缓存到本地 SQLite（TTL 24h），在 agent 处理时注入个性化上下文。

## Architecture

```
src/wecom/
├── token_manager.py   # 新增 - access_token 管理
└── user_service.py    # 新增 - 用户信息查询 + 缓存

src/models/
└── wecom_user.py      # 新增 - WeComUser ORM 模型

src/config.py          # 修改 - 新增 WECOM_CORP_SECRET
src/main.py            # 修改 - 实例化并注入 WeComUserService
src/wechat/message_handler.py  # 修改 - 查询用户信息注入 extra_state
src/wechat/router.py            # 修改 - 工厂函数接收 user_service，注入 extra_state
```

## Data Flow

```
消息到达 (WS 或 HTTP callback)
  → message_handler / router 提取 userid
  → user_service.get_user(userid, db)
    → 查 SQLite: WeComUser 存在且 last_synced_at 在 24h 内？
      → 是 → 返回缓存
      → 否 → token_manager.get_token()
              → 调企微 /cgi-bin/user/get?userid=xxx
              → Upsert WeComUser 记录
              → 返回用户信息
  → 将 user_name / user_department 注入 agent extra_state
  → agent 在回复中利用用户信息做个性化
```

## Component 1: Config & Model

### Config (`src/config.py` 追加)

```python
wecom_corp_secret: str = ""
```

### WeComUser ORM (`src/models/wecom_user.py`)

| Field | Type | Notes |
|-------|------|-------|
| id | Integer PK | 自增 |
| userid | String, unique, indexed | 企微用户 ID |
| name | String, nullable | 用户姓名 |
| department | String, nullable | 部门（JSON 数组字符串） |
| avatar | String, nullable | 头像 URL |
| position | String, nullable | 职位 |
| mobile | String, nullable | 手机号 |
| email | String, nullable | 邮箱 |
| last_synced_at | DateTime, default=now | 最后同步时间 |

注册到 `Base.metadata`（通过 import 触发）。

## Component 2: WeComTokenManager

```
class WeComTokenManager:
    __init__(corp_id: str, corp_secret: str)
    async get_token() -> str
```

- 内存缓存 `_token` + `_expires_at`
- 提前 5 分钟刷新（企微默认 7200s TTL）
- `asyncio.Lock` 防止并发刷新风暴
- 调用 `GET /cgi-bin/gettoken?corpid=...&corpsecret=...`
- 失败抛明确异常

## Component 3: WeComUserService

```
class WeComUserService:
    __init__(token_manager: WeComTokenManager)
    async get_user(userid: str, db: AsyncSession) -> WeComUser | None
```

- 先查本地 DB：userid 匹配且 `last_synced_at` 在 24h 内 → 直接返回
- 缓存未命中或过期 → 获取 token → 调 `GET /cgi-bin/user/get?access_token=...&userid=...`
- Upsert 记录，更新 `last_synced_at`
- userid 不存在 → 返回 `None`
- API/网络错误 → log warning，返回过期本地缓存（若有）

## Component 4: Integration

### main.py

当 `wecom_corp_secret` 配置时实例化 `WeComTokenManager` + `WeComUserService`，存到 `app.state`。

### message_handler.py (WS path)

在 `handle_ws_message` 中，agent 处理前调 `user_service.get_user(from_user, db)`，将 `user_name` / `user_department` 注入 `extra_state`。

### router.py (HTTP callback path)

`create_wechat_router` 工厂函数新增 `user_service` 参数。在 `receive_message` 中，agent 处理前查询用户信息，注入 `extra_state`。

### Fault tolerance

- `user_service.get_user()` 失败 → 返回 `None`，agent 正常工作
- `token_manager` 失败 → 不影响消息主流程，仅日志
- `wecom_corp_secret` 未配置 → 整个功能静默跳过，向后兼容

## Testing

| Test file | Coverage |
|-----------|----------|
| `test_token_manager.py` | token 缓存/过期刷新、并发锁、API 错误、提前 5 分钟刷新 |
| `test_wecom_user_service.py` | 缓存命中、过期刷新、userid 不存在、API 失败回退过期缓存 |
| `test_wecom_user_model.py` | ORM 字段、unique constraint、upsert |

Mock 企微 HTTP 调用，SQLite in-memory，遵循现有 `conftest.py` 测试模式。
