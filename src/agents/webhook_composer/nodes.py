"""
Webhook 内容生成节点函数
调用 LLM 将配置指令转换成最终群 markdown 正文。
"""
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
