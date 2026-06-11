"""
群 webhook 注册表 ORM 模型
存储群聊 chat_id 到企业微信群机器人 webhook URL 的映射。

Workflow:
1. 管理员通过私聊或直接写库注册群 webhook
2. PollAgent 到期推送时通过 chat_id 查找 webhook_url
3. 后续可替换或补充现有的 SCHEDULER_TARGETS_FILE 静态配置
"""
from sqlalchemy import Column, String

from src.db.base import Base


class GroupWebhook(Base):
    """群 webhook 注册表"""

    __tablename__ = "group_webhooks"

    chat_id = Column(String(256), primary_key=True)
    """群聊 ID，对应企业微信回调 chatid"""

    webhook_url = Column(String(1024), nullable=False)
    """企业微信群机器人 webhook 地址"""

    display_name = Column(String(256), nullable=True)
    """用户可见的群名称，用于展示"""
