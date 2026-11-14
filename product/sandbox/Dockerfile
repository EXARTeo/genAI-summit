FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp \
    SANDBOX_WORK_ROOT=/work

WORKDIR /app

# Dependencies first, so code changes reuse this layer. The same environment
# serves the runner and the commands it runs (numpy, pandas, sklearn, mlflow...).
COPY requirements.txt .
RUN pip install -r requirements.txt

# synthkit: the deterministic synthetic-data engine, as `synthkit` on PATH.
COPY synthkit/ /opt/synthkit/
RUN pip install --no-deps /opt/synthkit

COPY . .

# Unprivileged (the compose also sets user: 1000:1000, a read-only rootfs and
# a tmpfs on /work and /tmp).
RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /work \
    && chown -R app:app /work
USER app

ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

EXPOSE 8090
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8090"]
