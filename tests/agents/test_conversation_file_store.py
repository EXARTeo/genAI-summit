"""``ConversationFileStore``: a conversation's files as rows.

Pinned here, without a database:

* the **cipher**: bytes go through the checkpointer's key and cipher, plaintext
  without a key, and turning encryption on keeps older plaintext blobs
  readable;
* the **contract** every caller relies on (write-once ``create``, ``replace``,
  a locked ``edit``, prefix listing that never crosses clients or
  conversations, file/directory conflicts), run against the in-memory twin
  from ``conftest`` that the other suites use, so the twin cannot drift from
  what the callers expect;
* the **path rule** the table's CHECK constraint mirrors: uploads under
  ``/conversation/input/`` are storable rows now, anything outside the three
  mounts is not.
"""

from __future__ import annotations

import re

import pytest
from conftest import CLIENT_ID, OTHER_CLIENT_ID
from langgraph.checkpoint.serde.encrypted import EncryptedSerializer
from pydantic import SecretStr

from core.settings import settings
from harness.conversation_files import paths
from harness.conversation_files import store as store_module
from harness.conversation_files.cipher import FileCipher, get_file_cipher

KEY = b"0123456789abcdef0123456789abcdef"


def _cipher(key: bytes | None) -> FileCipher:
    if key is None:
        return FileCipher(None)
    return FileCipher(EncryptedSerializer.from_pycryptodome_aes(key=key).cipher)


@pytest.fixture
def fresh_cipher_cache():
    """``get_file_cipher`` is process-wide; a test that changes the key must not leak it."""
    get_file_cipher.cache_clear()
    yield
    get_file_cipher.cache_clear()


# ---------------------------------------------------------------------------
# The cipher
# ---------------------------------------------------------------------------
def test_bytes_round_trip_through_the_checkpointers_cipher():
    cipher = _cipher(KEY)
    name, stored = cipher.encrypt(b"quarterly numbers")

    assert name == "aes"
    assert b"quarterly" not in stored
    assert cipher.decrypt(name, stored) == b"quarterly numbers"


def test_without_a_key_bytes_are_stored_as_they_are_and_stay_readable():
    plain, keyed = _cipher(None), _cipher(KEY)

    assert plain.encrypt(b"dev") == ("none", b"dev")
    # Turning encryption on keeps the older plaintext blobs readable.
    assert keyed.decrypt("none", b"dev") == b"dev"
    with pytest.raises(RuntimeError, match="LANGGRAPH_AES_KEY"):
        plain.decrypt(*keyed.encrypt(b"secret"))


def test_the_cipher_uses_the_checkpointer_key(monkeypatch, fresh_cipher_cache):
    monkeypatch.setattr(settings.checkpointer, "aes_key", SecretStr(KEY.decode()))
    assert get_file_cipher().encrypted

    get_file_cipher.cache_clear()
    monkeypatch.setattr(settings.checkpointer, "aes_key", SecretStr("too-short"))
    with pytest.raises(ValueError, match="16, 24, or 32"):
        get_file_cipher()


def test_no_key_means_no_encryption(monkeypatch, fresh_cipher_cache):
    monkeypatch.setattr(settings.checkpointer, "aes_key", SecretStr(""))
    assert not get_file_cipher().encrypted


# ---------------------------------------------------------------------------
# The contract (the in-memory twin every other suite runs on)
# ---------------------------------------------------------------------------
async def test_create_writes_once(memory_file_store):
    store = memory_file_store
    path = "/conversation/output/a.md"

    assert await store.create(CLIENT_ID, "c1", path, b"one", agent_slug="assistant") == "ok"
    assert await store.create(CLIENT_ID, "c1", path, b"two", agent_slug="assistant") == "exists"
    assert await store.read(CLIENT_ID, "c1", path) == b"one"


async def test_files_and_directories_cannot_collide(memory_file_store):
    store = memory_file_store
    await store.create(CLIENT_ID, "c1", "/conversation/notes", b"file", agent_slug="a")
    await store.create(CLIENT_ID, "c1", "/conversation/drafts/v1.md", b"d", agent_slug="a")

    under_a_file = await store.create(
        CLIENT_ID, "c1", "/conversation/notes/x.md", b"x", agent_slug="a"
    )
    over_a_folder = await store.replace(
        CLIENT_ID, "c1", "/conversation/drafts", b"x", agent_slug="a"
    )

    assert under_a_file == "parent_is_file"
    assert over_a_folder == "is_directory"


async def test_replace_and_edit_change_the_bytes(memory_file_store):
    store = memory_file_store
    path = "/conversation/output/a.md"
    await store.create(CLIENT_ID, "c1", path, b"v1", agent_slug="assistant")

    assert await store.replace(CLIENT_ID, "c1", path, b"v2", agent_slug="writer") == "ok"
    assert await store.edit(CLIENT_ID, "c1", path, lambda b: b + b"!", agent_slug="assistant")
    missing = "/conversation/output/none.md"
    assert not await store.edit(CLIENT_ID, "c1", missing, lambda b: b, agent_slug="assistant")

    entry = await store.stat(CLIENT_ID, "c1", path)
    assert await store.read(CLIENT_ID, "c1", path) == b"v2!"
    assert (entry.size, entry.agent_slug) == (3, "assistant")


async def test_listing_is_by_prefix_and_never_crosses_clients_or_conversations(
    memory_file_store,
):
    store = memory_file_store
    for conversation, client, path in [
        ("c1", CLIENT_ID, "/conversation/output/a.md"),
        ("c1", CLIENT_ID, "/conversation/output/sub/b.md"),
        ("c1", CLIENT_ID, "/conversation/output.md"),  # a sibling, not under output/
        ("c1", CLIENT_ID, "/large_tool_results/call-1"),
        ("c2", CLIENT_ID, "/conversation/output/other.md"),
        ("c3", OTHER_CLIENT_ID, "/conversation/output/theirs.md"),
    ]:
        await store.create(client, conversation, path, path.encode(), agent_slug="assistant")

    under_output = [e.path for e in await store.list_files(CLIENT_ID, "c1", "/conversation/output")]

    assert under_output == ["/conversation/output/a.md", "/conversation/output/sub/b.md"]
    assert len(await store.list_files(CLIENT_ID, "c1")) == 4
    assert await store.read(OTHER_CLIENT_ID, "c1", "/conversation/output/a.md") is None


async def test_read_many_returns_only_what_exists(memory_file_store):
    store = memory_file_store
    await store.create(CLIENT_ID, "c1", "/conversation/a.md", b"a", agent_slug="assistant")

    found = await store.read_many(CLIENT_ID, "c1", ["/conversation/a.md", "/conversation/nope"])

    assert found == {"/conversation/a.md": b"a"}


# ---------------------------------------------------------------------------
# What may be a row
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "path",
    [
        "/conversation/input/upload.png",
        "/conversation/output/report.md",
        "/conversation/notes.md",
        "/large_tool_results/call-1",
        "/conversation_history/part-1.md",
    ],
)
def test_the_mounts_and_the_uploads_folder_are_storable(path):
    assert paths.is_storable(path)
    # The table's CHECK constraint says the same, so a refusal is never a
    # constraint violation the caller did not see coming.
    assert re.match(_table_path_check(), path)


@pytest.mark.parametrize("path", ["/conversation", "/elsewhere/x", "/large_tool_results", "/"])
def test_anything_else_is_not(path):
    assert not paths.is_storable(path)
    assert not re.match(_table_path_check(), path)


def _table_path_check() -> str:
    """The regex of ``conversation_files_path_ck``, read from the store's own DDL."""
    ddl = " ".join(store_module._DDL)
    [pattern] = re.findall(r"path ~ '([^']+)'", ddl)
    return pattern
