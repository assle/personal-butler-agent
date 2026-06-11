"""
群聊 @ Agent 节点函数
实现分类、群总结、天气工具调用、简单问答和不支持能力回复。
"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.config import get_config

from src.agents.group_mention.classifier import ALLOWED_CATEGORIES, classify_group_message
from src.agents.group_mention.prompts import GROUP_QA_PROMPT, GROUP_TOOL_PROMPT
from src.agents.translate import translate_text


async def classify_node(state: dict) -> dict:
    """分类群聊 @ 消息

    参数:
        state: 当前图状态

    返回:
        dict: 包含 category 的状态更新
    """
    existing_category = state.get("category")
    if existing_category in ALLOWED_CATEGORIES:
        return {"category": existing_category}

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
    if category in {"summarize_group", "weather", "simple_qa"}:
        return category
    if category in {"poll_create", "poll_vote", "poll_view", "poll_end"}:
        return "poll"
    if category == "translate":
        return "translate"
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


def build_initial_messages(message: str) -> list:
    """构造群聊工具调用初始用户消息

    参数:
        message: 群聊 @ 消息文本

    返回:
        list[HumanMessage]: 初始 messages 列表
    """
    return [HumanMessage(content=message)]


async def call_model_with_tools(state: dict) -> dict:
    """调用支持 tool calling 的 LLM 处理群聊天气问题

    参数:
        state: 当前图状态，包含 messages

    返回:
        dict: {"messages": [AIMessage]}，由 add_messages 合并进状态
    """
    configurable = get_config()["configurable"]
    llm = configurable["llm"]
    tools = configurable["tools"]
    messages = [SystemMessage(content=GROUP_TOOL_PROMPT)]
    messages.extend(state.get("messages", []))
    response = await llm.bind_tools(tools).ainvoke(messages)
    return {"messages": [response]}


async def extract_tool_reply(state: dict) -> dict:
    """提取群聊工具调用后的最终回复

    参数:
        state: 当前图状态，包含完整 messages 列表

    返回:
        dict: {"reply": "..."}，没有最终 AIMessage 时返回兜底提示
    """
    for message in reversed(state.get("messages", [])):
        if isinstance(message, AIMessage) and not message.tool_calls:
            return {"reply": str(message.content)}
    return {"reply": "天气回复生成失败，请稍后再试。"}


async def weather_unavailable_node(state: dict) -> dict:
    """返回天气工具未启用提示

    参数:
        state: 当前图状态

    返回:
        dict: 天气工具不可用回复
    """
    return {"reply": "天气功能已接入工具，但当前没有可用天气数据源。"}


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


async def poll_node(state: dict) -> dict:
    """将投票请求委派给 PollAgent 处理

    参数:
        state: 当前图状态

    返回:
        dict: 回复和数据
    """
    poll_agent = state.get("poll_agent")
    if poll_agent is None:
        return {"reply": "投票功能暂不可用。"}

    category = state.get("category", "")
    intent_map = {
        "poll_create": "create_poll",
        "poll_vote": "cast_vote",
        "poll_view": "view_results",
        "poll_end": "end_poll",
    }
    intent = intent_map.get(category, "view_results")

    result = await poll_agent.handle(
        intent=intent,
        message=state.get("message", ""),
        user_id=state.get("user_id", ""),
        db=state["db"],
        extra_state={
            "chat_type": state.get("chat_type", "group"),
            "chat_id": state.get("chat_id"),
        },
    )
    return {"reply": result.reply, "data": result.data}


async def translate_node(state: dict) -> dict:
    """将翻译请求翻译成目标语言

    参数:
        state: 当前图状态

    返回:
        dict: 包含翻译结果的 reply
    """
    import re

    message = state.get("message", "")
    llm = state["llm"]

    m = re.match(r"翻译(?:成|为|到)?\s*([a-zA-Z一-鿿]+)[：:]\s*(.+)", message, re.DOTALL)
    if m:
        target_lang = m.group(1).strip()
        text = m.group(2).strip()
    else:
        text = re.sub(r"^翻译(?:成|为|到)?\s*", "", message).strip()
        target_lang = "英文"

    reply = await translate_text(text=text, target_lang=target_lang, llm=llm)
    return {"reply": reply}
