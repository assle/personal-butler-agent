# WeCom Custom-App Callback Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an isolated encrypted WeChat Work custom-application callback endpoint that verifies the receive-server URL without changing research-result delivery behavior.

**Architecture:** Reuse `WeComCallbackCrypto` for signature, AES, and CorpID validation. Add a focused router with GET verification and POST validation-only handling, register it conditionally in `src/main.py`, and keep all AIBot and research-delivery code paths unchanged.

**Tech Stack:** Python 3.13, FastAPI, cryptography, Pydantic Settings, httpx ASGITransport, pytest.

---

### Task 1: Add Callback Configuration

**Files:**
- Modify: `src/config.py`
- Modify: `.env.example`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing configuration tests**

Add assertions that `WECOM_APP_CALLBACK_TOKEN` and
`WECOM_APP_CALLBACK_ENCODING_AES_KEY` load independently from the active
delivery credentials and default to empty strings.

- [ ] **Step 2: Verify the tests fail**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_config.py -q
```

Expected: failures because the callback settings do not exist.

- [ ] **Step 3: Add the settings**

Add:

```python
wecom_app_callback_token: str = ""
wecom_app_callback_encoding_aes_key: str = ""
```

Add matching empty entries and comments to `.env.example`.

- [ ] **Step 4: Verify the tests pass**

Run the same focused pytest command and expect all tests to pass.

### Task 2: Add the Validation-Only Router

**Files:**
- Create: `src/wechat/app_callback_router.py`
- Create: `tests/test_wecom_app_callback.py`
- Modify: `src/wechat/__init__.py`

- [ ] **Step 1: Write failing GET tests**

Use `WeComCallbackCrypto(token, key, corp_id).encrypt()` to create a valid
`echostr`. Assert GET returns the plaintext, invalid signatures return 403, and
a mismatched CorpID returns 403.

- [ ] **Step 2: Write failing POST tests**

Encrypt a minimal XML message, wrap the ciphertext in both XML and JSON request
bodies, and assert POST returns plaintext `success`. Assert missing encryption
returns 400 and invalid signatures return 403.

- [ ] **Step 3: Verify the router tests fail**

Run:

```bash
DEEPSEEK_API_KEY=test uv run pytest tests/test_wecom_app_callback.py -q
```

Expected: import failure because the router does not exist.

- [ ] **Step 4: Implement the router**

Create:

```python
def create_app_callback_router(
    token: str,
    encoding_aes_key: str,
    corp_id: str,
) -> APIRouter:
    ...
```

The router uses prefix `/api/wechat/app`. GET decrypts and returns `echostr`.
POST parses XML/JSON, requires `Encrypt`/`encrypt`, verifies and decrypts it,
validates that plaintext is XML or JSON, and returns `success` without business
processing.

- [ ] **Step 5: Verify the router tests pass**

Run the focused router tests and expect all tests to pass.

### Task 3: Register the Route

**Files:**
- Modify: `src/main.py`
- Modify: `tests/test_smoke.py`

- [ ] **Step 1: Write a failing registration test**

Construct an isolated FastAPI app with the router factory or reload main under
callback settings, then assert `/api/wechat/app/callback` is present only when
CorpID, callback Token, and callback EncodingAESKey are configured.

- [ ] **Step 2: Register conditionally**

In `src/main.py`, include the router when all three callback values are
non-empty. Do not require `RESEARCH_ENABLED=true` and do not alter the existing
custom-app delivery validation.

- [ ] **Step 3: Run callback and smoke tests**

```bash
DEEPSEEK_API_KEY=test RESEARCH_ENABLED=false uv run pytest \
  tests/test_wecom_app_callback.py tests/test_smoke.py -q
```

Expected: all tests pass.

### Task 4: Document Administrator Setup

**Files:**
- Modify: `docs/agent/active-context.md`
- Modify: `docs/agent/config-variables.md`
- Modify: `deployment.md`
- Modify: `deployment.en.md`
- Modify: `docs/agent/troubleshooting.md`

- [ ] **Step 1: Document environment values**

Document the two new callback variables separately from `WECOM_APP_SECRET`.

- [ ] **Step 2: Document the ZeroNews URL**

Use:

```text
https://<ZeroNews 公网 HTTPS 地址>/api/wechat/app/callback
```

Explain that successful URL verification unlocks trusted-IP configuration, and
that the Worker egress IP must then be added before retrying delivery.

- [ ] **Step 3: Update architecture context**

Add the custom-app validation-only callback to current interfaces and explicitly
state that research delivery remains proactive private delivery to the task
requester.

### Task 5: Verify End to End

**Files:**
- Verify all modified files

- [ ] **Step 1: Run focused tests**

```bash
DEEPSEEK_API_KEY=test RESEARCH_ENABLED=false uv run pytest \
  tests/test_config.py tests/test_wecom_app_callback.py tests/test_smoke.py -q
```

- [ ] **Step 2: Run the full suite**

```bash
DEEPSEEK_API_KEY=test RESEARCH_ENABLED=false uv run pytest -q
```

- [ ] **Step 3: Check formatting and route behavior**

```bash
git diff --check
```

Use an ASGI encrypted GET and POST request to verify plaintext echo and
`success`, then confirm no callback process writes to the database or invokes an
agent.
