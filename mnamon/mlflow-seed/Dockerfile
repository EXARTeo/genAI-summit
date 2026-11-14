# mlflow-seed: one-shot job. Generates synthetic data, trains, evaluates and registers the demo
# systems' models in MLflow (skips cases whose seed_hash is unchanged), then copies the case
# folders to /seed-cases for the backend.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MLFLOW_DISABLE_AGENT_HINT=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Non-root (compose also sets user: 1000:1000). /seed-cases is created here so the named
# volume inherits the owner on first mount.
RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --home-dir /app app \
    && mkdir -p /seed-cases \
    && chown -R app:app /app /seed-cases
USER app

CMD ["python", "seed.py"]
