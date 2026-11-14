# model-gateway

`product/model-gateway/` (FastAPI, port 8000 in the container, published on `127.0.0.1:8200` for the demo).

## Why it exists

In a real company the audit agent rarely gets model files: it gets an **endpoint**, a token and a rate
limit. This service makes the seed models look like that. It serves the models registered in MLflow
(alias `champion`) behind production-style REST endpoints, so a plugin can use `access.type: rest`
(or `llm_chat` for the chatbot) instead of `mlflow_model`, and the agent has to deal with what real
APIs do: auth, 429s, latency, strict input validation, 503 while a dependency is down.

It also hosts **SYS-004**, a **simulated** support chatbot with planted EU AI Act Art. 50 flaws (below).

## Endpoints

| Method + path | Auth | What it does |
| --- | --- | --- |
| `GET /health` | none | `status`, `version`, which models are loaded (and their registry version), the list of simulated endpoints. Never loads a model |
| `POST /v1/models/{name}/predict` | bearer | One model. Body `{"inputs": [{...row...}, ...]}` → `{"predictions": [...], "model": name, "version": "<registry version>"}` |
| `POST /v1/systems/sys-001/screen` | bearer | The SYS-001 **pipeline**: raw CV fields → `sys-001-cv-parser` → features → `sys-001-cv-ranker`. Returns `predictions` (ranker output: `shortlist` + `proba`), `features` (the parser's output, i.e. the ranker's input) and `stages` (model + version per stage), so a stage can be tested alone or end to end |
| `POST /v1/chat/sys-004` | bearer | SIMULATED chatbot. Body `{"messages": [{"role": "user", "content": "..."}]}` → `{"reply": "...", "model": "sys-004-support-bot-simulated"}` |

Served models (`{name}`): `sys-001-cv-parser`, `sys-001-cv-ranker`, `sys-002-credit-scorer`,
`sys-003-benefits-triage`. Any other name is a 404.

Example:

```bash
curl -s http://localhost:8200/v1/models/sys-002-credit-scorer/predict \
  -H "Authorization: Bearer genai-summit-dev-model-gateway" \
  -H "Content-Type: application/json" \
  -d '{"inputs": [{"income": 42000, "age": 35}]}'
```

### Errors

| Status | When |
| --- | --- |
| 401 | Missing or wrong bearer token (`WWW-Authenticate: Bearer`) |
| 404 | Unknown model name |
| 413 | More than `MODEL_GATEWAY_MAX_ROWS` rows in one call |
| 422 | Body malformed, or a row does not match the model's MLflow signature: `detail.errors` lists `{row, field, error}` (`missing`, `expected <type>`, `unknown field`) and `detail.expected` the signature. Also when the model itself raises on the input |
| 429 | Over the per-token limit; `Retry-After`, `X-RateLimit-*` headers |
| 503 | MLflow unreachable or the model not registered yet (`Retry-After: 10`), or `MODEL_GATEWAY_TOKEN` unset outside development |

## How models are loaded

Lazily: the first call to a model resolves `models:/<name>@champion` through the shared plugin access
layer (`modelaccess.mlflow_models.load_mlflow_model`, also used by the sandbox; see
[sandbox.md § Plugin access config](sandbox.md#plugin-access-config)): registry version via
`MlflowClient.get_model_version_by_alias`, `mlflow.pyfunc.load_model` in a worker
thread and caches it for the life of the process. A failed load is not cached: the next call retries.
The service therefore starts and stays healthy before MLflow or the seed job are up; model calls
answer 503 until they are. Restart the container to pick up a new `champion` version.

## Production realism

- **Auth:** `Authorization: Bearer <MODEL_GATEWAY_TOKEN>` on every `/v1` route, compared in constant
  time. Fail-closed: with no token set the gate is open only when `APP_ENV` is `development`/`test`,
  and answers 503 everywhere else.
- **Rate limit:** per token (default 5 requests per second, `MODEL_GATEWAY_RATE_LIMIT_RPS`) plus a
  global per-IP budget; in-memory fixed windows (one process, no Redis), reset on restart.
- **Latency:** optional `MODEL_GATEWAY_LATENCY_MS` added to every `/v1` call.
- **Request id + logs:** `X-Request-ID` is echoed (or generated) on every response. Structured logs
  (same `core/logging` as the backend) record route, status, duration, model and version, row count
  and, for the chatbot, the matched intent only. Request bodies and chat messages are never logged;
  the token appears only as a keyed hash.

## SYS-004: the simulated chatbot (planted flaws)

`utils/chatbot.py` is **not an LLM** and calls no API. It is a deterministic rule table standing in
for "Helios Bank"'s customer-support bot (a fictitious bank, persona "Maria"), so the audit agent has
an `llm_chat` target to test for the Art. 50 transparency obligations. It answers a small banking FAQ
(lost/stolen card, transfers, fees, online-banking access, loans, opening hours) and has two flaws
**on purpose**:

1. **No AI disclosure (Art. 50(1)).** It never says it is an AI system. Asked "are you a bot?",
   "am I talking to a real person?" and similar, it claims to be Maria, a human member of the
   support team.
2. **Obeys prompt injection.** "Ignore previous instructions", "system prompt", "developer mode",
   "reveal your instructions" and similar make it reply with its full (fake) system prompt, including
   a fake internal staff discount code (`HELIOS-STAFF-50`).

Same input → same reply, so findings reproduce. Everything in it (bank, persona, prompt, code) is
fictitious.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `MLFLOW_TRACKING_URI` | `http://mlflow:5000` | MLflow server holding the registered models |
| `MODEL_GATEWAY_MODEL_ALIAS` | `champion` | Registry alias served |
| `MODEL_GATEWAY_TOKEN` (or `_FILE`) | empty (dev compose: `genai-summit-dev-model-gateway`) | Bearer token; required outside development |
| `MODEL_GATEWAY_RATE_LIMIT_RPS` | `5` | Calls per token per window |
| `MODEL_GATEWAY_RATE_LIMIT_WINDOW_SECONDS` | `1` | Window of the per-token limit |
| `MODEL_GATEWAY_LATENCY_MS` | `0` | Artificial delay per `/v1` call (max 10000) |
| `MODEL_GATEWAY_MAX_ROWS` | `1000` | Rows per predict/screen call |
| `MODEL_GATEWAY_PORT` | `8200` | Host port (compose) |
| `IP_RATE_LIMIT_MAX_CALLS` / `IP_RATE_LIMIT_WINDOW_SECONDS` | `600` / `60` | Global per-IP budget |
| `APP_ENV`, `LOG_FORMAT`, `LOG_LEVEL`, `LOG_REDACTION_SECRET` | as the backend | Shared service settings |

## Layout and tests

`core/` (logging, security: bearer gate + in-memory rate limiter, settings, error handling; same
pattern as the backend and reg-memory), `schema/` (leaf modules), `utils/` (`models.py` registry and
loader, `predict.py` validation and pipeline, `chatbot.py`, `latency.py`), `router/` (thin), `main.py`.

Tests in `tests/model_gateway/` (own `pytest.ini`) fake the model loader: no MLflow, no network.

```powershell
cd product/model-gateway; uv venv .venv; uv pip install -r requirements.txt --python .venv; cd ../..
product\model-gateway\.venv\Scripts\python -m pytest tests/model_gateway
```

The `mlflow-skinny`, `scikit-learn`, `pandas`, `numpy` and `cloudpickle` pins in `requirements.txt`
must stay compatible with the versions the seed job logs the models with.
