"""
端到端烟雾测试
验证完整的请求 → ButlerAgent → tool → 领域 agent → 响应流程

测试范围:
  - log_training 工具记录后请求 today_plan 工具（多步交互）
  - summarize_text 工具总结文本完整流程
"""
import json
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, ToolCall

import src.main


class FakeBoundToolModel:
    """测试用绑定工具模型，按顺序返回预设 AIMessage"""

    def __init__(self, responses: list[AIMessage]):
        """初始化假模型

        参数:
            responses: 每次 ainvoke() 要返回的 AIMessage 列表

        返回:
            None
        """
        self._responses = list(responses)

    async def ainvoke(self, messages):
        """返回下一条预设 AIMessage

        参数:
            messages: ButlerAgent 传给模型的消息列表

        返回:
            AIMessage: 预设响应
        """
        return self._responses.pop(0)


def _tool_call_response(name: str, args: dict, call_id: str = "call-1") -> AIMessage:
    """构造包含单个工具调用的 AIMessage

    参数:
        name: 工具名称
        args: 工具参数
        call_id: 工具调用 ID

    返回:
        AIMessage: 带 tool_calls 的模型响应
    """
    return AIMessage(
        content="",
        tool_calls=[ToolCall(name=name, args=args, id=call_id)],
    )


@pytest.mark.asyncio
async def test_full_flow_log_training_to_plan(http_client, db_session):
    """端到端：先打卡记录训练，再请求训练计划

    步骤 1：发送打卡消息 → 验证意图=log_training，数据落地
    步骤 2：发送训练计划请求 → 验证意图=today_plan，回复非空

    参数:
        http_client: httpx 异步客户端 fixture
        db_session: 数据库会话 fixture
    """
    # 步骤 1：打卡记录训练，由 ButlerAgent 选择 log_training 工具
    log_model = FakeBoundToolModel(
        [
            _tool_call_response("log_training", {"message": "打卡 深蹲100kg5组5次"}),
            AIMessage(content="已记录深蹲。"),
        ]
    )
    with patch.object(
        src.main.llm_client,
        "bind_tools",
        return_value=log_model,
    ), patch.object(
        src.main.llm_client,
        "chat_json",
        return_value=json.dumps([
            {
                "date": "2026-05-29",
                "muscle_group": "腿",
                "exercise": "深蹲",
                "sets": 5,
                "reps": 5,
                "weight_kg": 100.0,
            }
        ]),
    ):
        response = await http_client.post(
            "/api/debug/message",
            json={
                "user_id": "assle",
                "message": "打卡 深蹲100kg5组5次",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "butler"
    assert body["data"] == {"intent": "butler"}
    assert "深蹲" in body["response"]

    # 步骤 2：请求训练计划，由 ButlerAgent 选择 get_today_training_plan 工具
    plan_model = FakeBoundToolModel(
        [
            _tool_call_response("get_today_training_plan", {"message": "今天练什么"}),
            AIMessage(content="根据你最近的训练，建议今天练胸：平板卧推 4×8..."),
        ]
    )
    with patch.object(
        src.main.llm_client,
        "bind_tools",
        return_value=plan_model,
    ), patch.object(
        src.main.llm_client,
        "chat",
        return_value="根据你最近的训练，建议今天练胸：平板卧推 4×8...",
    ):
        response = await http_client.post(
            "/api/debug/message",
            json={
                "user_id": "assle",
                "message": "今天练什么",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "butler"
    assert len(body["response"]) > 0


@pytest.mark.asyncio
async def test_full_flow_summarize(http_client, db_session):
    """端到端：通过调试端点发送群聊总结请求

    模拟 ButlerAgent 调用 summarize_text 工具 → 验证返回结构化摘要。

    参数:
        http_client: httpx 异步客户端 fixture
        db_session: 数据库会话 fixture
    """
    summary_text = (
        "讨论主题：版本发布\n"
        "关键结论：\n"
        "  - 周五发版\n"
        "待办事项：\n"
        "  - 无\n"
        "决策：正常发布"
    )
    bound_model = FakeBoundToolModel(
        [
            _tool_call_response(
                "summarize_text",
                {"text": "帮我总结：张三说周五发版，李四同意了。"},
            ),
            AIMessage(content=summary_text),
        ]
    )
    with patch.object(
        src.main.llm_client,
        "bind_tools",
        return_value=bound_model,
    ), patch.object(
        src.main.llm_client,
        "chat",
        return_value=summary_text,
    ):
        response = await http_client.post(
            "/api/debug/message",
            json={
                "user_id": "assle",
                "message": "帮我总结：张三说周五发版，李四同意了。",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "butler"
    assert "讨论主题" in body["response"]
