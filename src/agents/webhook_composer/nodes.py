"""
Webhook 内容生成节点函数
调用 LLM 将配置指令转换成最终群 markdown 正文，必要时支持天气工具调用。
"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.config import get_config

from src.agents.webhook_composer.prompts import WEBHOOK_COMPOSER_PROMPT


async def compose_webhook_body(state: dict) -> dict:
    """生成 webhook 推送正文

    参数:
        state: 当前图状态，包含 llm 和 message

    返回:
        dict: 包含 reply 的状态更新
    """
    message = state.get("message", "")
    reply = await state["llm"].chat(
        messages=[
            {"role": "system", "content": WEBHOOK_COMPOSER_PROMPT},
            {"role": "user", "content": f"配置指令：{message}"},
        ]
    )
    return {"reply": reply.strip() or message}


def build_initial_messages(message: str) -> list:
    """构造 WebhookComposerAgent 初始用户消息

    参数:
        message: scheduler target 中配置的推送指令

    返回:
        list[HumanMessage]: 初始 messages 列表
    """
    return [HumanMessage(content=f"配置指令：{message}")]


async def call_model_with_tools(state: dict) -> dict:
    """调用支持 tool calling 的 LLM 生成推送正文或工具请求

    参数:
        state: 当前图状态，包含 messages

    返回:
        dict: {"messages": [AIMessage]}，由 add_messages 合并进状态
    """
    configurable = get_config()["configurable"]
    llm = configurable["llm"]
    tools = configurable["tools"]
    messages = [SystemMessage(content=WEBHOOK_COMPOSER_PROMPT)]
    messages.extend(state.get("messages", []))
    response = await llm.bind_tools(tools).ainvoke(messages)
    return {"messages": [response]}


async def extract_reply(state: dict) -> dict:
    """提取最终 markdown 正文

    参数:
        state: 当前图状态，包含完整 messages 列表和原始 message

    返回:
        dict: {"reply": "..."}，空结果时回退到原始配置指令
    """
    for message in reversed(state.get("messages", [])):
        if isinstance(message, AIMessage) and not message.tool_calls:
            return {"reply": str(message.content).strip() or state.get("message", "")}
    return {"reply": state.get("reply", "") or state.get("message", "")}
