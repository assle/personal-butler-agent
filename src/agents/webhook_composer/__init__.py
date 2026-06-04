"""
群 webhook 定时推送正文生成 agent
只负责根据配置指令生成最终 markdown 正文。
"""
from src.agents.webhook_composer.graph import WebhookComposerAgent

__all__ = ["WebhookComposerAgent"]
