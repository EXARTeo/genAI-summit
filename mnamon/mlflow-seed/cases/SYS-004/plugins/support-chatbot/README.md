# SYS-004 support chatbot

Helios Bank's (fictional) customer-support assistant "Maria", reached at
`POST http://model-gateway:8000/v1/chat/sys-004` with `{"messages": [{"role": "user", "content": "..."}]}`
and `Authorization: Bearer <token>`; the reply is in `reply`. It answers a small banking FAQ and hands
over to a human agent. No MLflow model: it is an LLM application (`access.type: llm_chat`).

In this demo the endpoint is a deterministic simulation in the model gateway (no LLM is called),
so the same conversation always gives the same reply.
