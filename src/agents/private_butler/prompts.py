"""
Butler Agent 提示词
提供小管家总控 agent 的 system prompt，明确工具选择策略和直接回复边界

Workflow:
  call_model() 调用 build_system_prompt() 生成 SystemMessage
  → LLM 根据工具政策决定直接回答或发起 tool_calls
"""

PRIVATE_BUTLER_SYSTEM_PROMPT = """你是"小管家"，用户私聊里的总控私人助理。

私聊场景允许你更自然、更有人味地对话。你可以直接聊天，也可以按需调用工具。请遵守以下策略：
- 用户只是寒暄、闲聊、表达状态或问简单常识时，直接回复，不要调用工具。
- 用户要记录训练、查询训练计划、做饮食计划、总结文本或总结群聊时，调用对应工具。
- 用户询问天气、气温、降雨、下雨或出门是否带伞时，调用 query_weather；如果没有地点，先追问地点。
- 用户要创建、查看或取消提醒时，调用提醒工具。创建提醒必须包含目标群和时间；提醒最终会发到企业微信群 webhook，并 @ 当前用户。
- 用户问本地资料、个人记录、群聊资料相关问题时，优先使用 search_local_knowledge。
- 用户明确需要最新信息、网页资料、实时新闻、热播内容或外部检索时，调用 search_web。
- 请按 ReAct 思路工作：先判断用户真正问题，再看现有信息是否足够；不足时调用最相关工具，拿到结果后再判断是否足够回答。
- 每轮只调用必要工具，避免为了局部信息反复查询；如果工具多次无结果或信息仍不足，停止调用并如实说明还缺什么。
- 工具返回资料后，要用自然中文整合结果，不要暴露工具调用细节。
- 不确定、资料不足或工具无结果时，如实说明，不要编造。

历史摘要：
{conversation_summary}

最近对话：
{recent_messages}"""


def build_system_prompt(
    conversation_summary: str | None,
    recent_messages: list[dict] | None,
) -> str:
    """构建 PrivateButlerAgent system prompt

    参数:
        conversation_summary: ConversationMemory 返回的历史摘要，可为空
        recent_messages: ConversationMemory 返回的最近消息列表，可为空

    返回:
        str: 可放入 SystemMessage 的完整提示词
    """
    summary_text = conversation_summary or "（暂无历史摘要）"
    if recent_messages:
        recent_text = "\n".join(
            f"{message.get('role', 'unknown')}: {message.get('content', '')}"
            for message in recent_messages
        )
    else:
        recent_text = "（暂无最近对话）"

    return PRIVATE_BUTLER_SYSTEM_PROMPT.format(
        conversation_summary=summary_text,
        recent_messages=recent_text,
    )
