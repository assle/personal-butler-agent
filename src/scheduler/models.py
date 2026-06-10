"""
调度目标数据模型
定义企业微信群 webhook 定时推送所需的结构化配置。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WebhookSchedulerTarget:
    """企业微信群 webhook 定时推送目标"""

    # 目标名称，用于 job id、日志和 agent 上下文，不包含 webhook 密钥
    name: str
    # 当前群的 cron 表达式
    cron: str
    # 企业微信群机器人 webhook 地址，视为敏感信息
    webhook_url: str
    # 到点时使用的固定正文或交给 WebhookComposerAgent 的配置指令
    message: str
    # 推送正文模式；raw 原样发送，compose 交给 WebhookComposerAgent 生成
    mode: str = "compose"
    # 可选天气查询；存在时到点直接查询天气并追加到 message 后
    weather_query: str | None = None
    # 用户可见的群名称，用于私聊确认和提醒列表展示
    display_name: str | None = None
    # 可选群上下文 ID；为空时使用 name
    chat_id: str | None = None
    # 是否启用该目标；配置中可临时关闭单个群
    enabled: bool = True
    # 可选群名别名，用于自然语言目标解析
    aliases: tuple[str, ...] = ()
    # 可选 @ 用户覆盖，解决回调 userid 与 webhook @ userid 不一致的情况
    mention_user_overrides: dict[str, str] | None = None
