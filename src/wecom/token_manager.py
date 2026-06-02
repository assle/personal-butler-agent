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
