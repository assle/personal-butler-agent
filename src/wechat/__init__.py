"""
企业微信集成模块
提供消息加解密、签名验证、Webhook 推送和回调路由功能

Workflow: crypto.py（加解密）→ messages.py（XML 解析）→ router.py（FastAPI 路由）
         webhook.py（群推送）独立于回调链路
"""
