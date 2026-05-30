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
    if state.get("error"):
        return {"reply": f"生成总结失败：{state['error']}"}
    return {"reply": state.get("reply", "")}
