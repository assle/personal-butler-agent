"""
企业微信自建应用主动消息客户端
缓存 access_token、转换智能机器人 open_userid，并发送应用文本消息。
"""
from collections.abc import Awaitable, Callable
from typing import Protocol

import httpx


class AccessTokenCache(Protocol):
    """access_token 缓存接口"""

    async def get(self, key: str) -> str | None:
        """读取缓存值"""
        raise NotImplementedError

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        """按 TTL 保存缓存值"""
        raise NotImplementedError

    async def delete(self, key: str) -> None:
        """删除失效缓存值"""
        raise NotImplementedError


class RedisAccessTokenCache:
    """基于 redis.asyncio 的 access_token 缓存"""

    def __init__(self, redis_client):
        """注入 Redis 客户端"""
        self._redis = redis_client

    async def get(self, key: str) -> str | None:
        """读取并解码 token"""
        value = await self._redis.get(key)
        if value is None:
            return None
        return value.decode() if isinstance(value, bytes) else str(value)

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        """保存带 TTL 的 token"""
        await self._redis.set(key, value, ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        """删除 token"""
        await self._redis.delete(key)


class WeComAppApiError(RuntimeError):
    """企业微信自建应用 API 业务错误"""


GetJson = Callable[[str, dict], Awaitable[dict]]
PostJson = Callable[[str, dict, dict], Awaitable[dict]]


class WeComAppMessageClient:
    """企业微信自建应用主动消息客户端"""

    def __init__(
        self,
        *,
        corp_id: str,
        secret: str,
        agent_id: int,
        cache: AccessTokenCache,
        get_json: GetJson | None = None,
        post_json: PostJson | None = None,
    ):
        """初始化凭据、缓存和可注入 HTTP 函数"""
        self._corp_id = corp_id
        self._secret = secret
        self._agent_id = agent_id
        self._cache = cache
        self._get_json = get_json
        self._post_json = post_json
        self._token_key = f"wecom:app:{corp_id}:{agent_id}:access_token"

    async def get_access_token(self, force_refresh: bool = False) -> str:
        """读取缓存或调用 gettoken；提前 300 秒过期"""
        if not force_refresh:
            cached = await self._cache.get(self._token_key)
            if cached:
                return cached
        response = await self._get(
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
            {"corpid": self._corp_id, "corpsecret": self._secret},
        )
        self._ensure_ok(response)
        token = str(response.get("access_token", ""))
        if not token:
            raise WeComAppApiError("gettoken response missing access_token")
        ttl = max(60, int(response.get("expires_in", 7200)) - 300)
        await self._cache.set(self._token_key, token, ttl)
        return token

    async def convert_open_userid(self, open_userid: str) -> str:
        """把智能机器人 open_userid 转换为自建应用 userid"""
        response = await self._post_with_token_retry(
            "https://qyapi.weixin.qq.com/cgi-bin/batch/openuserid_to_userid",
            {"open_userid_list": [open_userid]},
        )
        self._ensure_ok(response)
        if open_userid in response.get("invalid_open_userid_list", []):
            raise WeComAppApiError("open_userid is invalid or outside app visibility")
        for item in response.get("userid_list", []):
            if item.get("open_userid") == open_userid and item.get("userid"):
                return str(item["userid"])
        raise WeComAppApiError("open_userid conversion returned no userid")

    async def send_text(self, userid: str, content: str) -> str:
        """向单个成员发送应用文本消息并返回 msgid"""
        response = await self._post_with_token_retry(
            "https://qyapi.weixin.qq.com/cgi-bin/message/send",
            {
                "touser": userid,
                "msgtype": "text",
                "agentid": self._agent_id,
                "text": {"content": self._truncate_utf8(content, 2048)},
                "enable_duplicate_check": 1,
                "duplicate_check_interval": 1800,
            },
        )
        self._ensure_ok(response)
        if response.get("invaliduser") or response.get("unlicenseduser"):
            raise WeComAppApiError(
                "recipient is invalid, outside visibility, or unlicensed"
            )
        return str(response.get("msgid", ""))

    async def _post_with_token_retry(self, url: str, payload: dict) -> dict:
        """token 失效时清缓存并只重试一次"""
        for attempt in range(2):
            token = await self.get_access_token(force_refresh=attempt == 1)
            response = await self._post(
                url, {"access_token": token}, payload
            )
            if int(response.get("errcode", -1)) not in {40014, 42001}:
                return response
            await self._cache.delete(self._token_key)
        return response

    @staticmethod
    def _truncate_utf8(content: str, max_bytes: int) -> str:
        """按 UTF-8 字节上限截断文本，避免切断多字节字符"""
        encoded = content.encode("utf-8")
        if len(encoded) <= max_bytes:
            return content
        return encoded[:max_bytes].decode("utf-8", errors="ignore")

    async def _get(self, url: str, params: dict) -> dict:
        """执行 JSON GET"""
        if self._get_json is not None:
            return await self._get_json(url, params)
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()

    async def _post(self, url: str, params: dict, payload: dict) -> dict:
        """执行 JSON POST"""
        if self._post_json is not None:
            return await self._post_json(url, params, payload)
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, params=params, json=payload)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _ensure_ok(response: dict) -> None:
        """检查企业微信业务 errcode"""
        if int(response.get("errcode", -1)) != 0:
            raise WeComAppApiError(
                f"WeCom API failed: {response.get('errcode')} {response.get('errmsg', '')}"
            )
