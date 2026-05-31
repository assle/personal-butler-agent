"""
Summary Agent 节点函数
每个节点是 StateGraph 中的一个执行单元，负责单一职责

Workflow:
  私聊文本总结: generate_summary → format_summary_response
  群聊消息总结: summarize_group_messages → format_summary_response
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

GROUP_SUMMARY_PROMPT = """你是群聊总结助手。以下是一条一条的群聊消息记录，按时间顺序排列，每条格式为 [发送者]: 内容。
请用以下格式总结群聊讨论：

讨论主题：<一句话概括群聊在讨论什么>
关键结论：
  - <结论1>
  - <结论2>
待办事项：
  - @<发送者> <事项>
决策：<已做出的决策，无则写"无">
未解决的问题：<有分歧或悬而未决的问题，无则写"无">

注意：
- 只总结消息中实际讨论的内容，不要编造信息
- 待办事项中 @后面写消息中的发送者标识
- 如果消息太少无法形成有效总结，如实说明
只返回上述格式，不要有其他说明文字。"""


async def generate_summary(state: dict) -> dict:
    """调用 LLM 将用户提供的文本总结为结构化摘要（私聊场景）

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


async def summarize_group_messages(state: dict) -> dict:
    """从数据库获取群聊最近消息，调用 LLM 生成结构化摘要（群聊场景）

    参数:
        state: 包含 chat_id 的当前状态

    返回:
        dict: {"reply": LLM 生成的结构化摘要} 或 {"reply": 错误提示, "error": ...}
    """
    config = get_config()
    llm = config["configurable"]["llm"]
    db = config["configurable"]["db"]
    chat_id = state.get("chat_id", "")

    # 从数据库获取最近 50 条群聊消息
    from src.models.group_message import GroupMessage
    messages = await GroupMessage.get_recent(db, chat_id, limit=50)

    if not messages:
        return {"reply": "暂无最近的群聊消息可供总结，请先在群里聊几句吧。"}

    # 构建对话记录文本
    transcript_lines = []
    for msg in messages:
        transcript_lines.append(f"[{msg.user_id}]: {msg.content}")
    transcript = "\n".join(transcript_lines)

    # 调用 LLM 总结
    try:
        reply = await llm.chat(
            messages=[
                {"role": "system", "content": GROUP_SUMMARY_PROMPT},
                {"role": "user", "content": f"以下是最新的群聊记录，按时间排列，请总结：\n\n{transcript}"},
            ],
        )
        return {"reply": reply}
    except Exception as e:
        return {"reply": f"生成群聊总结失败：{e}", "error": str(e)}


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
