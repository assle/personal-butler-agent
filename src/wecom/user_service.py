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
import json
import logging
import httpx
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.wecom_user import WeComUser
from src.wecom.token_manager import WeComTokenManager

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
        except Exception:
            logger.warning("WeComUserService: API fetch failed for %s", userid, exc_info=True)
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
    return json.dumps(department, ensure_ascii=False)
