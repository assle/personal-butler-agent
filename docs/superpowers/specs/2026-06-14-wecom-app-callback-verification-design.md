# WeCom Custom-App Callback Verification Design

## Goal

Add the minimum WeChat Work custom-application callback endpoint needed to
verify a "receive messages server URL", so the administrator can then configure
the custom application's trusted outbound IP and unblock proactive research
report delivery.

## Scope

The new endpoint is:

```text
GET/POST /api/wechat/app/callback
```

It is separate from the intelligent robot endpoint:

```text
GET/POST /api/wechat/aibot/callback
```

The endpoint does not create research tasks, persist inbound messages, call any
agent, or send a reply. Existing research delivery continues to use
`WeComAppMessageClient` with `WECOM_APP_CORP_ID`, `WECOM_APP_SECRET`, and
`WECOM_APP_AGENT_ID`.

## Configuration

Add two callback-only settings:

```env
WECOM_APP_CALLBACK_TOKEN=
WECOM_APP_CALLBACK_ENCODING_AES_KEY=
```

`WECOM_APP_CORP_ID` is reused as the encrypted payload receive ID. The route is
registered only when CorpID, callback Token, and callback EncodingAESKey are all
configured.

## Request Flow

### GET Verification

1. Read `msg_signature`, `timestamp`, `nonce`, and `echostr`.
2. Verify the SHA-1 signature with the callback Token.
3. Decrypt `echostr` with the callback EncodingAESKey.
4. Verify the encrypted payload receive ID equals `WECOM_APP_CORP_ID`.
5. Return the decrypted plaintext as `text/plain`.
6. Return HTTP 403 when signature or receive-ID validation fails.

### POST Confirmation

1. Read encrypted XML or JSON body.
2. Extract `Encrypt` or `encrypt`.
3. Verify the signature and decrypt the payload.
4. Verify the encrypted payload receive ID equals `WECOM_APP_CORP_ID`.
5. Parse XML or JSON only to confirm the plaintext is structurally valid.
6. Log only non-sensitive message metadata and return plaintext `success`.
7. Return HTTP 400 for malformed bodies and HTTP 403 for cryptographic
   validation failures.

## Security

- AIBot callback credentials and custom-app callback credentials remain
  independent.
- Token, EncodingAESKey, Secret, access token, and decrypted message content are
  never logged.
- POST payloads are intentionally ignored after validation.
- No database access or background task is needed.

## Testing

- Config fields load from environment and default to empty strings.
- GET returns the decrypted echo for a valid encrypted request.
- GET rejects an invalid signature and wrong CorpID.
- POST accepts encrypted XML and JSON, returning `success`.
- POST rejects missing encryption and invalid signatures.
- Main app registers the route only when all callback settings are present.

## Documentation

Update `.env.example`, config-variable documentation, deployment guides,
architecture context, and troubleshooting instructions with the exact ZeroNews
URL and administrator workflow.
