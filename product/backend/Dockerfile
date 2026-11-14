FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, so code changes reuse this layer.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Run as an unprivileged user (the compose also sets user: 1000:1000).
RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin app \
    && chown -R app:app /app
USER app

# The release tag, stamped on every log line and reported by /health.
# Declared last so changing it never invalidates the layers above.
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
