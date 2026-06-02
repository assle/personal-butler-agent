# WeCom OAuth User Identity Mapping — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 通过企业微信服务端 API 获取用户详细信息（姓名/部门/头像等），缓存到本地 SQLite（TTL 24h），在 Bot 消息处理流程中为 agent 提供个性化用户上下文。

**Architecture:** 新增 `WeComTokenManager`（access_token 缓存管理）和 `WeComUserService`（用户信息查询 + DB 缓存），通过 `main.py` 注入到 WS 和 HTTP 两条消息路径，在 agent 处理前将 `user_name` / `user_department` 注入 `extra_state`。

**Tech Stack:** Python 3.13+, httpx (async HTTP), SQLAlchemy 2 async, pytest + AsyncMock

---

### Task 1: Config — 新增 WECOM_CORP_SECRET 配置项

**Files:**
- Modify: `src/config.py`

- [ ] **Step 1: 添加 wecom_corp_secret 字段**

```python
# 在 Settings 类中，wechat_agent_id 之后添加：
    # 企业微信服务端 API 密钥（用于获取 access_token，调用用户信息等接口）
    wecom_corp_secret: str = ""
```

- [ ] **Step 2: 验证配置加载**

Run: `cd /Users/assle/dev/personal_butler_agent && WECOM_CORP_SECRET=test123 uv run python -c "from src.config import settings; print('OK:', bool(settings.wecom_corp_secret))"`
Expected: `OK: True`

- [ ] **Step 3: Commit**

```bash
git add src/config.py
git commit -m "feat: add wecom_corp_secret config field for server API access"
```

---

### Task 2: WeComUser ORM 模型

**Files:**
- Create: `src/models/wecom_user.py`
- Modify: `src/models/__init__.py`

- [ ] **Step 1: 创建 WeComUser 模型**

```python
"""
企业微信用户信息缓存 ORM 模型
存储通过企微服务端 API 查询到的用户详细信息，TTL 24h

在总流程中的位置:
  WeComUserService.get_user() → 查 WeComUser 表 → 缓存命中则直接返回 → 未命中则调 API 并 upsert
"""
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy.orm import Mapped, mapped_column
from src.db.base import Base

# 用户信息缓存有效期：24 小时
_USER_TTL_HOURS = 24


class WeComUser(Base):
    """企业微信用户信息缓存模型"""

    __tablename__ = "wecom_users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    """自增主键"""

    userid: Mapped[str] = mapped_column(nullable=False, unique=True, index=True)
    """企业微信用户 ID（如 zhangsan），唯一索引"""

    name: Mapped[Optional[str]] = mapped_column(nullable=True)
    """用户姓名"""

    department: Mapped[Optional[str]] = mapped_column(nullable=True)
    """所属部门（JSON 数组字符串，如 '[1, 2]'）"""

    avatar: Mapped[Optional[str]] = mapped_column(nullable=True)
    """头像 URL"""

    position: Mapped[Optional[str]] = mapped_column(nullable=True)
    """职位"""

    mobile: Mapped[Optional[str]] = mapped_column(nullable=True)
    """手机号"""

    email: Mapped[Optional[str]] = mapped_column(nullable=True)
    """邮箱"""

    last_synced_at: Mapped[str] = mapped_column(
        default=lambda: datetime.now(timezone.utc).isoformat(), nullable=False
    )
    """最后同步时间（ISO 格式 UTC），用于判断缓存是否过期"""

    @classmethod
    def is_fresh(cls, synced_at: str) -> bool:
        """判断缓存的同步时间是否仍在有效期内

        参数:
            synced_at: ISO 格式的最后同步时间字符串

        返回:
            bool: 未超过 24h 返回 True
        """
        try:
            t = datetime.fromisoformat(synced_at)
        except ValueError:
            return False
        now = datetime.now(timezone.utc)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (now - t) < timedelta(hours=_USER_TTL_HOURS)
```

- [ ] **Step 2: 在 models/__init__.py 中注册模型**

在 `src/models/__init__.py` 末尾追加：

```python
from src.models.wecom_user import WeComUser

# 同时在 __all__ 列表的末尾添加:
    "WeComUser",
```

- [ ] **Step 3: 验证模型可以被导入、表可创建**

Run: `cd /Users/assle/dev/personal_butler_agent && uv run python -c "
from src.db.base import Base
from src.models import WeComUser
print('Table:', WeComUser.__tablename__)
print('Fresh test (now):', WeComUser.is_fresh('2026-06-02T00:00:00+00:00'))
print('Fresh test (old):', WeComUser.is_fresh('2020-01-01T00:00:00+00:00'))
print('Columns:', [c.name for c in WeComUser.__table__.columns])
"`

- [ ] **Step 4: Commit**

```bash
git add src/models/wecom_user.py src/models/__init__.py
git commit -m "feat: add WeComUser ORM model for user info caching"
```

---

### Task 3: WeComUser 模型测试

**Files:**
- Create: `tests/test_wecom_user_model.py`

- [ ] **Step 1: 编写模型测试**

```python
"""
WeComUser ORM 模型测试
验证表结构创建、字段唯一约束、is_fresh 缓存判断
"""
import pytest
from sqlalchemy.exc import IntegrityError
from src.models.wecom_user import WeComUser


@pytest.mark.asyncio
async def test_create_wecom_user(db_session):
    """测试创建 WeComUser 记录并查询"""
    user = WeComUser(userid="zhangsan", name="张三")
    db_session.add(user)
    await db_session.flush()

    from sqlalchemy import select
    result = await db_session.execute(
        select(WeComUser).where(WeComUser.userid == "zhangsan")
    )
    found = result.scalar_one()
    assert found.name == "张三"
    assert found.userid == "zhangsan"
    assert found.last_synced_at is not None


@pytest.mark.asyncio
async def test_wecom_user_unique_constraint(db_session):
    """测试 userid 唯一约束"""
    user1 = WeComUser(userid="zhangsan", name="张三")
    db_session.add(user1)
    await db_session.flush()

    user2 = WeComUser(userid="zhangsan", name="张三副本")
    db_session.add(user2)
    with pytest.raises(IntegrityError):
        await db_session.flush()


def test_is_fresh_recent():
    """测试最近时间的 is_fresh 返回 True"""
    assert WeComUser.is_fresh("2026-06-02T10:00:00+00:00") is True


def test_is_fresh_old():
    """测试超过 24h 的 is_fresh 返回 False"""
    assert WeComUser.is_fresh("2020-01-01T00:00:00+00:00") is False


def test_is_fresh_invalid():
    """测试无效时间字符串返回 False"""
    assert WeComUser.is_fresh("not-a-date") is False
```

- [ ] **Step 2: 运行测试验证通过**

Run: `cd /Users/assle/dev/personal_butler_agent && uv run pytest tests/test_wecom_user_model.py -v`
Expected: 4 passed

- [ ] **Step 3: Commit**

```bash
git add tests/test_wecom_user_model.py
git commit -m "test: add WeComUser model tests"
```

---

### Task 4: WeComTokenManager

**Files:**
- Create: `src/wecom/token_manager.py`

- [ ] **Step 1: 创建 WeComTokenManager**

```python
"""
企业微信 access_token 管理器
负责获取、缓存和自动刷新 access_token

Workflow:
  get_token() → 缓存有效直接返回 → 过期则调 /cgi-bin/gettoken 获取新 token → 缓存并返回
  使用 asyncio.Lock 防止并发刷新风暴，提前 5 分钟刷新避免边界问题
"""
import asyncio
import logging
import time
import httpx

logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setLevel(logging.INFO)
    logger.addHandler(h)

# access_token 提前刷新的秒数（5 分钟）
_TOKEN_REFRESH_MARGIN = 300


class TokenError(Exception):
    """access_token 获取失败"""


class WeComTokenManager:
    """企业微信 access_token 管理器

    内部维护内存缓存，自动处理获取和刷新逻辑。
    """

    def __init__(self, corp_id: str, corp_secret: str):
        """初始化 token 管理器

        参数:
            corp_id: 企业微信 CorpID
            corp_secret: 应用 Secret（用于获取 access_token）
        """
        self._corp_id = corp_id
        self._corp_secret = corp_secret
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        """获取有效的 access_token，必要时自动刷新

        返回:
            str: 有效的 access_token

        异常:
            TokenError: 获取 token 失败时抛出
        """
        if self._is_valid():
            return self._token  # type: ignore[return-value]

        async with self._lock:
            # 双重检查：等锁期间可能已被其他协程刷新
            if self._is_valid():
                return self._token  # type: ignore[return-value]

            url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
            params = {
                "corpid": self._corp_id,
                "corpsecret": self._corp_secret,
            }
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(url, params=params)
                    data = resp.json()
            except httpx.HTTPError as e:
                logger.error("WeComTokenManager: HTTP error fetching token: %s", e)
                raise TokenError(f"HTTP error: {e}") from e

            errcode = data.get("errcode", -1)
            if errcode != 0:
                errmsg = data.get("errmsg", "unknown")
                logger.error(
                    "WeComTokenManager: API error fetching token: errcode=%s errmsg=%s",
                    errcode, errmsg,
                )
                raise TokenError(f"API error: {errcode} {errmsg}")

            self._token = data["access_token"]
            expires_in = data.get("expires_in", 7200)
            self._expires_at = time.time() + expires_in - _TOKEN_REFRESH_MARGIN
            logger.info("WeComTokenManager: token refreshed, expires_in=%s", expires_in)
            return self._token

    def _is_valid(self) -> bool:
        """判断当前缓存的 token 是否有效

        返回:
            bool: token 存在且未过期返回 True
        """
        return self._token is not None and time.time() < self._expires_at
```

- [ ] **Step 2: 验证基本逻辑**

Run: `cd /Users/assle/dev/personal_butler_agent && uv run python -c "
from src.wecom.token_manager import WeComTokenManager, TokenError
tm = WeComTokenManager('test_corp_id', 'test_secret')
print('TokenManager created OK')
print('TokenError:', TokenError('test'))
"`

- [ ] **Step 3: Commit**

```bash
git add src/wecom/token_manager.py
git commit -m "feat: add WeComTokenManager for access_token caching"
```

---

### Task 5: WeComTokenManager 测试

**Files:**
- Create: `tests/test_token_manager.py`

- [ ] **Step 1: 编写测试**

```python
"""
WeComTokenManager 测试
覆盖 token 缓存命中、过期刷新、并发锁、API 错误处理
"""
import pytest
from unittest.mock import AsyncMock, patch
from src.wecom.token_manager import WeComTokenManager, TokenError


@pytest.mark.asyncio
async def test_get_token_success():
    """测试首次获取 token 成功"""
    mock_resp = {"errcode": 0, "access_token": "test_token_123", "expires_in": 7200}
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value.json.return_value = mock_resp
        tm = WeComTokenManager("corp", "secret")
        token = await tm.get_token()
        assert token == "test_token_123"


@pytest.mark.asyncio
async def test_get_token_cached():
    """测试 token 在有效期内使用缓存，不重新请求"""
    mock_resp = {"errcode": 0, "access_token": "cached_token", "expires_in": 7200}
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value.json.return_value = mock_resp
        tm = WeComTokenManager("corp", "secret")
        token1 = await tm.get_token()
        token2 = await tm.get_token()
        assert token1 == "cached_token"
        assert token2 == "cached_token"
        # 只请求了一次
        assert mock_get.call_count == 1


@pytest.mark.asyncio
async def test_get_token_api_error():
    """测试 API 返回错误时抛出 TokenError"""
    mock_resp = {"errcode": 40001, "errmsg": "invalid credential"}
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value.json.return_value = mock_resp
        tm = WeComTokenManager("corp", "bad_secret")
        with pytest.raises(TokenError, match="40001"):
            await tm.get_token()


@pytest.mark.asyncio
async def test_get_token_http_error():
    """测试网络错误时抛出 TokenError"""
    import httpx
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.ConnectError("connection refused")
        tm = WeComTokenManager("corp", "secret")
        with pytest.raises(TokenError, match="HTTP error"):
            await tm.get_token()


@pytest.mark.asyncio
async def test_get_token_expiry():
    """测试 token 过期后自动刷新"""
    import time
    mock_resp = {"errcode": 0, "access_token": "new_token", "expires_in": 7200}
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value.json.return_value = mock_resp
        tm = WeComTokenManager("corp", "secret")
        # 先取一个 token
        await tm.get_token()
        assert mock_get.call_count == 1
        # 强制过期
        tm._expires_at = time.time() - 10
        token2 = await tm.get_token()
        assert token2 == "new_token"
        assert mock_get.call_count == 2
```

- [ ] **Step 2: 运行测试**

Run: `cd /Users/assle/dev/personal_butler_agent && uv run pytest tests/test_token_manager.py -v`
Expected: 5 passed

- [ ] **Step 3: Commit**

```bash
git add tests/test_token_manager.py
git commit -m "test: add WeComTokenManager tests"
```

---

### Task 6: WeComUserService

**Files:**
- Create: `src/wecom/user_service.py`

- [ ] **Step 1: 创建 WeComUserService**

```python
"""
企业微信用户信息服务
负责查询用户详细信息（姓名/部门/头像等），支持本地 DB 缓存（TTL 24h）

Workflow:
  get_user(userid, db) → 查 wecom_users 表
    → 缓存命中且未过期 → 直接返回
    → 缓存未命中或过期 → 获取 access_token → 调企微 /cgi-bin/user/get
      → 成功 → upsert WeComUser 记录 → 返回
      → userid 不存在 (60111) → 返回 None
      → 其他 API 错误 → 返回过期的本地缓存（若有）
"""
import logging
import httpx
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.wecom_user import WeComUser
from src.wecom.token_manager import WeComTokenManager, TokenError

logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    h = logging.StreamHandler()
    h.setLevel(logging.INFO)
    logger.addHandler(h)


class WeComUserService:
    """企业微信用户信息服务，从企微 API 拉取用户信息并缓存到本地 DB"""

    def __init__(self, token_manager: WeComTokenManager):
        """初始化用户信息服务

        参数:
            token_manager: access_token 管理器
        """
        self._token_manager = token_manager

    async def get_user(self, userid: str, db: AsyncSession) -> WeComUser | None:
        """获取用户信息（优先缓存，过期则刷新）

        参数:
            userid: 企业微信用户 ID
            db: 数据库异步会话

        返回:
            WeComUser | None: 用户信息，userid 不存在或查询失败时可能为 None
        """
        # 1. 查本地缓存
        result = await db.execute(
            select(WeComUser).where(WeComUser.userid == userid)
        )
        cached = result.scalar_one_or_none()

        if cached is not None and WeComUser.is_fresh(cached.last_synced_at):
            logger.debug("WeComUserService: cache hit for %s", userid)
            return cached

        # 2. 缓存过期或不存在，调企微 API 刷新
        try:
            user_data = await self._fetch_from_api(userid)
        except Exception as e:
            logger.warning("WeComUserService: API fetch failed for %s: %s", userid, e)
            # 返回过期的本地缓存（若有）
            return cached

        if user_data is None:
            # userid 不存在
            return None

        # 3. Upsert 到 DB
        now = datetime.now(timezone.utc).isoformat()
        if cached is not None:
            cached.name = user_data.get("name")
            cached.department = _serialize_department(user_data.get("department"))
            cached.avatar = user_data.get("avatar")
            cached.position = user_data.get("position")
            cached.mobile = user_data.get("mobile")
            cached.email = user_data.get("email")
            cached.last_synced_at = now
        else:
            cached = WeComUser(
                userid=userid,
                name=user_data.get("name"),
                department=_serialize_department(user_data.get("department")),
                avatar=user_data.get("avatar"),
                position=user_data.get("position"),
                mobile=user_data.get("mobile"),
                email=user_data.get("email"),
                last_synced_at=now,
            )
            db.add(cached)

        await db.flush()
        logger.info("WeComUserService: user synced for %s", userid)
        return cached

    async def _fetch_from_api(self, userid: str) -> dict | None:
        """调用企微 API 获取用户信息

        参数:
            userid: 企业微信用户 ID

        返回:
            dict | None: 用户信息字段，userid 不存在时返回 None

        异常:
            TokenError: token 获取失败
            httpx.HTTPError: 网络错误
            RuntimeError: API 业务错误
        """
        token = await self._token_manager.get_token()
        url = "https://qyapi.weixin.qq.com/cgi-bin/user/get"
        params = {"access_token": token, "userid": userid}

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            data = resp.json()

        errcode = data.get("errcode", -1)
        if errcode == 60111:
            # userid 不存在
            logger.info("WeComUserService: userid %s not found in corp", userid)
            return None
        if errcode != 0:
            raise RuntimeError(f"API error: {errcode} {data.get('errmsg', 'unknown')}")

        return data


def _serialize_department(department) -> str | None:
    """将部门信息序列化为 JSON 字符串

    参数:
        department: 部门 ID 列表或 None

    返回:
        str | None: JSON 数组字符串
    """
    if department is None:
        return None
    import json
    return json.dumps(department, ensure_ascii=False)
```

- [ ] **Step 2: 验证导入**

Run: `cd /Users/assle/dev/personal_butler_agent && uv run python -c "from src.wecom.user_service import WeComUserService; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add src/wecom/user_service.py
git commit -m "feat: add WeComUserService for user info query and caching"
```

---

### Task 7: WeComUserService 测试

**Files:**
- Create: `tests/test_wecom_user_service.py`

- [ ] **Step 1: 编写测试**

```python
"""
WeComUserService 测试
覆盖缓存命中、过期刷新、userid 不存在、API 错误回退过期缓存
"""
import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy import select
from src.models.wecom_user import WeComUser
from src.wecom.user_service import WeComUserService


@pytest.fixture
def mock_token_manager():
    """创建模拟的 WeComTokenManager"""
    tm = AsyncMock()
    tm.get_token.return_value = "mock_token"
    return tm


@pytest.mark.asyncio
async def test_cache_hit(db_session, mock_token_manager):
    """测试缓存命中，不调 API 直接返回"""
    # 预写入缓存
    cached = WeComUser(
        userid="zhangsan", name="张三",
        last_synced_at="2026-06-02T10:00:00+00:00",
    )
    db_session.add(cached)
    await db_session.flush()

    svc = WeComUserService(mock_token_manager)
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        result = await svc.get_user("zhangsan", db_session)
        assert result is not None
        assert result.name == "张三"
        # 未调 API
        mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_cache_miss_fetch_from_api(db_session, mock_token_manager):
    """测试缓存未命中，调 API 获取并写入缓存"""
    api_resp = {
        "errcode": 0,
        "userid": "zhangsan",
        "name": "张三",
        "department": [1, 2],
        "avatar": "http://avatar.url",
        "position": "工程师",
        "mobile": "13800138000",
        "email": "zhangsan@example.com",
    }
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value.json.return_value = api_resp
        svc = WeComUserService(mock_token_manager)
        result = await svc.get_user("zhangsan", db_session)
        assert result is not None
        assert result.name == "张三"
        assert result.position == "工程师"
        assert result.department == '[1, 2]'

    # 验证写入 DB
    stmt = select(WeComUser).where(WeComUser.userid == "zhangsan")
    db_result = await db_session.execute(stmt)
    saved = db_result.scalar_one()
    assert saved.name == "张三"


@pytest.mark.asyncio
async def test_user_not_found_in_api(db_session, mock_token_manager):
    """测试 userid 在企微不存在时返回 None"""
    api_resp = {"errcode": 60111, "errmsg": "userid not found"}
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value.json.return_value = api_resp
        svc = WeComUserService(mock_token_manager)
        result = await svc.get_user("nobody", db_session)
        assert result is None


@pytest.mark.asyncio
async def test_api_error_fallback_to_stale_cache(db_session, mock_token_manager):
    """测试 API 调用失败时回退返回过期缓存"""
    # 预写入过期缓存
    stale = WeComUser(
        userid="zhangsan", name="旧名称",
        last_synced_at="2020-01-01T00:00:00+00:00",
    )
    db_session.add(stale)
    await db_session.flush()

    svc = WeComUserService(mock_token_manager)
    # API 调用失败（token 获取失败）
    mock_token_manager.get_token.side_effect = Exception("token error")
    result = await svc.get_user("zhangsan", db_session)
    assert result is not None
    assert result.name == "旧名称"
```

- [ ] **Step 2: 运行测试**

Run: `cd /Users/assle/dev/personal_butler_agent && uv run pytest tests/test_wecom_user_service.py -v`
Expected: 4 passed

- [ ] **Step 3: Commit**

```bash
git add tests/test_wecom_user_service.py
git commit -m "test: add WeComUserService tests"
```

---

### Task 8: 集成到 main.py

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: 在 lifespan 中添加 WeComUserService 初始化**

在 `src/main.py` 的 lifespan 中，WS 启动之前添加：

```python
    # 初始化企微用户信息服务（需要 corp_id 和 corp_secret 同时配置）
    wecom_user_service = None
    if settings.wecom_corp_secret and settings.wechat_corp_id:
        from src.wecom.token_manager import WeComTokenManager
        from src.wecom.user_service import WeComUserService

        token_manager = WeComTokenManager(
            corp_id=settings.wechat_corp_id,
            corp_secret=settings.wecom_corp_secret,
        )
        wecom_user_service = WeComUserService(token_manager=token_manager)
        app.state.wecom_user_service = wecom_user_service
        logger.info("WeComUserService: initialized")
```

- [ ] **Step 2: 将 user_service 注入到 WS 消息处理回调**

修改 WS 的 `on_message_callback` 闭包，在调用 `handle_ws_message` 时传入 `user_service`：

```python
        async def on_message_callback(msg: dict, req_id: str):
            async with async_session() as db:
                try:
                    await handle_ws_message(
                        msg, req_id, ws_client, intent_router, agent_registry, db,
                        user_service=wecom_user_service,
                    )
                    await db.commit()
                except Exception:
                    await db.rollback()
                    logger.exception("WS message handler: unhandled error")
```

- [ ] **Step 3: 将 user_service 注入到 HTTP 回调路由**

修改 `create_wechat_router` 调用，传入 `user_service`：

```python
    if settings.wechat_corp_id and settings.wechat_token:
        from src.wechat.router import create_wechat_router

        wechat_router = create_wechat_router(
            intent_router=intent_router,
            agent_registry=agent_registry,
            corp_id=settings.wechat_corp_id,
            token=settings.wechat_token,
            encoding_aes_key=settings.wechat_encoding_aes_key,
            user_service=wecom_user_service,
        )
        app.include_router(wechat_router)
```

- [ ] **Step 4: 验证应用启动**

Run: `cd /Users/assle/dev/personal_butler_agent && timeout 3 uv run python -c "from src.main import app; print('App imports OK')" || true`

- [ ] **Step 5: Commit**

```bash
git add src/main.py
git commit -m "feat: wire WeComUserService into app lifespan and message handlers"
```

---

### Task 9: 集成到 message_handler.py (WS 路径)

**Files:**
- Modify: `src/wechat/message_handler.py`

- [ ] **Step 1: 修改 handle_ws_message 函数签名和逻辑**

在 `handle_ws_message` 函数签名中添加 `user_service` 参数，并在 agent 处理前查询用户信息注入 `extra_state`。

将函数签名从：
```python
async def handle_ws_message(
    msg: dict,
    req_id: str,
    ws_client,
    intent_router: IntentRouter,
    agent_registry: AgentRegistry,
    db: AsyncSession,
):
```

改为：
```python
async def handle_ws_message(
    msg: dict,
    req_id: str,
    ws_client,
    intent_router: IntentRouter,
    agent_registry: AgentRegistry,
    db: AsyncSession,
    user_service=None,
):
```

在 `from_user = msg.get("from", {}).get("userid", "")` 之后、私聊 agent 处理之前，加入用户信息查询和 `extra_state` 构建逻辑。

将当前硬编码的 `extra_state`：
```python
extra_state={"chat_type": chat_type, "chat_id": chat_id or None},
```

改为统一的 extra_state 字典，在开头处构建：
```python
    # 构建 extra_state（用户上下文 + 会话上下文）
    extra_state: dict = {"chat_type": chat_type, "chat_id": chat_id or None}

    # 查询企微用户信息注入 agent 上下文
    if user_service is not None and from_user:
        try:
            user_info = await user_service.get_user(from_user, db)
            if user_info is not None:
                extra_state["user_name"] = user_info.name
                extra_state["user_department"] = user_info.department
        except Exception as e:
            logger.warning("WS handler: failed to get user info for %s: %s", from_user, e)
```

然后将群聊和私聊两处 `agent.handle(... extra_state=...)` 的 `extra_state` 参数改为使用 `extra_state` 变量。

移除群聊分支中：
```python
extra_state={"chat_id": chat_id, "chat_type": "group"},
```

改为：
```python
extra_state=extra_state,
```

移除私聊分支中：
```python
extra_state={"chat_type": chat_type, "chat_id": chat_id or None},
```

改为：
```python
extra_state=extra_state,
```

- [ ] **Step 2: 验证导入**

Run: `cd /Users/assle/dev/personal_butler_agent && uv run python -c "from src.wechat.message_handler import handle_ws_message; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add src/wechat/message_handler.py
git commit -m "feat: inject WeCom user info into WS message handler extra_state"
```

---

### Task 10: 集成到 router.py (HTTP 回调路径)

**Files:**
- Modify: `src/wechat/router.py`

- [ ] **Step 1: 修改 create_wechat_router 工厂函数和 receive_message 逻辑**

`create_wechat_router` 新增 `user_service` 参数：

```python
def create_wechat_router(
    intent_router: IntentRouter,
    agent_registry: AgentRegistry,
    corp_id: str,
    token: str,
    encoding_aes_key: str,
    user_service=None,
) -> APIRouter:
```

在 `create_wechat_router` 文档字符串中补充参数说明：

```
        user_service: 可选，WeComUserService 实例，用于查询用户详细信息
```

在 `receive_message` 内部，`from_user` 提取之后、agent 处理之前，添加用户信息查询和 extra_state 构建：

在 `msg_type != "text"` 检查之前，添加 extra_state 构建：

```python
        # 构建 extra_state（用户上下文 + 会话上下文）
        extra_state: dict = {"chat_type": chat_type, "chat_id": chat_id or None}

        if user_service is not None and from_user:
            try:
                user_info = await user_service.get_user(from_user, db)
                if user_info is not None:
                    extra_state["user_name"] = user_info.name
                    extra_state["user_department"] = user_info.department
            except Exception as e:
                logger.warning("WeChat callback: failed to get user info for %s: %s", from_user, e)
```

然后将群聊和私聊两处 `agent.handle(... extra_state=...)` 改为使用 `extra_state` 变量，移除现有的 `extra_state=` 参数中的硬编码 dict。

- [ ] **Step 2: 验证导入**

Run: `cd /Users/assle/dev/personal_butler_agent && uv run python -c "from src.wechat.router import create_wechat_router; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add src/wechat/router.py
git commit -m "feat: inject WeCom user info into HTTP callback router extra_state"
```

---

### Task 11: 最终验证

- [ ] **Step 1: 运行全部测试**

```bash
cd /Users/assle/dev/personal_butler_agent && uv run pytest -q
```

Expected: 所有既有测试通过 + 新增测试通过，总数 ≥ 127

- [ ] **Step 2: 验证未配置时向后兼容**

Run: `cd /Users/assle/dev/personal_butler_agent && timeout 3 uv run python -c "
from src.main import app
# 检查无 wecom_corp_secret 时 app.state 上没有 user_service
import asyncio
async def check():
    print('App created OK (no wecom_corp_secret)')
asyncio.run(check())
" || true`

- [ ] **Step 3: 运行完整测试确认回归通过**

```bash
cd /Users/assle/dev/personal_butler_agent && DEEPSEEK_API_KEY=test uv run pytest -q
```

Expected: all tests pass
```

- [ ] **Step 4: Commit final state**

```bash
git add -A
git commit -m "chore: final verification after WeCom user identity mapping integration"
```
