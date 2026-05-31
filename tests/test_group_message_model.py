"""
测试企业微信群聊消息 ORM 模型的 CRUD 操作

Workflow:
1. save: 保存消息 → 验证写入成功
2. get_recent: 保存多条消息 → 查询最近 N 条 → 验证顺序和条数限制
3. cleanup: 保存超过上限的消息 → 调用 cleanup → 验证旧消息被删除
4. 多群隔离: 不同 chat_id 的消息互不影响
"""
import pytest

from src.models.group_message import GroupMessage


async def test_save_group_message(db_session):
    """测试保存群聊消息：写入一条消息并验证字段

    输入: chat_id="group_1", user_id="user_001", content="大家好", create_time=1000
    输出: 数据库中存在该消息，各字段值匹配
    """
    msg = await GroupMessage.save(
        db_session,
        chat_id="group_1",
        user_id="user_001",
        content="大家好",
        create_time=1000,
    )

    assert msg.id is not None
    assert msg.chat_id == "group_1"
    assert msg.user_id == "user_001"
    assert msg.content == "大家好"
    assert msg.create_time == 1000
    assert msg.stored_at is not None


async def test_get_recent_returns_messages_in_chronological_order(db_session):
    """测试查询最近消息：返回按时间升序排列的最近 N 条

    输入: 保存 5 条不同时间戳的消息，查询最近 3 条
    输出: 返回时间戳最大的 3 条，且按时间升序排列
    """
    for i, ts in enumerate([100, 200, 300, 400, 500]):
        await GroupMessage.save(
            db_session,
            chat_id="group_1",
            user_id="user_001",
            content=f"消息{i}",
            create_time=ts,
        )

    recent = await GroupMessage.get_recent(db_session, "group_1", limit=3)

    assert len(recent) == 3
    # 返回最近的 3 条，按时间升序
    assert [m.create_time for m in recent] == [300, 400, 500]
    assert [m.content for m in recent] == ["消息2", "消息3", "消息4"]


async def test_get_recent_respects_limit(db_session):
    """测试查询最近消息：结果数不超过 limit

    输入: 保存 10 条消息，limit=5
    输出: 返回 5 条
    """
    for i in range(10):
        await GroupMessage.save(
            db_session,
            chat_id="group_1",
            user_id="user_001",
            content=f"消息{i}",
            create_time=i,
        )

    recent = await GroupMessage.get_recent(db_session, "group_1", limit=5)

    assert len(recent) == 5
    assert [m.create_time for m in recent] == [5, 6, 7, 8, 9]


async def test_cleanup_deletes_old_messages(db_session):
    """测试清理旧消息：超过 keep 条数的旧消息被删除

    输入: 保存 300 条消息，keep=200
    输出: cleanup 后仅保留最近的 200 条
    """
    for i in range(300):
        await GroupMessage.save(
            db_session,
            chat_id="group_1",
            user_id="user_001",
            content=f"消息{i}",
            create_time=i,
        )

    await GroupMessage.cleanup(db_session, "group_1", keep=200)

    recent = await GroupMessage.get_recent(db_session, "group_1", limit=300)
    assert len(recent) == 200
    assert recent[0].create_time == 100
    assert recent[-1].create_time == 299


async def test_multi_group_isolation(db_session):
    """测试多群消息隔离：不同 chat_id 的消息各自独立存储和查询

    输入: 向 group_A 存 3 条消息，向 group_B 存 2 条消息
    输出: get_recent 各自群只返回本群消息
    """
    for i, ts in enumerate([1, 2, 3]):
        await GroupMessage.save(
            db_session, chat_id="group_A", user_id="u1",
            content=f"A消息{i}", create_time=ts,
        )
    for i, ts in enumerate([10, 20]):
        await GroupMessage.save(
            db_session, chat_id="group_B", user_id="u2",
            content=f"B消息{i}", create_time=ts,
        )

    a_msgs = await GroupMessage.get_recent(db_session, "group_A", limit=10)
    b_msgs = await GroupMessage.get_recent(db_session, "group_B", limit=10)

    assert len(a_msgs) == 3
    assert all(m.chat_id == "group_A" for m in a_msgs)
    assert len(b_msgs) == 2
    assert all(m.chat_id == "group_B" for m in b_msgs)


async def test_cleanup_only_affects_target_chat(db_session):
    """测试清理仅影响目标群：清理 group_A 不影响 group_B

    输入: 两个群各保存 10 条消息，清理 group_A
    输出: group_A 的消息不变（小于 keep），group_B 的消息也不变
    """
    for i in range(10):
        await GroupMessage.save(
            db_session, chat_id="group_A", user_id="u1",
            content=f"A{i}", create_time=i,
        )
        await GroupMessage.save(
            db_session, chat_id="group_B", user_id="u2",
            content=f"B{i}", create_time=100 + i,
        )

    await GroupMessage.cleanup(db_session, "group_A", keep=5)

    a_msgs = await GroupMessage.get_recent(db_session, "group_A", limit=20)
    b_msgs = await GroupMessage.get_recent(db_session, "group_B", limit=20)

    assert len(a_msgs) == 5
    assert all(m.chat_id == "group_A" for m in a_msgs)
    assert len(b_msgs) == 10
    assert all(m.chat_id == "group_B" for m in b_msgs)


def test_model_attributes():
    """测试模型基本属性：表名、列名

    输入: 创建 GroupMessage 实例
    输出: __tablename__ 为 "group_messages"，各字段有默认值
    """
    msg = GroupMessage(
        chat_id="g1", user_id="u1", content="hello", create_time=1,
    )
    assert msg.__tablename__ == "group_messages"
    assert msg.chat_id == "g1"
    assert msg.content == "hello"
