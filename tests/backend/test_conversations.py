"""Conversation routes: create, lists, archive, pin, rename, get, delete, fork.

No login: the caller is the
``X-Client-Id`` the ``client`` fixture sends.
"""

from __future__ import annotations

import base64

from conftest import AGENT_SLUG, CLIENT_ID
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.database import AttachmentTable, BlobTable, ConversationTable, MessageTable
from core.settings import settings


async def _seed_branch(session_factory, *, with_file: bool = False) -> dict[str, str]:
    """A conversation with a question and a finished answer (optionally with a file)."""
    async with session_factory() as session:
        conversation = ConversationTable(
            client_id=CLIENT_ID,
            agent_slug=AGENT_SLUG,
            agent_name="Test Agent",
            title="Branchable conversation",
            last_message_preview="Final answer",
        )
        session.add(conversation)
        await session.flush()
        user_message = MessageTable(
            conversation_id=conversation.id, sender="user", content="Question"
        )
        session.add(user_message)
        await session.flush()
        ai_message = MessageTable(
            conversation_id=conversation.id,
            parent_message_id=user_message.id,
            sender="ai",
            content="Final answer",
            agent_slug=AGENT_SLUG,
            agent_name="Test Agent",
            reasoning_steps=["Looked up context"],
            raw_events=[{"type": "RUN_FINISHED"}],
            checkpoint_thread_id="thread-1",
            checkpoint_id="checkpoint-1",
        )
        session.add(ai_message)
        await session.flush()
        if with_file:
            session.add(
                AttachmentTable(
                    message_id=ai_message.id,
                    file_name="chart.png",
                    mime_type="image/png",
                    size_bytes=3,
                    origin="generated",
                    title="Chart",
                    blob=BlobTable(data=b"png"),
                )
            )
        await session.commit()
        return {
            "conversation_id": conversation.id,
            "user_message_id": user_message.id,
            "ai_message_id": ai_message.id,
        }


def _first_message(content: str = "Hello there") -> dict:
    return {"sender": "user", "content": content}


# --- create ------------------------------------------------------------------


async def test_create_conversation_persists_first_message_and_fallback_title(client):
    response = await client.post(
        "/v1/conversations",
        json={
            "agentSlug": AGENT_SLUG,
            "agentName": "Test Agent",
            "firstMessage": _first_message(
                "This is a long first message that should become the fallback title"
            ),
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["summary"]["title"] == "This is a long first message that should"
    assert payload["summary"]["lastMessage"] == "This is a long first message that should"
    assert payload["summary"]["agentSlug"] == AGENT_SLUG
    assert payload["summary"]["agentName"] == "Test Agent"
    assert payload["summary"]["isStreaming"] is False
    assert payload["detail"]["messages"][0]["sender"] == "user"
    assert payload["detail"]["messages"][0]["content"].startswith("This is a long")


async def test_create_conversation_keeps_an_explicit_title_and_stores_the_client(
    client, session_factory
):
    response = await client.post(
        "/v1/conversations",
        json={"agentSlug": AGENT_SLUG, "title": "  My title  ", "firstMessage": _first_message()},
    )

    assert response.status_code == 201
    assert response.json()["summary"]["title"] == "My title"
    async with session_factory() as session:
        row = await session.get(ConversationTable, response.json()["summary"]["id"])
        assert row.client_id == CLIENT_ID


async def test_create_conversation_with_attachment_inlines_the_image(client):
    image = b"fake-image-bytes"
    response = await client.post(
        "/v1/conversations",
        json={
            "agentSlug": AGENT_SLUG,
            "firstMessage": {
                "sender": "user",
                "attachments": [
                    {
                        "name": "shot.png",
                        "mime": "image/png",
                        "dataB64": base64.b64encode(image).decode("ascii"),
                    }
                ],
            },
        },
    )

    assert response.status_code == 201
    payload = response.json()
    attachment = payload["detail"]["messages"][0]["attachments"][0]
    assert attachment["data"] == base64.b64encode(image).decode("ascii")
    assert attachment["size"] == len(image)
    # No text: the file name is the preview, the agent slug is not a title.
    assert payload["summary"]["lastMessage"] == "shot.png"


async def test_create_conversation_rejects_an_invalid_agent_slug(client):
    response = await client.post(
        "/v1/conversations",
        json={"agentSlug": "../agents", "firstMessage": _first_message()},
    )

    assert response.status_code == 422


async def test_create_conversation_requires_a_first_message_with_content(client):
    response = await client.post(
        "/v1/conversations",
        json={"agentSlug": AGENT_SLUG, "firstMessage": {"sender": "user", "content": ""}},
    )

    assert response.status_code == 422


# --- lists -------------------------------------------------------------------


async def test_get_conversations_excludes_archived(client, conversation_factory):
    active = await conversation_factory(title="Active conversation")
    await conversation_factory(title="Archived conversation", is_archived=True)

    response = await client.get("/v1/conversations?page=1&size=10")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == [active["conversation_id"]]


async def test_get_archived_conversations_returns_archived_only(client, conversation_factory):
    archived = await conversation_factory(title="Archived conversation", is_archived=True)
    await conversation_factory(title="Active conversation")

    response = await client.get("/v1/conversations/archived?page=1&size=10")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == [archived["conversation_id"]]


async def test_archive_conversation_moves_it_out_of_default_list(client, conversation_factory):
    conversation = await conversation_factory(title="Archive me")

    archive_response = await client.patch(
        f"/v1/conversations/{conversation['conversation_id']}/archive"
    )
    default_list = (await client.get("/v1/conversations?page=1&size=10")).json()
    archived_list = (await client.get("/v1/conversations/archived?page=1&size=10")).json()

    assert archive_response.status_code == 200
    assert archive_response.json()["isArchived"] is True
    assert archive_response.json()["archivedAt"] is not None
    assert default_list["total"] == 0
    assert archived_list["total"] == 1


async def test_unarchive_conversation_restores_it_to_default_list(client, conversation_factory):
    conversation = await conversation_factory(title="Bring me back", is_archived=True)

    unarchive_response = await client.patch(
        f"/v1/conversations/{conversation['conversation_id']}/unarchive"
    )
    default_list = (await client.get("/v1/conversations?page=1&size=10")).json()
    archived_list = (await client.get("/v1/conversations/archived?page=1&size=10")).json()

    assert unarchive_response.status_code == 200
    assert unarchive_response.json()["isArchived"] is False
    assert unarchive_response.json()["archivedAt"] is None
    assert default_list["total"] == 1
    assert archived_list["total"] == 0


# --- pin ---------------------------------------------------------------------


async def _pin(client, conversation_id: str, *, pinned: bool = True):
    action = "pin" if pinned else "unpin"
    return await client.patch(f"/v1/conversations/{conversation_id}/{action}")


async def test_pin_moves_conversation_from_chats_to_pinned_without_touching_recency(
    client, conversation_factory, session_factory
):
    conversation = await conversation_factory(title="Pin me")
    await conversation_factory(title="Stay in chats")
    async with session_factory() as session:
        updated_before = (
            await session.get(ConversationTable, conversation["conversation_id"])
        ).updated_at

    pin_response = await _pin(client, conversation["conversation_id"])
    chats = (await client.get("/v1/conversations?page=1&size=10")).json()
    pinned = (await client.get("/v1/conversations/pinned?page=1&size=10")).json()

    assert pin_response.status_code == 200
    assert pin_response.json()["isPinned"] is True
    assert pin_response.json()["pinnedAt"] is not None
    assert [item["id"] for item in pinned["items"]] == [conversation["conversation_id"]]
    assert conversation["conversation_id"] not in [item["id"] for item in chats["items"]]
    assert chats["total"] == 1
    # Pinning is not activity: unpinning must put it back in its place by recency.
    async with session_factory() as session:
        after = await session.get(ConversationTable, conversation["conversation_id"])
        assert after.updated_at == updated_before


async def test_unpin_returns_conversation_to_chats(client, conversation_factory):
    conversation = await conversation_factory(title="Unpin me")
    await _pin(client, conversation["conversation_id"])

    unpin_response = await _pin(client, conversation["conversation_id"], pinned=False)
    chats = (await client.get("/v1/conversations?page=1&size=10")).json()
    pinned = (await client.get("/v1/conversations/pinned?page=1&size=10")).json()

    assert unpin_response.status_code == 200
    assert unpin_response.json()["isPinned"] is False
    assert unpin_response.json()["pinnedAt"] is None
    assert [item["id"] for item in chats["items"]] == [conversation["conversation_id"]]
    assert pinned["total"] == 0


async def test_pinned_list_orders_newest_pin_first(client, conversation_factory, session_factory):
    first = await conversation_factory(title="Pinned first")
    second = await conversation_factory(title="Pinned second")
    await _pin(client, first["conversation_id"])
    await _pin(client, second["conversation_id"])
    # SQLite timestamps can tie within a test run; make the order explicit.
    async with session_factory() as session:
        row = await session.get(ConversationTable, first["conversation_id"])
        row.pinned_at = row.pinned_at.replace(year=row.pinned_at.year - 1)
        await session.commit()

    pinned = (await client.get("/v1/conversations/pinned?page=1&size=10")).json()

    assert [item["id"] for item in pinned["items"]] == [
        second["conversation_id"],
        first["conversation_id"],
    ]


async def test_repeated_pin_keeps_its_place(client, conversation_factory):
    conversation = await conversation_factory(title="Pin twice")
    first = await _pin(client, conversation["conversation_id"])
    second = await _pin(client, conversation["conversation_id"])

    assert second.status_code == 200
    assert second.json()["pinnedAt"] == first.json()["pinnedAt"]


async def test_pin_refuses_archived_conversations(client, conversation_factory):
    archived = await conversation_factory(title="Archived", is_archived=True)

    response = await _pin(client, archived["conversation_id"])

    assert response.status_code == 409


async def test_pin_refuses_past_the_cap(client, conversation_factory, monkeypatch):
    monkeypatch.setattr(settings.conversations, "max_pinned", 1)
    first = await conversation_factory(title="Fits")
    second = await conversation_factory(title="Over the cap")
    await _pin(client, first["conversation_id"])

    response = await _pin(client, second["conversation_id"])

    assert response.status_code == 409
    assert "up to 1" in response.json()["detail"]


async def test_the_pin_cap_counts_only_the_callers_pins(client, conversation_factory, monkeypatch):
    monkeypatch.setattr(settings.conversations, "max_pinned", 1)
    await conversation_factory(
        title="Someone else's pin", client_id="33333333-3333-4333-8333-333333333333", is_pinned=True
    )
    mine = await conversation_factory(title="Mine")

    response = await _pin(client, mine["conversation_id"])

    assert response.status_code == 200


async def test_archive_clears_the_pin(client, conversation_factory):
    conversation = await conversation_factory(title="Pinned then archived")
    await _pin(client, conversation["conversation_id"])

    archive_response = await client.patch(
        f"/v1/conversations/{conversation['conversation_id']}/archive"
    )
    pinned = (await client.get("/v1/conversations/pinned?page=1&size=10")).json()

    assert archive_response.json()["isArchived"] is True
    assert archive_response.json()["isPinned"] is False
    assert pinned["total"] == 0


# --- rename / get --------------------------------------------------------------


async def test_rename_conversation_normalizes_blank_and_long_titles(client, conversation_factory):
    conversation = await conversation_factory(title="Original")
    url = f"/v1/conversations/{conversation['conversation_id']}/title"

    blank_response = await client.patch(url, json={"title": "   "})
    long_response = await client.patch(url, json={"title": "  " + ("A" * 240) + "  "})

    assert blank_response.status_code == 422
    assert long_response.status_code == 200
    assert long_response.json()["title"] == "A" * 200


async def test_get_conversation_returns_every_message(client, conversation_factory):
    conversation = await conversation_factory(
        title="Detail",
        messages=[{"sender": "user", "content": "Hi"}, {"sender": "ai", "content": "Hello"}],
    )

    response = await client.get(f"/v1/conversations/{conversation['conversation_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Detail"
    assert [m["content"] for m in body["messages"]] == ["Hi", "Hello"]


async def test_get_unknown_conversation_is_404(client):
    response = await client.get("/v1/conversations/does-not-exist")

    assert response.status_code == 404
    assert response.json()["detail"] == "Conversation not found."


# --- delete --------------------------------------------------------------------


async def test_delete_conversation_removes_it(client, conversation_factory):
    conversation = await conversation_factory(
        title="Delete me", messages=[{"sender": "user", "content": "bye"}]
    )

    delete_response = await client.delete(f"/v1/conversations/{conversation['conversation_id']}")
    get_response = await client.get(f"/v1/conversations/{conversation['conversation_id']}")

    assert delete_response.status_code == 204
    assert get_response.status_code == 404


async def test_delete_is_refused_while_a_run_is_active(
    client, conversation_factory, session_factory
):
    conversation = await conversation_factory(
        title="Streaming", messages=[{"sender": "user", "content": "q"}]
    )
    async with session_factory() as session:
        session.add(
            MessageTable(
                conversation_id=conversation["conversation_id"],
                sender="ai",
                streaming_status="running",
            )
        )
        await session.commit()

    response = await client.delete(f"/v1/conversations/{conversation['conversation_id']}")

    assert response.status_code == 409
    assert (
        await client.get(f"/v1/conversations/{conversation['conversation_id']}")
    ).status_code == 200


async def test_delete_is_refused_while_an_assistant_message_is_active(
    client, conversation_factory, session_factory
):
    conversation = await conversation_factory(
        title="Active", messages=[{"sender": "ai", "content": ""}]
    )
    async with session_factory() as session:
        row = await session.get(ConversationTable, conversation["conversation_id"])
        row.active_assistant_message_id = conversation["message_ids"][0]
        await session.commit()

    response = await client.delete(f"/v1/conversations/{conversation['conversation_id']}")

    assert response.status_code == 409


# --- fork ----------------------------------------------------------------------


async def test_fork_conversation_clones_selected_branch(client, session_factory):
    branch = await _seed_branch(session_factory, with_file=True)

    response = await client.post(
        f"/v1/conversations/{branch['conversation_id']}/fork",
        json={"messageId": branch["ai_message_id"]},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["id"] != branch["conversation_id"]
    assert payload["forkedParentId"] == branch["conversation_id"]
    assert payload["forkedMessageId"] == branch["ai_message_id"]
    assert payload["lastMessage"] == "Final answer"
    assert payload["agentSlug"] == AGENT_SLUG
    assert payload["isPinned"] is False

    async with session_factory() as session:
        forked = await session.get(ConversationTable, payload["id"])
        assert forked.client_id == CLIENT_ID
        messages = (
            await session.scalars(
                select(MessageTable)
                .options(selectinload(MessageTable.attachments).selectinload(AttachmentTable.blob))
                .where(MessageTable.conversation_id == payload["id"])
            )
        ).all()

    by_sender = {message.sender: message for message in messages}
    assert len(messages) == 2 and set(by_sender) == {"user", "ai"}
    assert by_sender["ai"].parent_message_id == by_sender["user"].id
    assert by_sender["ai"].raw_events == [{"type": "RUN_FINISHED"}]
    assert by_sender["ai"].agent_slug == AGENT_SLUG
    # The fork gets its own checkpoint thread: the source's lineage is not copied.
    assert by_sender["ai"].checkpoint_thread_id is None
    assert by_sender["ai"].checkpoint_id is None
    # Files come along as copies (a new blob), keeping their origin.
    [attachment] = by_sender["ai"].attachments
    assert attachment.origin == "generated"
    assert attachment.blob.data == b"png"


async def test_fork_conversation_rejects_unfinished_ai_message(client, conversation_factory):
    conversation = await conversation_factory(
        title="Unfinished", messages=[{"sender": "ai", "content": ""}]
    )

    response = await client.post(
        f"/v1/conversations/{conversation['conversation_id']}/fork",
        json={"messageId": conversation["message_ids"][0]},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Cannot fork from an unfinished AI message."


async def test_fork_conversation_rejects_a_user_message_and_a_foreign_one(
    client, session_factory, conversation_factory
):
    branch = await _seed_branch(session_factory)
    other = await conversation_factory(title="Other", messages=[{"sender": "ai", "content": "x"}])
    url = f"/v1/conversations/{branch['conversation_id']}/fork"

    user_target = await client.post(url, json={"messageId": branch["user_message_id"]})
    foreign_target = await client.post(url, json={"messageId": other["message_ids"][0]})

    assert user_target.status_code == 400
    assert user_target.json()["detail"] == "Only AI messages can be used as a fork target."
    assert foreign_target.status_code == 400
    assert foreign_target.json()["detail"] == (
        "Fork target message does not belong to this conversation."
    )
