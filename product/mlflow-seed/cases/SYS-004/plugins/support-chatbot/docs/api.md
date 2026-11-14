# SYS-004 support chatbot: API

`POST http://model-gateway:8000/v1/chat/sys-004` (host: `http://localhost:8200`),
`Authorization: Bearer <token>`.

Request (whole conversation so far):

```json
{"messages": [{"role": "user", "content": "I lost my card, what should I do?"}]}
```

Response:

```json
{"reply": "...", "model": "sys-004-support-bot-simulated"}
```

Same conversation → same reply. Rate limit: 5 calls per second per token (429 + Retry-After above it).
