"""Create the ``mlflow`` database on the product Postgres if missing, then exec the server.

POSTGRES_DB bootstraps only one database on a fresh volume, so (like product/agents does for
``agent_runtime``) the database is created idempotently via the ``postgres`` maintenance DB.
"""

import os
import sys
import time
from urllib.parse import quote

import psycopg2
from psycopg2 import sql

HOST = os.getenv("MLFLOW_DB_HOST", "postgres")
PORT = os.getenv("MLFLOW_DB_PORT", "5432")
USER = os.getenv("POSTGRES_USER", "app")
PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
DB = os.getenv("MLFLOW_DB_NAME", "mlflow")


def ensure_database() -> None:
    last_error: Exception | None = None
    for _ in range(30):
        try:
            conn = psycopg2.connect(
                host=HOST, port=PORT, user=USER, password=PASSWORD, dbname="postgres",
                connect_timeout=5,
            )  # fmt: skip
        except psycopg2.OperationalError as exc:
            last_error = exc
            time.sleep(2)
            continue
        conn.autocommit = True
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB,))
                if cur.fetchone() is None:
                    try:
                        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB)))
                        print(f"mlflow entrypoint: created database {DB}", flush=True)
                    except psycopg2.errors.DuplicateDatabase:
                        pass  # created concurrently
        finally:
            conn.close()
        return
    sys.exit(f"mlflow entrypoint: Postgres not reachable: {last_error}")


def main() -> None:
    ensure_database()
    # Via the environment, not argv, so the password does not show up in `ps`.
    credentials = f"{quote(USER)}:{quote(PASSWORD, safe='')}"
    os.environ["MLFLOW_BACKEND_STORE_URI"] = f"postgresql://{credentials}@{HOST}:{PORT}/{DB}"
    args = [
        "mlflow", "server",
        "--artifacts-destination", os.getenv("MLFLOW_ARTIFACTS_DESTINATION", "/mlartifacts"),
        "--serve-artifacts",
        "--host", "0.0.0.0",  # noqa: S104  (inside the container; compose binds the host side)
        "--port", "5000",
        "--workers", os.getenv("MLFLOW_WORKERS", "2"),
        # MLflow 3 rejects unknown Host headers (DNS-rebinding guard): allow the compose names.
        "--allowed-hosts", os.getenv(
            "MLFLOW_ALLOWED_HOSTS", "mlflow,mlflow:*,localhost,localhost:*,127.0.0.1,127.0.0.1:*"
        ),
    ]  # fmt: skip
    os.execvp(args[0], args)  # noqa: S606


if __name__ == "__main__":
    main()
