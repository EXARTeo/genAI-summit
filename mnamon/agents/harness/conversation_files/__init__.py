"""A conversation's files, stored in ``agent_runtime``.

Everything a conversation owns is rows, and lives exactly as long as the
database does:

* ``store`` — the tables: content-addressed, encrypted blobs per client, and
  the conversation's paths that name them.
* ``inputs`` — ``/conversation/input/``: the uploads the run request carries
  inline, written into the store before the run starts.
* ``files`` — one run's view of the store; ``backend`` — that view as the
  deepagents filesystem behind ``/conversation/``, ``/large_tool_results/``
  and ``/conversation_history/``.
* ``paths`` — the one normaliser every path goes through; ``cipher`` — the
  checkpointer's AES key and cipher, reused for the bytes.
"""

from harness.conversation_files.backend import ConversationFilesBackend
from harness.conversation_files.files import ConversationFiles
from harness.conversation_files.store import ConversationFileStore

__all__ = [
    "ConversationFileStore",
    "ConversationFiles",
    "ConversationFilesBackend",
]
