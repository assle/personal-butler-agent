"""
研究报告主动私聊投递服务
解析并缓存企微身份映射，独立维护投递状态，失败不回滚研究报告。
"""
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.research import ResearchDelivery, WeComUserBinding
from src.research.schemas import ResearchDeliveryStatus
from src.research.service import ResearchTaskService


class ResearchDeliveryService:
    """研究报告主动投递服务"""

    def __init__(self, task_service: ResearchTaskService, app_client):
        """注入任务服务和企微自建应用客户端"""
        self._tasks = task_service
        self._client = app_client

    async def deliver(self, db: AsyncSession, task_id: str) -> ResearchDelivery:
        """幂等投递报告；失败只更新 delivery 状态"""
        delivery = await db.get(ResearchDelivery, task_id)
        if delivery is None:
            task = await self._tasks.get_task(db, task_id)
            delivery = ResearchDelivery(
                task_id=task_id,
                workspace_id=task.workspace_id,
                status="pending",
            )
            db.add(delivery)
            await db.flush()
        if delivery.status == ResearchDeliveryStatus.DELIVERED.value:
            return delivery

        snapshot = await self._tasks.get_report_snapshot(db, task_id)
        binding = await db.get(WeComUserBinding, snapshot.requester_open_userid)
        if binding is None or binding.status != "active":
            userid = await self._client.convert_open_userid(
                snapshot.requester_open_userid
            )
            binding = WeComUserBinding(
                open_userid=snapshot.requester_open_userid,
                userid=userid,
                status="active",
                converted_at=datetime.now(timezone.utc),
            )
            await db.merge(binding)
        else:
            userid = binding.userid

        delivery.status = ResearchDeliveryStatus.DELIVERING.value
        delivery.recipient_userid = userid
        delivery.attempts += 1
        delivery.error = None
        await db.flush()

        content = (
            f"研究任务 {snapshot.task_id} 已完成\n"
            f"问题：{snapshot.question}\n"
            f"质量状态：{snapshot.quality_status}\n\n"
            f"{snapshot.summary}\n\n"
            "当前为 Phase 1 单次 LLM 初稿，尚未进行多来源检索、逐项引用和独立审核。"
        )
        try:
            delivery.wecom_msgid = await self._client.send_text(userid, content)
        except Exception as exc:
            delivery.status = ResearchDeliveryStatus.FAILED.value
            delivery.error = str(exc)[:1000]
            await db.flush()
            raise

        delivery.status = ResearchDeliveryStatus.DELIVERED.value
        delivery.delivered_at = datetime.now(timezone.utc)
        await db.flush()
        return delivery
