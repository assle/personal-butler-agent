"""
Summary Agent 节点函数
每个节点是 StateGraph 中的一个执行单元，负责单一职责

Workflow:
  generate_summary → format_summary_response
  不访问数据库，直接将用户提供的群聊文本投喂给 LLM 做总结
"""
from langgraph.config import get_config

SUMMARY_PROMPT = """你是群聊总结助手。用以下格式总结用户提供的聊天记录：

讨论主题：<一句话概括>
关键结论：
  - <结论1>
  - <结论2>
待办事项：
  - @<负责人> <事项>
决策：<已做出的决策，无则写"无">

只返回上述格式，不要有其他说明文字。"""


async def generate_summary(state: dict) -> dict:
    """调用 LLM 将群聊文本总结为结构化摘要

    参数:
        state: 包含 message（待总结文本）的当前状态

    返回:
        dict: {"reply": LLM 生成的结构化摘要} 或 {"error": 错误信息}
    """
    config = get_config()
    llm = config["configurable"]["llm"]
    try:
        reply = await llm.chat(
            messages=[
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": state["message"]},
            ],
        )
        return {"reply": reply}
    except Exception as e:
        return {"error": str(e)}


async def format_summary_response(state: dict) -> dict:
    """格式化摘要输出

    参数:
        state: 包含 reply 或 error 的当前状态

    返回:
        dict: {"reply": 格式化后的摘要文本或错误提示}
    """
    if state.get("error"):
        return {"reply": f"生成总结失败：{state['error']}"}
    return {"reply": state.get("reply", "")}
