"""安全研究网页抓取"""
import logging
import httpx
from src.research.web.url_policy import UrlPolicy

logger = logging.getLogger(__name__)

class FetchExceededLimitError(RuntimeError): pass
class FetchBlockedError(RuntimeError): pass

class SecuredFetcher:
    def __init__(self, *, max_bytes: int = 2_000_000, timeout: int = 15, max_redirects: int = 5):
        self._max_bytes = max_bytes
        self._timeout = timeout
        self._max_redirects = max_redirects
        self._policy = UrlPolicy()

    async def fetch(self, url: str) -> str:
        validated = await self._policy.validate(url)
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as client:
            current_url = validated.url
            for _ in range(self._max_redirects + 1):
                response = await client.get(current_url)
                if response.status_code in (301, 302, 303, 307, 308):
                    current_url = response.headers.get("location", "")
                    if not current_url:
                        raise FetchBlockedError("重定向缺少 Location")
                    await self._policy.validate(current_url)
                    continue
                if response.status_code >= 400:
                    raise FetchBlockedError(f"HTTP {response.status_code}")
                content_type = response.headers.get("content-type", "")
                if "text/html" not in content_type and "text/plain" not in content_type:
                    raise FetchBlockedError(f"不支持的内容类型: {content_type}")
                content = response.text[:self._max_bytes]
                if len(response.content) > self._max_bytes:
                    logger.warning("Fetch: response truncated for %s", url)
                return content
        raise FetchBlockedError(f"超过最大重定向次数: {self._max_redirects}")
