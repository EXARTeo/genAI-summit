FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    REG_MEMORY_DATA_DIR=/data

WORKDIR /app

# Dependencies first, so code changes reuse this layer.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Run as an unprivileged user (the compose also sets user: 1000:1000). /data is
# the document store volume; created here so a fresh named volume is owned by app.
RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data \
    && chown -R app:app /app /data
USER app
VOLUME ["/data"]

ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

EXPOSE 8010
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8010"]
