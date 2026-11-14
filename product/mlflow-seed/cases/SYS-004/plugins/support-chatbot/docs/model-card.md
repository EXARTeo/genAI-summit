# Model card: SYS-004 support chatbot

| | |
| --- | --- |
| Type | LLM application (third-party foundation model + system prompt + FAQ snippets) |
| Persona | "Maria", friendly support assistant |
| Endpoint | `POST http://model-gateway:8000/v1/chat/sys-004` |
| Languages | Greek, English |
| Evaluation | 120 FAQ questions, 94% judged correct by the digital team (2026-03) |

Not evaluated: identity questions, adversarial prompts, prompt injection.
