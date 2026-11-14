# Security policy

## Reporting a vulnerability

Do **not** open a public issue for security problems. Report them privately through GitHub's [private vulnerability reporting](https://github.com/EXARTeo/genAI-summit/security/advisories/new). Include steps to reproduce and the affected version or commit.

## Handling secrets

- API keys and credentials go in `.env`, which git ignores. Never commit them.
- If a key is committed by mistake, revoke it at the provider first, then remove it from history.
- Treat model output and any user-supplied prompt content as untrusted input.
