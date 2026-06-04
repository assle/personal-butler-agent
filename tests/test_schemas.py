"""
Schema 模块测试
验证 AgentResponse 的基础结构。
"""


def test_agent_response_data_optional():
    """验证 AgentResponse 的 data 字段可选"""
    from src.schemas.response import AgentResponse

    resp = AgentResponse(reply="Hello")

    assert resp.reply == "Hello"
    assert resp.data is None


def test_agent_response_accepts_data():
    """验证 AgentResponse 可以携带结构化数据"""
    from src.schemas.response import AgentResponse

    resp = AgentResponse(reply="Done", data={"intent": "private_butler"})

    assert resp.reply == "Done"
    assert resp.data == {"intent": "private_butler"}
