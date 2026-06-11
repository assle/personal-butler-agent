"""
Butler Agent 节点函数
实现总控 LLM 调用、初始消息构造和最终回复提取

Workflow:
  build_initial_messages() 生成用户消息 → call_model() 绑定工具并调用 LLM
  → ToolNode 可能追加工具结果 → call_model() 再次生成最终 AIMessage
  → extract_reply() 从消息流中提取最终回复
"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.config import get_config

from src.agents.private_butler.prompts import build_system_prompt


def _recent_message_to_langchain(message: dict):
    """把 ConversationMemory 的字典消息转换为 LangChain 消息

    参数:
        message: 形如 {"role": "...", "content": "..."} 的历史消息字典

    返回:
        HumanMessage | AIMessage: 可传给模型的 LangChain 消息对象
    """
    role = message.get("role")
    content = message.get("content", "")
    if role == "assistant":
        return AIMessage(content=content)
    return HumanMessage(content=content)


async def call_model(state: dict) -> dict:
    """调用支持 tool calling 的 LLM

    参数:
        state: PrivateButlerState 当前状态，包含 messages 和会话记忆字段

    返回:
        dict: {"messages": [AIMessage]}，由 add_messages 合并进状态
    """
    configurable = get_config()["configurable"]
    llm = configurable["llm"]
    tools = configurable["tools"]

    messages = [
        SystemMessage(
            content=build_system_prompt(
                state.get("conversation_summary"),
                state.get("recent_messages", []),
                memory_context=state.get("memory_context", ""),
            )
        )
    ]
    messages.extend(
        _recent_message_to_langchain(message)
        for message in state.get("recent_messages", [])
    )
    messages.extend(state.get("messages", []))

    response = await llm.bind_tools(tools).ainvoke(messages)
    return {"messages": [response]}


async def extract_reply(state: dict) -> dict:
    """提取最后一条不含 tool_calls 的 AIMessage 作为最终回复

    参数:
        state: PrivateButlerState 当前状态，包含完整 messages 列表

    返回:
        dict: {"reply": "..."}，供 PrivateButlerAgent.handle() 包装 AgentResponse
    """
    for message in reversed(state.get("messages", [])):
        if isinstance(message, AIMessage) and not message.tool_calls:
            return {"reply": str(message.content)}
    return {"reply": state.get("reply", "") or "我暂时没有生成有效回复。"}


def build_initial_messages(message: str) -> list:
    """构造 PrivateButlerAgent 初始用户消息

    参数:
        message: 用户原始输入文本

    返回:
        list[HumanMessage]: 初始 messages 列表
    """
    return [HumanMessage(content=message)]
