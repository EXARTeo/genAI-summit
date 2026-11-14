# MLflow tracking server + model registry: Postgres metadata (`mlflow` database on the
# product Postgres, created at start) and proxied artifacts in the mlflow_artifacts volume.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MLFLOW_DISABLE_AGENT_HINT=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY entrypoint.py .

# Non-root (compose also sets user: 1000:1000). /mlartifacts is created here so the named
# volume inherits the owner on first mount.
RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --home-dir /app app \
    && mkdir -p /mlartifacts \
    && chown -R app:app /app /mlartifacts
USER app

EXPOSE 5000
CMD ["python", "entrypoint.py"]
