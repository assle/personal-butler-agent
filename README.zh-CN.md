# Personal Butler Agent

当前中文说明以 [README.md](README.md) 为准。

旧的企业微信自建应用回调入口 `/api/wechat/callback`、`WECHAT_TOKEN`、`WECHAT_ENCODING_AES_KEY` 已删除。

当前只使用企业微信智能机器人 URL 回调：

```text
https://<你的域名>/api/wechat/aibot/callback
```

核心配置：

```env
WECOM_AIBOT_BOT_ID=bot-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WECOM_AIBOT_TOKEN=your-callback-token
WECOM_AIBOT_ENCODING_AES_KEY=your-43-char-encoding-aes-key
```
