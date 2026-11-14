"""Message routes: append (with attachments), finalize an AI placeholder,
like / dislike; and the total order of a conversation's messages."""

from __future__ import annotations

import base64
from datetime import datetime

from conftest import AGENT_SLUG, CLIENT_ID
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.database import ConversationTable, MessageTable


async def test_add_message_with_image_attachment_updates_conversation_summary(
    client, conversation_factory
):
    conversation = await conversation_factory(title="Message target")
    image_bytes = b"fake-image-bytes"

    response = await client.post(
        f"/v1/messages/{conversation['conversation_id']}",
        json={
            "sender": "user",
            "content": "Please review this screenshot",
            "attachments": [
                {
                    "name": "screenshot.png",
                    "mime": "image/png",
                    "dataB64": base64.b64encode(image_bytes).decode("ascii"),
                    "size": len(image_bytes),
                }
            ],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["message"]["content"] == "Please review this screenshot"
    assert payload["message"]["attachments"][0]["name"] == "screenshot.png"
    assert payload["message"]["attachments"][0]["data"] == base64.b64encode(image_bytes).decode(
        "ascii"
    )
    assert payload["summary"]["lastMessage"] == "Please review this screenshot"


async def test_add_message_under_a_parent(client, conversation_factory):
    conversation = await conversation_factory(
        title="Branching", messages=[{"sender": "user", "content": "Root"}]
    )
    root_id = conversation["message_ids"][0]

    response = await client.post(
        f"/v1/messages/{conversation['conversation_id']}",
        json={"sender": "ai", "content": "Reply", "parentMessageId": root_id},
    )

    assert response.status_code == 201
    assert response.json()["message"]["parentMessageId"] == root_id


async def test_add_message_refuses_a_parent_from_another_conversation(client, conversation_factory):
    target = await conversation_factory(title="Target")
    other = await conversation_factory(
        title="Other", messages=[{"sender": "user", "content": "Elsewhere"}]
    )

    response = await client.post(
        f"/v1/messages/{target['conversation_id']}",
        json={"sender": "user", "content": "Hi", "parentMessageId": other["message_ids"][0]},
    )

    assert response.status_code == 400


async def test_an_empty_ai_placeholder_is_accepted(client, conversation_factory):
    conversation = await conversation_factory(title="Placeholder")

    response = await client.post(
        f"/v1/messages/{conversation['conversation_id']}", json={"sender": "ai"}
    )

    assert response.status_code == 201
    assert response.json()["message"]["content"] is None


async def test_update_ai_message_persists_streaming_metadata(client, conversation_factory):
    conversation = await conversation_factory(
        title="AI placeholder", messages=[{"sender": "ai", "content": ""}]
    )
    message_id = conversation["message_ids"][0]

    response = await client.patch(
        f"/v1/messages/{conversation['conversation_id']}/{message_id}",
        json={
            "content": "Completed response",
            "thinking": ["Step 1", "Step 2"],
            "thinkingTime": 7,
            "error": False,
            "errorMessage": None,
            "rawEvents": [{"type": "token", "value": "Completed"}],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"]["content"] == "Completed response"
    assert payload["message"]["thinking"] == ["Step 1", "Step 2"]
    assert payload["message"]["thinkingTime"] == 7
    assert payload["message"]["rawEvents"] == [{"type": "token", "value": "Completed"}]
    assert payload["summary"]["lastMessage"] == "Completed response"


async def test_update_user_message_is_rejected(client, conversation_factory):
    conversation = await conversation_factory(
        title="User message", messages=[{"sender": "user", "content": "Original"}]
    )
    message_id = conversation["message_ids"][0]

    response = await client.patch(
        f"/v1/messages/{conversation['conversation_id']}/{message_id}",
        json={"content": "Not allowed", "rawEvents": []},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only AI messages can be updated."


async def test_like_and_dislike_toggle_message_feedback(client, conversation_factory):
    conversation = await conversation_factory(
        title="Feedback target", messages=[{"sender": "ai", "content": "Helpful answer"}]
    )
    base = f"/v1/messages/{conversation['conversation_id']}/{conversation['message_ids'][0]}"

    liked = await client.post(f"{base}/like")
    cleared_like = await client.post(f"{base}/like")
    disliked = await client.post(f"{base}/dislike")
    cleared_dislike = await client.post(f"{base}/dislike")

    assert liked.status_code == 200
    assert liked.json()["liked"] is True
    assert cleared_like.json()["liked"] is None
    assert disliked.json()["liked"] is False
    assert cleared_dislike.json()["liked"] is None


async def test_add_message_rejects_empty_user_payload(client, conversation_factory):
    conversation = await conversation_factory(title="Empty payload")

    response = await client.post(
        f"/v1/messages/{conversation['conversation_id']}",
        json={"sender": "user", "content": "", "attachments": []},
    )

    assert response.status_code == 422


async def test_add_message_rejects_invalid_attachment_base64(client, conversation_factory):
    conversation = await conversation_factory(title="Bad attachment")

    response = await client.post(
        f"/v1/messages/{conversation['conversation_id']}",
        json={
            "sender": "user",
            "content": "See attached",
            "attachments": [
                {"name": "broken.txt", "mime": "text/plain", "dataB64": "not-base64", "size": 10}
            ],
        },
    )

    assert response.status_code == 422


async def test_update_message_requires_content(client, conversation_factory):
    conversation = await conversation_factory(
        title="AI placeholder", messages=[{"sender": "ai", "content": ""}]
    )

    response = await client.patch(
        f"/v1/messages/{conversation['conversation_id']}/{conversation['message_ids'][0]}",
        json={"rawEvents": []},
    )

    assert response.status_code == 422


async def test_like_missing_message_returns_404(client, conversation_factory):
    conversation = await conversation_factory(title="Feedback target")

    response = await client.post(
        f"/v1/messages/{conversation['conversation_id']}/missing-message/like"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Message not found."


async def test_a_message_of_another_conversation_is_404(client, conversation_factory):
    target = await conversation_factory(title="Target")
    other = await conversation_factory(title="Other", messages=[{"sender": "ai", "content": "x"}])

    response = await client.post(
        f"/v1/messages/{target['conversation_id']}/{other['message_ids'][0]}/like"
    )

    assert response.status_code == 404


# --- order -----------------------------------------------------------------------
# A run writes the user message and its AI placeholder in one transaction, so
# their created_at can tie. The ids below make the AI message sort first by id:
# the case that used to come back reversed.

SAME_INSTANT = datetime(2026, 10, 8, 12, 0, 0)
AI_ID_SORTS_FIRST = "00000000-0000-0000-0000-000000000001"
USER_ID_SORTS_LAST = "ffffffff-ffff-ffff-ffff-ffffffffffff"


async def _senders_in_order(session_factory, rows: list[dict]) -> list[str]:
    async with session_factory() as session:
        conversation = ConversationTable(client_id=CLIENT_ID, agent_slug=AGENT_SLUG, title="order")
        session.add(conversation)
        await session.flush()
        for row in rows:
            session.add(MessageTable(conversation_id=conversation.id, **row))
        await session.commit()
        conversation_id = conversation.id
    async with session_factory() as session:
        loaded = await session.scalar(
            select(ConversationTable)
            .options(selectinload(ConversationTable.messages))
            .where(ConversationTable.id == conversation_id)
        )
        return [message.sender for message in loaded.messages]


async def test_a_tied_question_precedes_its_reply(session_factory):
    senders = await _senders_in_order(
        session_factory,
        [
            {
                "id": USER_ID_SORTS_LAST,
                "sender": "user",
                "content": "q",
                "created_at": SAME_INSTANT,
            },
            {
                "id": AI_ID_SORTS_FIRST,
                "sender": "ai",
                "content": "a",
                "parent_message_id": USER_ID_SORTS_LAST,
                "created_at": SAME_INSTANT,
            },
        ],
    )
    assert senders == ["user", "ai"]


async def test_the_timestamp_still_decides_when_it_differs(session_factory):
    senders = await _senders_in_order(
        session_factory,
        [
            {"sender": "ai", "content": "earlier", "created_at": datetime(2026, 10, 8, 11, 0, 0)},
            {"sender": "user", "content": "later", "created_at": SAME_INSTANT},
        ],
    )
    assert senders == ["ai", "user"]
