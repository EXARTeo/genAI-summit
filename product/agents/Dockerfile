# The agents service: FastAPI on 8003, AG-UI over SSE to the backend.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# psycopg[binary] and Pillow ship wheels, so no build toolchain is needed.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Non-root: uid/gid 1000, matching the compose `user: "1000:1000"`.
RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --no-create-home app \
    && chown -R app:app /app
USER app

# The release tag, stamped on every log line (settings.app.version). Declared
# last so changing it never invalidates the dependency layers above.
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

EXPOSE 8003
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8003"]
