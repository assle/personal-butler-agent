"""
测试企业微信群机器人 Webhook 推送

Workflow:
1. send_text: POST text 类型消息到 webhook URL → 检查 errcode
2. send_markdown: POST markdown 类型消息到 webhook URL → 检查 errcode
3. 处理 errcode != 0 的失败响应
4. 处理网络异常
"""
import pytest
from unittest.mock import AsyncMock, Mock

from src.wechat.webhook import WechatWebhookClient


@pytest.fixture
def mock_http_client():
    """创建 mock httpx.AsyncClient，用于测试中注入 WebhookClient"""
    client = AsyncMock()
    return client


@pytest.fixture
def webhook_client(mock_http_client):
    """创建 WechatWebhookClient，注入 mock HTTP client

    输入: mock_http_client
    输出: WechatWebhookClient 实例，后续调用使用注入的 mock
    """
    return WechatWebhookClient(
        webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test",
        client=mock_http_client,
    )


async def test_send_text_success(webhook_client, mock_http_client):
    """测试发送文本消息成功：POST 正确 JSON，errcode=0 返回 True

    输入: content="测试推送消息"
    输出: True + 验证 POST 的 JSON 格式正确
    """
    mock_resp = Mock()
    mock_resp.json.return_value = {"errcode": 0, "errmsg": "ok"}
    mock_http_client.post.return_value = mock_resp

    result = await webhook_client.send_text("测试推送消息")

    assert result is True
    call_args = mock_http_client.post.call_args
    assert call_args.kwargs["json"] == {
        "msgtype": "text",
        "text": {"content": "测试推送消息"},
    }


async def test_send_markdown_success(webhook_client, mock_http_client):
    """测试发送 Markdown 消息成功：POST 正确 JSON，errcode=0 返回 True

    输入: content="# 标题\n内容"
    输出: True + 验证 POST 的 JSON 格式为 markdown 类型
    """
    mock_resp = Mock()
    mock_resp.json.return_value = {"errcode": 0, "errmsg": "ok"}
    mock_http_client.post.return_value = mock_resp

    result = await webhook_client.send_markdown("# 标题\n内容")

    assert result is True
    call_args = mock_http_client.post.call_args
    assert call_args.kwargs["json"] == {
        "msgtype": "markdown",
        "markdown": {"content": "# 标题\n内容"},
    }


async def test_send_text_failure(webhook_client, mock_http_client):
    """测试发送失败：errcode != 0 返回 False

    输入: content="测试" + mock 返回 errcode=40001
    输出: False
    """
    mock_resp = Mock()
    mock_resp.json.return_value = {"errcode": 40001, "errmsg": "invalid url"}
    mock_http_client.post.return_value = mock_resp

    result = await webhook_client.send_text("测试")

    assert result is False


async def test_send_text_network_error(webhook_client, mock_http_client):
    """测试网络异常：抛出异常时返回 False

    输入: content="测试" + mock 抛出 Connection refused
    输出: False
    """
    mock_http_client.post.side_effect = Exception("Connection refused")

    result = await webhook_client.send_text("测试")

    assert result is False
