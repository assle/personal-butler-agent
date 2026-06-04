"""
群聊 @ Agent 节点函数
实现分类、群总结、天气占位、简单问答和不支持能力回复。
"""
from src.agents.group_mention.classifier import classify_group_message
from src.agents.group_mention.prompts import GROUP_QA_PROMPT


async def classify_node(state: dict) -> dict:
    """分类群聊 @ 消息

    参数:
        state: 当前图状态

    返回:
        dict: 包含 category 的状态更新
    """
    llm = state["llm"]
    category = await classify_group_message(state.get("message", ""), llm)
    return {"category": category}


def route_by_category(state: dict) -> str:
    """根据分类结果选择下一个节点

    参数:
        state: 当前图状态

    返回:
        str: 下一个节点名
    """
    category = state.get("category", "unsupported")
    if category in {"summarize_group", "weather_placeholder", "simple_qa"}:
        return category
    return "unsupported"


async def summarize_group_node(state: dict) -> dict:
    """调用 SummaryAgent 总结当前群聊

    参数:
        state: 当前图状态

    返回:
        dict: 回复和数据
    """
    result = await state["summary_agent"].handle(
        "summarize_group",
        state.get("message", ""),
        state.get("user_id", ""),
        state["db"],
        extra_state={
            "chat_type": state.get("chat_type", "group"),
            "chat_id": state.get("chat_id"),
        },
    )
    return {"reply": result.reply, "data": result.data}


async def weather_placeholder_node(state: dict) -> dict:
    """返回天气功能待配置提示

    参数:
        state: 当前图状态

    返回:
        dict: 天气占位回复
    """
    return {"reply": "天气功能还没有接入数据源，配置完成后我就能查询。"}


async def simple_qa_node(state: dict) -> dict:
    """生成群聊简单问答回复

    参数:
        state: 当前图状态

    返回:
        dict: 简单问答回复
    """
    reply = await state["llm"].chat(
        messages=[
            {"role": "system", "content": GROUP_QA_PROMPT},
            {"role": "user", "content": state.get("message", "")},
        ]
    )
    return {"reply": reply}


async def unsupported_node(state: dict) -> dict:
    """返回群聊不支持能力的短提示

    参数:
        state: 当前图状态

    返回:
        dict: 不支持能力回复
    """
    return {"reply": "群聊里我只处理总结、天气和简单问答，训练和食谱请私聊我。"}
