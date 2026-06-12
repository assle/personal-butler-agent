"""
Butler Agent 状态定义
定义小管家工具调用图在节点之间传递的消息、用户上下文和最终回复字段

Workflow:
  handle() 构造初始 PrivateButlerState → agent 节点追加 AIMessage
  → ToolNode 按需追加 ToolMessage → extract_reply 提取最终回复
"""
from typing import Annotated

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class PrivateButlerState(TypedDict, total=False):
    """PrivateButlerAgent 图状态，所有字段均可按节点需要增量更新"""

    # LangGraph 消息列表，使用 add_messages 合并 Human/AI/Tool 消息
    messages: Annotated[list[AnyMessage], add_messages]
    # 当前用户标识，用于工具运行时上下文和会话记忆
    user_id: str
    # 当前聊天类型，single 表示私聊，group 表示群聊
    chat_type: str
    # 当前群聊或会话标识，私聊时通常为 None
    chat_id: str | None
    # ConversationMemory 读取到的压缩历史摘要
    conversation_summary: str | None
    # ConversationMemory 读取到的最近消息列表
    recent_messages: list[dict]
    # 最终要返回给用户的自然语言回复
    reply: str
    # 图执行过程中的错误信息
    error: str | None
    # 个性化画像上下文，由 handle() 检索并注入
    profile_context: str
