"""
研究任务 Taskiq broker
使用 Redis Stream 提供消息确认，生产者和 Worker 共享此 broker 实例定义。
"""
from taskiq_redis import RedisStreamBroker

from src.config import settings


broker = RedisStreamBroker(
    url=settings.redis_url,
    queue_name=settings.research_queue_name,
)
"""研究任务 Redis Stream broker；业务结果不写 Taskiq result backend"""
