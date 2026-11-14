"""One browser never reaches another's data.

The caller is the ``X-Client-Id`` header (no login). Every per-conversation
route answers another client with a 404 (never a 403, which would confirm the
id exists), and every list is scoped to the caller. A request without the
header lands in the shared ``anonymous`` bucket; a malformed header is a 400.
"""

from __future__ import annotations

import pytest
from conftest import AGENT_SLUG, CLIENT_ID
from httpx import ASGITransport, AsyncClient

from core.database import AttachmentTable, BlobTable

PER_CONVERSATION_ROUTES = [
    ("GET", "/v1/conversations/{cid}", None),
    ("DELETE", "/v1/conversations/{cid}", None),
    ("PATCH", "/v1/conversations/{cid}/title", {"title": "Mine now"}),
    ("PATCH", "/v1/conversations/{cid}/archive", None),
    ("PATCH", "/v1/conversations/{cid}/unarchive", None),
    ("PATCH", "/v1/conversations/{cid}/pin", None),
    ("PATCH", "/v1/conversations/{cid}/unpin", None),
    ("POST", "/v1/conversations/{cid}/fork", {"messageId": "{ai}"}),
    ("POST", "/v1/messages/{cid}", {"sender": "user", "content": "hi"}),
    ("PATCH", "/v1/messages/{cid}/{ai}", {"content": "overwritten"}),
    ("POST", "/v1/messages/{cid}/{ai}/like", None),
    ("POST", "/v1/messages/{cid}/{ai}/dislike", None),
    ("GET", "/v1/attachments/download/{cid}/{user}/{blob}", None),
    ("GET", "/v1/attachments/preview/{cid}/{user}/{blob}", None),
]


@pytest.fixture
async def owned(conversation_factory, session_factory) -> dict[str, str]:
    """A conversation of the test client with a question, an answer and a file."""
    created = await conversation_factory(
        title="Private plans",
        messages=[{"sender": "user", "content": "rocket"}, {"sender": "ai", "content": "fuel"}],
    )
    user_id, ai_id = created["message_ids"]
    async with session_factory() as session:
        blob = BlobTable(data=b"%PDF")
        session.add(
            AttachmentTable(
                message_id=user_id, file_name="plan.pdf", mime_type="application/pdf", blob=blob
            )
        )
        session.add(
            AttachmentTable(
                message_id=user_id,
                file_name="photo.png",
                mime_type="image/png",
                blob=BlobTable(data=b"png"),
            )
        )
        await session.commit()
        blob_id = blob.id
    return {"cid": created["conversation_id"], "user": user_id, "ai": ai_id, "blob": blob_id}


def _fill(template: str, ids: dict[str, str]) -> str:
    return template.format(**ids)


@pytest.mark.parametrize(("method", "path", "body"), PER_CONVERSATION_ROUTES)
async def test_another_client_gets_404_on_every_per_conversation_route(
    client, other_client, owned, method, path, body
):
    json_body = (
        {
            key: _fill(value, owned) if isinstance(value, str) else value
            for key, value in body.items()
        }
        if body
        else None
    )

    response = await other_client.request(method, _fill(path, owned), json=json_body)

    assert response.status_code == 404
    # And nothing changed for the owner.
    detail = (await client.get(f"/v1/conversations/{owned['cid']}")).json()
    assert detail["title"] == "Private plans"
    assert detail["isArchived"] is False
    assert detail["isPinned"] is False
    assert [m["content"] for m in detail["messages"]] == ["rocket", "fuel"]
    assert all(m["liked"] is None for m in detail["messages"])


async def test_another_client_sees_empty_lists(client, other_client, owned, conversation_factory):
    # One conversation of the test client in each list: Chats (owned), archive, pins.
    await conversation_factory(title="Archived plans", is_archived=True)
    await conversation_factory(title="Pinned plans", is_pinned=True)

    for path in (
        "/v1/conversations",
        "/v1/conversations/archived",
        "/v1/conversations/pinned",
        "/v1/attachments/images",
    ):
        mine = (await client.get(path)).json()
        theirs = (await other_client.get(path)).json()
        assert mine["total"] == 1, path
        assert theirs == {**theirs, "items": [], "total": 0}, path

    assert (await client.get("/v1/search?q=rocket")).json()
    assert (await other_client.get("/v1/search?q=rocket")).json() == []


async def test_requests_without_a_client_id_share_the_anonymous_bucket(app, client):
    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://testserver") as first,
        AsyncClient(transport=transport, base_url="http://testserver") as second,
    ):
        created = await first.post(
            "/v1/conversations",
            json={"agentSlug": AGENT_SLUG, "firstMessage": {"sender": "user", "content": "hi"}},
        )
        assert created.status_code == 201
        cid = created.json()["summary"]["id"]

        assert (await second.get(f"/v1/conversations/{cid}")).status_code == 200
        assert (await client.get(f"/v1/conversations/{cid}")).status_code == 404


async def test_a_malformed_client_id_is_a_400(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver", headers={"X-Client-Id": "not-a-uuid"}
    ) as malformed:
        response = await malformed.get("/v1/conversations")

    assert response.status_code == 400


async def test_an_equivalent_client_id_spelling_is_the_same_client(app, owned):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-Client-Id": CLIENT_ID.upper()},
    ) as same:
        response = await same.get(f"/v1/conversations/{owned['cid']}")

    assert response.status_code == 200
