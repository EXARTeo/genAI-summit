"""Search: query cleaning, LIKE escaping, the ILIKE queries over the caller's
conversations / messages / files, and the ``GET /v1/search`` route."""

from __future__ import annotations

from conftest import CLIENT_ID, OTHER_CLIENT_ID
from sqlalchemy import select

from core.database import AttachmentTable, MessageTable
from utils.search import build_like_pattern, clean_search_query, search_workspace_data


async def _search(session_factory, query: str, *, limit: int = 20, client_id: str = CLIENT_ID):
    async with session_factory() as session:
        return await search_workspace_data(
            db=session, client_id=client_id, query=query, limit=limit
        )


# --- pure helpers -----------------------------------------------------------------


def test_clean_search_query_collapses_whitespace():
    assert clean_search_query("  hello   world\n\tfoo  ") == "hello world foo"


def test_clean_search_query_empty_and_none():
    assert clean_search_query("") == ""
    assert clean_search_query("   ") == ""
    assert clean_search_query(None) == ""


def test_build_like_pattern_wraps_with_percent():
    assert build_like_pattern("term") == "%term%"


def test_build_like_pattern_escapes_wildcards_and_backslash():
    # Backslash first, so the escapes of % and _ are not doubled.
    assert build_like_pattern("a%b_c\\d") == "%a\\%b\\_c\\\\d%"


# --- search_workspace_data ----------------------------------------------------------


async def test_search_matches_conversation_title(session_factory, conversation_factory):
    await conversation_factory(title="Quarterly Finance Review")
    await conversation_factory(title="Unrelated topic")

    results = await _search(session_factory, "finance")

    titles = [r.title for r in results if r.kind == "conversation"]
    assert titles == ["Quarterly Finance Review"]


async def test_search_matches_message_content(session_factory, conversation_factory):
    await conversation_factory(
        title="Chat", messages=[{"sender": "user", "content": "Tell me about photosynthesis"}]
    )

    results = await _search(session_factory, "photosynthesis")

    message_hits = [r for r in results if r.kind == "message"]
    assert message_hits
    assert message_hits[0].subtitle == "You message"
    assert message_hits[0].title == "Chat"


async def test_search_matches_file_attachment(session_factory, conversation_factory):
    created = await conversation_factory(
        title="With file", messages=[{"sender": "user", "content": "see attached"}]
    )
    async with session_factory() as session:
        message_id = await session.scalar(
            select(MessageTable.id).where(
                MessageTable.conversation_id == created["conversation_id"]
            )
        )
        session.add(
            AttachmentTable(
                message_id=message_id,
                file_name="budget_report.xlsx",
                mime_type="application/vnd.ms-excel",
            )
        )
        await session.commit()

    results = await _search(session_factory, "budget_report")

    file_hits = [r for r in results if r.kind == "file"]
    assert file_hits
    assert file_hits[0].title == "budget_report.xlsx"
    assert file_hits[0].snippet == "application/vnd.ms-excel"
    assert file_hits[0].conversationId == created["conversation_id"]


async def test_search_excludes_archived_conversations(session_factory, conversation_factory):
    await conversation_factory(
        title="Archived rocket notes",
        is_archived=True,
        messages=[{"sender": "user", "content": "rocket"}],
    )

    assert await _search(session_factory, "rocket") == []


async def test_search_never_returns_another_clients_data(session_factory, conversation_factory):
    await conversation_factory(
        title="Secret rocket plans",
        client_id=OTHER_CLIENT_ID,
        messages=[{"sender": "user", "content": "rocket fuel"}],
    )

    assert await _search(session_factory, "rocket") == []
    assert len(await _search(session_factory, "rocket", client_id=OTHER_CLIENT_ID)) == 2


async def test_search_respects_limit(session_factory, conversation_factory):
    for i in range(5):
        await conversation_factory(title=f"alpha topic {i}")

    assert len(await _search(session_factory, "alpha", limit=2)) == 2


async def test_search_underscore_is_literal_not_wildcard(session_factory, conversation_factory):
    await conversation_factory(title="report_2026 summary")
    await conversation_factory(title="reportX2026 other")

    results = await _search(session_factory, "report_2026")

    titles = {r.title for r in results if r.kind == "conversation"}
    assert titles == {"report_2026 summary"}


async def test_search_percent_is_literal_not_wildcard(session_factory, conversation_factory):
    await conversation_factory(title="100% done")
    await conversation_factory(title="100 percent")

    results = await _search(session_factory, "100%")

    assert {r.title for r in results if r.kind == "conversation"} == {"100% done"}


# --- GET /v1/search ------------------------------------------------------------------


async def test_search_route_returns_empty_for_blank_query(client):
    response = await client.get("/v1/search?q=   ")

    assert response.status_code == 200
    assert response.json() == []


async def test_search_route_returns_matches(client, conversation_factory):
    await conversation_factory(title="Marketing roadmap")

    response = await client.get("/v1/search?q=marketing&limit=10")

    assert response.status_code == 200
    body = response.json()
    assert any(item["title"] == "Marketing roadmap" for item in body)
    assert all(item["agentSlug"] == "test-agent" for item in body)


async def test_search_route_bounds_its_inputs(client):
    too_long = await client.get("/v1/search", params={"q": "x" * 201})
    too_many = await client.get("/v1/search?q=x&limit=51")

    assert too_long.status_code == 422
    assert too_many.status_code == 422
