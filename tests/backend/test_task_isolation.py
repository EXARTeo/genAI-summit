"""One browser never reaches another's background tasks.

Every task route answers another client with a 404 (never a 403) and proxies
nothing upstream; the task list of a conversation is its owner's only; the
busy list is the caller's own; and both sockets a task view uses (the task's
drill-down and the conversation channel) close 4404 for another client before
the handshake completes, while the owner gets through.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from conftest import AGENT_SLUG, CLIENT_ID, OTHER_CLIENT_ID
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.websockets import WebSocketDisconnect

import router.inference as inference_router
import router.tasks as tasks_router
import utils.async_tasks as async_tasks
import utils.websockets as websockets
from core.database import ConversationTable, ConversationTaskTable

TASK_ROUTES = [
    ("POST", "/v1/tasks/task-1/cancel", None),
    ("POST", "/v1/tasks/task-1/resume", {"decision": "approve", "interruptId": "int-1"}),
    ("GET", "/v1/conversations/{cid}/tasks", None),
]


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@pytest.fixture
async def owned_task(session_factory) -> str:
    """A conversation of the test client with one settled, mirrored task."""
    async with session_factory() as s:
        conversation = ConversationTable(client_id=CLIENT_ID, agent_slug=AGENT_SLUG, title="mine")
        s.add(conversation)
        await s.flush()
        s.add(
            ConversationTaskTable(
                task_id="task-1",
                conversation_id=conversation.id,
                client_id=CLIENT_ID,
                name="researcher",
                status="success",
                depth=1,
                raw_events=[{"type": "RUN_STARTED"}],
                started_at=_now(),
                settled_at=_now(),
            )
        )
        await s.commit()
        return conversation.id


@pytest.mark.parametrize(("method", "path", "body"), TASK_ROUTES)
async def test_another_client_gets_404_on_every_task_route(
    other_client, owned_task, agents_service, method, path, body
):
    # Not in the other client's mirror, and the agents service says the same.
    agents_service.on("GET", "/tasks/task-1", httpx.Response(404))
    response = await other_client.request(method, path.format(cid=owned_task), json=body)
    assert response.status_code == 404
    proxied = [r for r in agents_service.calls if r.method == "POST"]
    assert proxied == []


async def test_an_upstream_task_of_another_clients_conversation_is_a_404(
    other_client, owned_task, agents_service
):
    # Even if the agents service answered for this client, the task's
    # conversation must be the caller's own.
    agents_service.on(
        "GET",
        "/tasks/task-1",
        httpx.Response(
            200,
            json={
                "task_id": "task-1",
                "conversation_id": owned_task,
                "client_id": OTHER_CLIENT_ID,
                "name": "researcher",
                "status": "running",
            },
        ),
    )
    assert (await other_client.post("/v1/tasks/task-1/cancel")).status_code == 404
    assert agents_service.called("POST", "/tasks/task-1/cancel") == []


async def test_the_busy_list_is_the_callers_own(client, other_client, session_factory, owned_task):
    async with session_factory() as s:
        (await s.get(ConversationTaskTable, "task-1")).status = "running"
        await s.commit()
    mine = await client.get("/v1/tasks/active-conversations")
    theirs = await other_client.get("/v1/tasks/active-conversations")
    assert mine.json() == {"conversationIds": [owned_task]}
    assert theirs.json() == {"conversationIds": []}


async def test_the_drill_down_frames_are_the_owners_only(session_factory, owned_task):
    frames = [
        f
        async for f in async_tasks.stream_task_events(
            OTHER_CLIENT_ID, "task-1", None, session_factory=session_factory
        )
    ]
    assert frames == []


# ---------------------------------------------------------------------------
# The sockets (a real handshake through the ASGI app)
# ---------------------------------------------------------------------------
@pytest.fixture
def socket_app(app, db_engine, monkeypatch):
    """The app with the socket routes on the test database.

    ``TestClient`` runs the app on its own event loop, so the sockets get an
    engine without a pool (a connection per session, opened on that loop).
    """
    engine = create_async_engine(db_engine.url, poolclass=NullPool)
    sessions = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    for module in (tasks_router, inference_router, async_tasks):
        monkeypatch.setattr(module, "SessionLocal", sessions)

    async def allowed(_websocket, _client_id):
        return True

    monkeypatch.setattr(websockets, "allow_ws_connect", allowed)
    return app


SOCKETS = ["/v1/tasks/task-1/ws", "/v1/inference/conversations/{cid}/ws"]


@pytest.mark.parametrize("path", SOCKETS)
def test_another_client_is_refused_on_both_task_sockets(socket_app, owned_task, path):
    # No `with`: the app's lifespan (migrations, task loops) must not run here.
    client = TestClient(socket_app)
    url = f"{path.format(cid=owned_task)}?client_id={OTHER_CLIENT_ID}"
    with pytest.raises(WebSocketDisconnect) as refused, client.websocket_connect(url):
        pass
    assert refused.value.code == 4404


def test_the_owner_opens_a_settled_tasks_drill_down(socket_app, owned_task):
    client = TestClient(socket_app)
    with client.websocket_connect(f"/v1/tasks/task-1/ws?client_id={CLIENT_ID}") as ws:
        ws.send_json({"type": "subscribe"})
        snapshot = ws.receive_json()
        terminal = ws.receive_json()
    assert snapshot["type"] == "snapshot" and snapshot["events"] == [{"type": "RUN_STARTED"}]
    assert "client_id" not in snapshot["task"]
    assert terminal == {"type": "terminal", "status": "success"}
