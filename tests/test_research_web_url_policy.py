"""URL 安全策略测试"""
import pytest
from src.research.web.url_policy import UnsafeUrlError, UrlPolicy

@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.com/a",
    "http://127.0.0.1/admin", "http://169.254.169.254/latest",
])
@pytest.mark.asyncio
async def test_url_policy_blocks_unsafe_targets(url):
    with pytest.raises(UnsafeUrlError):
        await UrlPolicy().validate(url)

@pytest.mark.asyncio
async def test_url_policy_allows_safe_url():
    # This test may need DNS resolution; skip gracefully if offline
    try:
        result = await UrlPolicy().validate("https://example.com")
        assert result.host == "example.com"
    except UnsafeUrlError as e:
        if "无法解析" in str(e):
            pytest.skip("DNS not available")
        raise
