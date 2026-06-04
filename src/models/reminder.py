"""
提醒任务 ORM 模型
存储由私聊创建、最终通过企业微信群 webhook 推送的提醒任务和执行记录。

Workflow:
1. ReminderAgent 解析私聊自然语言并写入 Reminder
2. SchedulerManager 周期扫描到期的 Reminder
3. WebhookPushClient 推送群提醒后写入 ReminderRun
4. Reminder 的 last_run_at/next_run_at/status 用于后续查看和取消
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from src.db.base import Base


class Reminder(Base):
    """群 webhook 提醒任务表"""

    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    """自增主键"""

    creator_user_id = Column(String(256), nullable=False, index=True)
    """创建提醒的私聊用户 ID，来自企业微信回调 from.userid"""

    mention_user_id = Column(String(256), nullable=False)
    """群 webhook 中要 @ 的用户 ID，默认等于 creator_user_id，可被配置覆盖"""

    target_name = Column(String(128), nullable=False, index=True)
    """目标 webhook target 名称，对应 SCHEDULER_TARGETS_FILE 中的 name"""

    chat_id = Column(String(256), nullable=True)
    """目标群上下文 ID；为空时由 scheduler 使用 target_name"""

    title = Column(String(256), nullable=False)
    """提醒标题，用于列表展示"""

    message = Column(Text, nullable=False)
    """提醒正文，到点时和 @ 人一起推送到群"""

    schedule_type = Column(String(32), nullable=False)
    """调度类型：once 或 cron"""

    run_at = Column(DateTime, nullable=True)
    """一次性提醒的 UTC 触发时间"""

    cron = Column(String(64), nullable=True)
    """周期性提醒的 crontab 表达式"""

    timezone = Column(String(64), nullable=False, default="Asia/Shanghai")
    """用户表达时间时使用的时区"""

    enabled = Column(Boolean, nullable=False, default=True, index=True)
    """是否启用该提醒"""

    status = Column(String(32), nullable=False, default="scheduled", index=True)
    """状态：scheduled/executed/cancelled/failed"""

    last_run_at = Column(DateTime, nullable=True)
    """最近一次执行时间"""

    next_run_at = Column(DateTime, nullable=True, index=True)
    """下一次 UTC 触发时间；调度器按此字段扫描"""

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    """创建时间"""

    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    """更新时间"""


class ReminderRun(Base):
    """提醒任务执行记录表"""

    __tablename__ = "reminder_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    """自增主键"""

    reminder_id = Column(Integer, nullable=False, index=True)
    """对应 Reminder.id"""

    status = Column(String(32), nullable=False)
    """执行状态：success/failed/skipped"""

    delivered_to = Column(String(128), nullable=False, default="")
    """实际推送到的 webhook target 名称"""

    error_message = Column(Text, nullable=True)
    """失败时记录错误说明"""

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    """执行记录创建时间"""
