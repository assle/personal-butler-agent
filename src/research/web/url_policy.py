"""研究网页 URL 安全策略"""
import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}
BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"), ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"), ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"), ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("fc00::/7"), ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::1/128"),
]

class UnsafeUrlError(ValueError):
    """URL 安全策略拒绝"""

class ValidatedUrl:
    def __init__(self, url: str, host: str):
        self.url = url
        self.host = host

class UrlPolicy:
    async def validate(self, url: str) -> ValidatedUrl:
        parsed = urlparse(url)
        if parsed.scheme not in ALLOWED_SCHEMES:
            raise UnsafeUrlError(f"不允许的协议: {parsed.scheme}")
        if parsed.username or parsed.password:
            raise UnsafeUrlError("URL 不能包含凭据")
        host = parsed.hostname
        if not host:
            raise UnsafeUrlError("缺少主机名")
        try:
            addr = ipaddress.ip_address(host)
        except ValueError:
            try:
                addrs = await asyncio.to_thread(socket.getaddrinfo, host, None)
                addr = ipaddress.ip_address(addrs[0][4][0])
            except Exception:
                raise UnsafeUrlError(f"无法解析主机: {host}")
        for net in BLOCKED_NETWORKS:
            if addr in net:
                raise UnsafeUrlError(f"主机 {host} 解析到受限地址")
        return ValidatedUrl(url, host)
