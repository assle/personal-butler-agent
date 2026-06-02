"""
WeComUser ORM 模型测试
验证表结构创建、字段唯一约束、is_fresh 缓存判断
"""
import pytest
from sqlalchemy.exc import IntegrityError
from src.models.wecom_user import WeComUser


@pytest.mark.asyncio
async def test_create_wecom_user(db_session):
    """测试创建 WeComUser 记录并查询"""
    user = WeComUser(userid="zhangsan", name="张三")
    db_session.add(user)
    await db_session.flush()

    from sqlalchemy import select
    result = await db_session.execute(
        select(WeComUser).where(WeComUser.userid == "zhangsan")
    )
    found = result.scalar_one()
    assert found.name == "张三"
    assert found.userid == "zhangsan"
    assert found.last_synced_at is not None


@pytest.mark.asyncio
async def test_wecom_user_unique_constraint(db_session):
    """测试 userid 唯一约束"""
    user1 = WeComUser(userid="zhangsan", name="张三")
    db_session.add(user1)
    await db_session.flush()

    user2 = WeComUser(userid="zhangsan", name="张三副本")
    db_session.add(user2)
    with pytest.raises(IntegrityError):
        await db_session.flush()


def test_is_fresh_recent():
    """测试最近时间的 is_fresh 返回 True"""
    assert WeComUser.is_fresh("2026-06-02T10:00:00+00:00") is True


def test_is_fresh_old():
    """测试超过 24h 的 is_fresh 返回 False"""
    assert WeComUser.is_fresh("2020-01-01T00:00:00+00:00") is False


def test_is_fresh_invalid():
    """测试无效时间字符串返回 False"""
    assert WeComUser.is_fresh("not-a-date") is False
