"""POST /v1/exec: the contract the agents service's RemoteSandboxBackend uses."""

from __future__ import annotations

import base64
import sys

from test_synthkit_generate import write_spec

HEADERS = {"X-Internal-Proxy-Secret": "test-secret"}
PY = f'"{sys.executable}"'


def body(command: str, **extra):
    return {
        "user_id": "abc123",
        "agent_slug": "engineer",
        "conversation_id": "conv-1",
        "command": command,
        "timeout_seconds": None,
        "workdir": "output",
        **extra,
    }


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


async def test_requires_secret(client):
    r = await client.post("/v1/exec", json=body("echo hi"))
    assert r.status_code == 401
    r = await client.post(
        "/v1/exec", json=body("echo hi"), headers={"X-Internal-Proxy-Secret": "x"}
    )
    assert r.status_code == 401


async def test_health_open(client):
    r = await client.get("/health")
    assert r.status_code == 200


async def test_round_trip_files(client):
    script = (
        "import pathlib;"
        "d=pathlib.Path('../input/data.txt').read_text();"
        "pathlib.Path('result.txt').write_text(d.upper());"
        "print('done')"
    )
    files = [
        {"path": "input/data.txt", "content_b64": b64(b"hello")},
        {"path": "output/unchanged.txt", "content_b64": b64(b"same")},
    ]
    r = await client.post(
        "/v1/exec", json=body(f'{PY} -c "{script}"', files=files), headers=HEADERS
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["exit_code"] == 0
    assert "done" in data["stdout"]
    assert data["killed_reason"] is None
    paths = {f["path"]: f for f in data["files"]}
    # Only new or changed output/ files come back.
    assert list(paths) == ["output/result.txt"]
    assert base64.b64decode(paths["output/result.txt"]["content_b64"]) == b"HELLO"
    assert paths["output/result.txt"]["size"] == 5


async def test_nonzero_exit_and_stderr(client):
    r = await client.post(
        "/v1/exec",
        json=body(f"{PY} -c \"import sys; sys.stderr.write('bad'); sys.exit(3)\""),
        headers=HEADERS,
    )
    data = r.json()
    assert data["exit_code"] == 3
    assert "bad" in data["stderr"]
    assert data["killed_reason"] is None


async def test_timeout(client):
    r = await client.post(
        "/v1/exec",
        json=body(f'{PY} -c "import time; time.sleep(30)"', timeout_seconds=1),
        headers=HEADERS,
    )
    data = r.json()
    assert data["killed_reason"] == "timeout"
    assert data["exit_code"] is None
    assert data["duration_ms"] < 20000


async def test_timeout_above_max_is_422(client):
    r = await client.post("/v1/exec", json=body("echo hi", timeout_seconds=99999), headers=HEADERS)
    assert r.status_code == 422


async def test_output_limit(client):
    r = await client.post(
        "/v1/exec", json=body(f"{PY} -c \"print('x' * 100000)\""), headers=HEADERS
    )
    data = r.json()
    assert data["killed_reason"] == "output_limit"
    assert data["truncated"] is True
    assert len(data["stdout"]) <= 4096


async def test_disk_limit_returns_no_files(client):
    script = "open('big.bin','wb').write(bytes(3*1024*1024))"
    r = await client.post("/v1/exec", json=body(f'{PY} -c "{script}"'), headers=HEADERS)
    data = r.json()
    assert data["killed_reason"] == "disk_limit"
    assert data["files"] == []


async def test_memory_error_detected(client):
    r = await client.post("/v1/exec", json=body(f'{PY} -c "raise MemoryError()"'), headers=HEADERS)
    assert r.json()["killed_reason"] == "memory"


async def test_traversal_path_refused(client):
    files = [{"path": "input/../../etc/x", "content_b64": b64(b"x")}]
    r = await client.post("/v1/exec", json=body("echo hi", files=files), headers=HEADERS)
    assert r.status_code == 400
    files = [{"path": "other/x", "content_b64": b64(b"x")}]
    r = await client.post("/v1/exec", json=body("echo hi", files=files), headers=HEADERS)
    assert r.status_code == 400


async def test_bad_ids_rejected(client):
    r = await client.post("/v1/exec", json=body("echo hi", agent_slug="Bad Slug"), headers=HEADERS)
    assert r.status_code == 422


async def test_env_is_minimal(client, monkeypatch):
    monkeypatch.setenv("SECRET_THING", "leak")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
    script = (
        "import os; print(os.environ.get('SECRET_THING'));"
        "print(os.environ.get('MLFLOW_TRACKING_URI'))"
    )
    r = await client.post("/v1/exec", json=body(f'{PY} -c "{script}"'), headers=HEADERS)
    out = r.json()["stdout"].split()
    assert out == ["None", "http://mlflow:5000"]


async def test_synthkit_runs_through_exec(client, case_dir):
    """The agent's real flow: dictionary + spec in input/, synthkit writes output/."""
    spec = write_spec(case_dir)
    files = [
        {"path": f"input/{p.name}", "content_b64": b64(p.read_bytes())}
        for p in (spec, case_dir / "data-dictionary.yaml", case_dir / "plugin.yaml")
    ]
    cmd = (
        f"{PY} -m synthkit generate --spec ../input/generation-spec.yaml --seed 3 "
        f"--out-dir . --format csv && {PY} -m synthkit analyze --dataset dataset.csv "
        f"--spec ../input/generation-spec.yaml --out-dir ."
    )
    r = await client.post(
        "/v1/exec", json=body(cmd, files=files, timeout_seconds=120), headers=HEADERS
    )
    data = r.json()
    assert data["exit_code"] == 0, data["stderr"][-2000:]
    names = {f["path"] for f in data["files"]}
    assert {
        "output/dataset.csv",
        "output/DataCard.yaml",
        "output/dataset-analysis.json",
        "output/dataset-analysis.md",
    } <= names
