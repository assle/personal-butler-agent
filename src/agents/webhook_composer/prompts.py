"""
Webhook 内容生成提示词
约束模型只生成即将发送到群 webhook 的 markdown 正文。
"""

WEBHOOK_COMPOSER_PROMPT = """这是 APScheduler 定时群 webhook 推送任务。

系统会负责通过企业微信群 webhook 自动发送，你只生成最终要发到群里的 markdown 正文。

规则：
- 不要解释执行方式。
- 不要说自己没有群发权限。
- 不要给用户手动复制粘贴步骤。
- 不要调用或假装调用训练、食谱、问答、天气、群总结能力。
- 正文应适合直接作为企业微信群 markdown 发送。
"""
