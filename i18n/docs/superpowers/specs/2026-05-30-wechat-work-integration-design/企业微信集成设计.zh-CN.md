# WeChat Work Integration Design

## Overview

Integrate the Personal Butler Agent with WeChat Work (企业微信) via two channels:
1. **Self-built app callback** — users send messages in WeChat Work, the app receives and replies through the existing intent → agent pipeline.
2. **Group bot webhook push** — the app can proactively push text/markdown messages to group chats.

Scheduled push (APScheduler) is deferred to a separate feature round.

## Prerequisites

### WeChat Work Admin Panel Setup (Step-by-Step)

1. **Create a self-built app**:
   - Go to [WeChat Work Admin Console](https://work.weixin.qq.com/wework_admin/frame#apps)
   - Click "Create Application" (创建应用)
   - Fill in application name, description, and upload an icon
   - After creation, note down **AgentId** (应用 AgentId)

2. **Get CorpID**:
   - Go to "My Enterprise" (我的企业) → "Enterprise Info" (企业信息)
   - Copy the **CorpID**

3. **Configure callback URL**:
   - In the app settings page, find "Receive Messages" (接收消息) section
   - Set callback URL: `https://<your-domain>/api/wechat/callback`
   - Randomly generate **Token** (3-32 chars, letters/numbers) and **EncodingAESKey** (43 chars, letters/numbers) — save these
   - The URL verification will fail initially (the server must be running first)

4. **Get group bot webhook**:
   - In the target group chat, click "..." → "Add Group Robot" (添加群机器人)
   - Give the bot a name
   - Copy the **webhook URL**

### Local Development

Use a tunnel (ngrok, frp, cloudflare tunnel) to expose `localhost:8000` to the internet for callback testing:
```bash
ngrok http 8000
# Then set callback URL to: https://<ngrok-subdomain>.ngrok-free.dev/api/wechat/callback
```

## Configuration

New settings in `src/config.py` (`.env`):

| Variable | Required | Purpose |
|----------|----------|---------|
| `WECHAT_CORP_ID` | yes (for callback) | Enterprise CorpID |
| `WECHAT_TOKEN` | yes (for callback) | Callback URL verification token |
| `WECHAT_ENCODING_AES_KEY` | yes (for callback) | AES key for message encryption |
| `WECHAT_AGENT_ID` | no | Application AgentId for response |
| `WECHAT_WEBHOOK_URL` | yes (for push) | Group bot webhook URL |

All empty by default. The wechat router only registers when `WECHAT_CORP_ID` and `WECHAT_TOKEN` are set, so the app runs without WeChat config in local debug mode.

## Module Structure

```
src/wechat/
├── __init__.py          # Re-exports: WechatCrypto, WechatRouter, WechatWebhookClient
├── crypto.py            # AES-256-CBC encrypt/decrypt, SHA1 signature verification
├── messages.py          # XML parsing and construction
├── webhook.py           # Group bot HTTP push client
└── router.py            # FastAPI router factory: GET/POST /api/wechat/callback
```

Dependency flow:
```
crypto.py   ← stdlib only (hashlib, base64, struct)
messages.py ← crypto.py (for decrypt)
webhook.py  ← httpx (already in FastAPI ecosystem)
router.py   ← crypto.py, messages.py, intent_router, agent_registry
```

## Component Details

### `crypto.py`

Pure functions, no project dependencies:

```python
def verify_signature(token: str, timestamp: str, nonce: str,
                     msg_encrypt: str, msg_signature: str) -> bool
    # SHA1(sort([token, timestamp, nonce, msg])) == msg_signature

def decrypt(encoding_aes_key: str, msg_encrypt: str, corp_id: str) -> str
    # Base64 decode AES key → AES-256-CBC decrypt → strip PKCS#7 padding
    # → strip 16-byte random prefix → read 4-byte big-endian length
    # → extract plaintext → verify trailing CorpID → return plaintext

def encrypt(encoding_aes_key: str, msg: str, corp_id: str) -> str
    # 16-byte random + 4-byte len(network order) + msg + corp_id
    # → PKCS#7 pad → AES-256-CBC encrypt → Base64 encode
```

Uses `cryptography` library for AES (CBC mode) — it has built-in PKCS#7 padding.

Custom exceptions: `SignatureError`, `DecryptError`, `CorpIDMismatch`.

### `messages.py`

Dataclasses for parsed messages, plus parse/construct functions:

```python
@dataclass
class EncryptedMessage:
    to_user_name: str
    agent_id: str
    encrypt: str

@dataclass
class InnerMessage:
    to_user_name: str
    from_user_name: str    # This becomes user_id in our pipeline
    create_time: int
    msg_type: str          # "text" (others ignored for now)
    content: str
    msg_id: str

def parse_encrypted_xml(body: bytes) -> EncryptedMessage
def parse_inner_xml(decrypted: str) -> InnerMessage
def build_reply_xml(to_user: str, from_user: str, content: str) -> str
def build_encrypted_reply_xml(encrypt: str, ...) -> str
```

Non-text message types (image, voice, etc.) → reply with "暂不支持该消息类型" (message type not supported).

### `webhook.py`

Simple HTTP client for group bot pushes:

```python
class WechatWebhookClient:
    def __init__(self, webhook_url: str, client: httpx.AsyncClient | None = None)
    async def send_text(self, content: str) -> bool
    async def send_markdown(self, content: str) -> bool
```

POSTs JSON to the webhook URL. Returns `True` on `errcode == 0`.

Accepts an optional `httpx.AsyncClient` for connection reuse and test injection.

### `router.py`

Factory function creating a FastAPI router:

```python
def create_wechat_router(
    intent_router: IntentRouter,
    agent_registry: AgentRegistry,
    corp_id: str,
    token: str,
    encoding_aes_key: str,
) -> APIRouter:
```

**GET `/api/wechat/callback`** — URL verification:
1. `verify_signature(token, timestamp, nonce, echostr, msg_signature)` → 403 if invalid
2. `decrypt(encoding_aes_key, echostr, corp_id)` → 200 plaintext on success

**POST `/api/wechat/callback`** — Message reception:
1. Parse encrypted XML from body
2. `decrypt()` → `parse_inner_xml()` → extract `from_user_name`, `content`
3. Run existing pipeline: `intent_router.route(content)` → `agent_registry.get(intent)` → `agent.handle()`
4. Build inner reply XML → `encrypt()` → wrap in outer encrypted XML → 200 XML response

Error handling:
- Signature mismatch → 403
- Decrypt/parse failure → 200 with "success" plaintext (WeChat Work protocol convention: return 200 even on failures to prevent retry storms, log the error server-side)
- Agent APIError → reply with encrypted error message "LLM 服务暂时不可用，请稍后重试。" to the user
- Non-text messages → reply "暂不支持该消息类型"

## Wiring in `main.py`

```python
# Conditional wechat router registration
if settings.wechat_corp_id and settings.wechat_token:
    wechat_router = create_wechat_router(
        intent_router=intent_router,
        agent_registry=agent_registry,
        ...
    )
    app.include_router(wechat_router)

# Webhook client (always created if URL is set)
if settings.wechat_webhook_url:
    webhook_client = WechatWebhookClient(settings.wechat_webhook_url)
```

The debug endpoint remains untouched.

## Reply Timing

WeChat Work expects the callback response within 5 seconds. DeepSeek LLM calls can take 2-8 seconds. For the MVP:
- The HTTP response is blocked on agent completion (acceptable for reasonable LLM latencies)
- A comment in the code notes that if latency becomes a problem, the reply can be offloaded to the WeChat Work "customer service message" (客服消息) API asynchronously

This is an explicit scope trade-off — not worth building async push-reply until we see actual latency issues.

## Testing Strategy

- `crypto.py`: unit tests with known WeChat Work test vectors (verifiable against WeChat Work's official encryption library)
- `messages.py`: unit tests with sample XML fixtures
- `webhook.py`: unit tests with mocked httpx
- `router.py`: integration tests using `httpx.AsyncClient` against the FastAPI `TestClient`
- All tests use `DEEPSEEK_API_KEY=test` — no real LLM calls
- No changes to existing agent/route/intent tests

## What's Not In Scope

- APScheduler-based timed push (separate feature round)
- WeChat Work "customer service message" API for async reply
- Multi-message type support (image, voice, etc.)
- WeChat Work OAuth login / user identity mapping
- Ocr / media handling
