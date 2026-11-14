FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp

WORKDIR /app

# Dependencies first, so code changes reuse this layer.
COPY requirements.txt .
RUN pip install -r requirements.txt

# modelaccess: the plugin access layer (mlflow_model / rest / llm_chat + RunLogger),
# one source shared by the sandbox (synthkit, run-tests) and the model gateway.
# Comes from the compose build context `shared` (mnamon/shared).
COPY --from=shared modelaccess/ /opt/modelaccess/
RUN pip install --no-deps /opt/modelaccess

COPY . .

# Run as an unprivileged user (the compose also sets user: 1000:1000). MLflow
# downloads model artifacts to a temp dir; HOME=/tmp keeps its caches writable.
RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin app \
    && chown -R app:app /app
USER app

ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
