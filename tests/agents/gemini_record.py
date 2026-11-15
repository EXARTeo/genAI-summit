"""Record real Gemini runs of the nested test agent as replay fixtures (paid API).

NOT a test (pytest never collects it). Run by hand with the agents venv:

    mnamon\\agents\\.venv\\Scripts\\python tests/agents/gemini_record.py <scenario> [model]

It builds ``fixtures/gemini/agents/nested-demo`` through the real path
(``YamlDeepAgent`` -> ``build_deep_agent`` -> ``BaseAgent.astream``) on
``ChatGoogleGenerativeAI`` with ``GOOGLE_API_KEY`` from the repo-root ``.env``,
and records every raw ``(namespace, mode, payload)`` chunk the normalizer is
handed, per stream (a HITL pause is resumed with an approval on a fresh agent
seeded as the ``/resume`` route seeds it). The workspace is in-memory
(``StateBackend``) and the checkpointer a ``MemorySaver``; nothing else is
stubbed. Thought signatures are redacted, unused metadata dropped and a
"tasks" payload cut to what the normalizer reads (no node's full state), in
the encoding ``test_agui_gemini._decode`` reads back. Output:
``fixtures/gemini/nested_<scenario>_<model>.json``, replayed by
``test_agui_gemini_nested.py``.

The ``async*`` scenarios run the real ``TaskRunner`` over the in-memory task
store and fakeredis (``async_helpers``), building every task's node of the
tree the way the service does, approving a task's pause as soon as it waits,
and waking the orchestrator with each settled depth-1 task as the backend
does; every run of every task is its own recorded stream.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
FIXTURES = HERE / "fixtures" / "gemini"
AGENT_DIR = FIXTURES / "agents" / "nested-demo"


def _load_env() -> None:
    """The Gemini key and model from the repo-root .env (never printed)."""
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        key = key.strip()
        if sep and key in ("GOOGLE_API_KEY", "GEMINI_MODEL"):
            os.environ[key] = value.split("#", 1)[0].strip().strip('"')


_load_env()
sys.path.insert(0, str(HERE))
import conftest  # noqa: E402  (the suite's offline environment, minus the fake key)
import fakeredis.aioredis  # noqa: E402
import yaml  # noqa: E402
from async_helpers import FakeTaskStore, no_mcp, protocol_app  # noqa: E402
from deepagents.backends import StateBackend  # noqa: E402
from langchain_core.load import dumpd  # noqa: E402
from langchain_core.messages import BaseMessage  # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from langgraph.types import Command, Interrupt, Overwrite  # noqa: E402

from core.settings import settings  # noqa: E402
from harness.abstractions.agent_spec import AgentSpec  # noqa: E402
from harness.abstractions.yaml_agent import YamlDeepAgent  # noqa: E402
from harness.agui import normalizer as normalizer_module  # noqa: E402
from harness.async_tasks.events import TaskStreamPublisher  # noqa: E402
from harness.async_tasks.notification import to_human_message  # noqa: E402
from harness.async_tasks.runner import TaskRunner, set_task_runner, task_context  # noqa: E402
from harness.async_tasks.specs import TaskNode, decode_path  # noqa: E402
from harness.async_tasks.token import InheritedContext  # noqa: E402
from harness.checkpointer import store as checkpointer_store  # noqa: E402

KEEP_METADATA = ("langgraph_node", "checkpoint_ns", "ls_provider", "ls_model_name", "lc_source")
SIGNATURE = "<thought-signature>"

SCENARIOS: dict[str, str] = {
    "sync3": (
        "Is the Eiffel Tower 330 m tall? Delegate it to the researcher; it must have its "
        "checker verify the claim, and the checker must have its source-verifier verify the "
        "source. Then answer me."
    ),
    "siblings": (
        "In ONE turn, call the `task` tool twice in parallel: the researcher with "
        "'Is the Eiffel Tower 330 m tall?' (its checker and source-verifier must verify it) "
        "and the summarizer with 'the Eiffel Tower'. Then answer me."
    ),
    "async": (
        "Is the Eiffel Tower 330 m tall? Delegate it to the researcher in the background; it "
        "must have its checker verify the claim, and the checker must have its "
        "source-verifier verify the source. Do not check on the tasks: you are told when "
        "they finish. Then answer me."
    ),
    "async_hitl": (
        "Is the Eiffel Tower 330 m tall? Delegate it to the researcher in the background. The "
        "researcher must pass it to its checker, and the checker must write its verdict to "
        "/verdict.md with write_file (no further delegation). Do not check on or update the "
        "tasks and write no file yourself: you are told when they finish. Then answer me in "
        "one sentence."
    ),
    "hitl": (
        "Is the Eiffel Tower 330 m tall? Delegate it to the researcher. The researcher must "
        "pass it to its checker, and the checker must write its verdict to /verdict.md with "
        "write_file (no further delegation). Then answer me."
    ),
}


# --------------------------------------------------------------------------
# Encoding (what test_agui_gemini._decode reads)
# --------------------------------------------------------------------------
def _redact(obj: Any) -> Any:
    if isinstance(obj, list):
        return [_redact(item) for item in obj]
    if not isinstance(obj, dict):
        return obj
    out: dict[str, Any] = {}
    for key, value in obj.items():
        if key == "signature" and isinstance(value, str):
            out[key] = SIGNATURE
        elif key == "__gemini_function_call_thought_signatures__" and isinstance(value, dict):
            out[key] = dict.fromkeys(value, SIGNATURE)
        else:
            out[key] = _redact(value)
    return out


def encode(obj: Any, *, metadata: bool = False) -> Any:
    if isinstance(obj, BaseMessage):
        return {"__lc__": _redact(dumpd(obj))}
    if isinstance(obj, Interrupt):
        return {"__interrupt__": {"value": encode(obj.value), "id": obj.id}}
    if isinstance(obj, Overwrite):
        return {"__overwrite__": encode(obj.value)}
    if isinstance(obj, tuple):
        return {"__tuple__": [encode(item) for item in obj]}
    if isinstance(obj, list):
        return [encode(item) for item in obj]
    if isinstance(obj, dict):
        if metadata:
            return {k: v for k, v in obj.items() if k in KEEP_METADATA}
        return {str(k): encode(v) for k, v in obj.items()}
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if hasattr(obj, "model_dump"):
        return encode(obj.model_dump())
    return repr(obj)


def trim_task(payload: dict[str, Any]) -> dict[str, Any]:
    """A "tasks" payload as the normalizer reads it: a tools node's tool calls
    (without the state a call may be wrapped with); every node's full input
    state and result are dropped (the bulk of a recording, never read)."""
    out = {key: payload[key] for key in ("id", "name") if key in payload}
    if payload.get("name") == "tools" and isinstance(payload.get("input"), list):
        out["input"] = [
            {k: v for k, v in item.items() if k != "state"} if isinstance(item, dict) else item
            for item in payload["input"]
        ]
    return out


def encode_chunk(chunk: Any) -> Any:
    namespace, mode, payload = chunk
    ns = encode(tuple(namespace))
    if mode == "messages":
        msg, meta = payload
        return {"__tuple__": [ns, mode, {"__tuple__": [encode(msg), encode(meta, metadata=True)]}]}
    if mode == "tasks":
        return {"__tuple__": [ns, mode, trim_task(encode(payload))]}
    return {"__tuple__": [ns, mode, encode(payload)]}


# --------------------------------------------------------------------------
# Sync scenarios
# --------------------------------------------------------------------------
def _spec() -> AgentSpec:
    return AgentSpec.model_validate(
        yaml.safe_load((AGENT_DIR / "agent.yaml").read_text(encoding="utf-8"))
    )


def _agent(spec: AgentSpec, checkpointer: Any, run_id: str, thread_id: str) -> YamlDeepAgent:
    config = conftest.run_config(run_id=run_id, thread_id=thread_id)
    config["run_config"]["recursion_limit"] = 200
    agent = YamlDeepAgent(spec, AGENT_DIR, config=config)
    agent.checkpointer = checkpointer
    agent._build_composite_backend = lambda: StateBackend()
    return agent


async def record_sync(prompt: str) -> dict[str, Any]:
    settings.async_tasks.enabled = False
    spec = _spec()
    checkpointer = MemorySaver()
    run_id, thread_id = "nested-run", "nested-thread"
    normalizer_module.release_namespace_bindings(run_id)
    streams: list[dict[str, Any]] = []
    command: Command | None = None
    for _ in range(4):
        agent = _agent(spec, checkpointer, run_id, thread_id)
        seeded: list[Any] = []
        if command is not None:
            await agent.ensure_built()
            snapshot = await agent.compiled.aget_state(agent.run_config)
            seeded = list(snapshot.values.get("messages") or [])
        chunks: list[Any] = []
        handle = agent.agui_normalizer.handle_chunk

        def spy(chunk: Any, handle=handle, chunks=chunks) -> list[bytes]:
            chunks.append(encode_chunk(chunk))
            return handle(chunk)

        agent.agui_normalizer.handle_chunk = spy
        if seeded:
            agent.agui_normalizer.seed_pending_tasks(seeded)
        payload = {"messages": [{"role": "user", "content": prompt}]}
        frames = [f.decode("utf-8") async for f in agent.astream(payload, command=command)]
        if any('"RUN_ERROR"' in f for f in frames):
            raise RuntimeError(f"run failed: {frames[-1][:500]}")
        streams.append(
            {
                "actor": "",
                "thread_id": run_id,
                "resume": command is not None,
                "seed_messages": [encode(m) for m in seeded],
                "chunks": chunks,
            }
        )
        snapshot = await agent.compiled.aget_state(agent.run_config)
        if not snapshot.interrupts:
            break
        requests = (snapshot.interrupts[0].value or {}).get("action_requests") or [None]
        command = Command(resume={"decisions": [{"type": "approve"}] * len(requests)})
    normalizer_module.release_namespace_bindings(run_id)
    return {"prompt": prompt, "thread_id": run_id, "streams": streams}


# --------------------------------------------------------------------------
# Async scenario: the real TaskRunner over the in-memory store and fakeredis
# --------------------------------------------------------------------------
async def record_async(prompt: str) -> dict[str, Any]:
    settings.async_tasks.enabled = True
    spec = _spec()
    checkpointer = MemorySaver()
    store = FakeTaskStore()
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    runner = TaskRunner(store, TaskStreamPublisher(client=redis), mcp_session=no_mcp)
    streams: list[dict[str, Any]] = []

    def spy_on(agent: YamlDeepAgent, record: dict[str, Any]) -> None:
        handle = agent.agui_normalizer.handle_chunk

        def spy(chunk: Any) -> list[bytes]:
            record["chunks"].append(encode_chunk(chunk))
            return handle(chunk)

        agent.agui_normalizer.handle_chunk = spy

    async def build(task: Mapping[str, Any], run_id: str) -> YamlDeepAgent:
        config = {
            "context": task_context(task, run_id),
            "run_config": {"configurable": {"thread_id": task["task_id"]}, "recursion_limit": 200},
        }
        agent = YamlDeepAgent(spec, AGENT_DIR, config=config)
        agent.checkpointer = checkpointer
        agent._build_composite_backend = lambda: StateBackend()
        agent.async_task_node = TaskNode(
            task_id=task["task_id"],
            depth=int(task["depth"]),
            path=tuple(decode_path(task["subagent_path"])),
            client_id=task["client_id"],
            conversation_id=task["conversation_id"],
            root_run_id=task["root_run_id"],
            branch_thread_id=task["branch_thread_id"],
            agent_slug=task["agent_slug"],
            definition_version=task["definition_version"],
            inherited=InheritedContext.model_validate(task.get("context") or {}),
        )
        record = {
            "actor": "/".join(decode_path(task["subagent_path"])),
            "task_id": task["task_id"],
            "parent_task_id": task.get("parent_task_id"),
            "thread_id": run_id,
            "resume": (store.runs.get(run_id) or {}).get("kind") == "resume",
            "seed_messages": [],
            "chunks": [],
        }
        streams.append(record)
        spy_on(agent, record)
        return agent

    runner.build_agent = build  # type: ignore[method-assign]
    set_task_runner(runner)
    protocol_app()

    async def root_leg(run_id: str, payload: dict[str, Any]) -> None:
        agent = _agent(spec, checkpointer, run_id, "root-thread")
        record = {
            "actor": "",
            "task_id": None,
            "parent_task_id": None,
            "thread_id": run_id,
            "resume": False,
            "seed_messages": [],
            "chunks": [],
        }
        streams.append(record)
        spy_on(agent, record)
        frames = [f.decode("utf-8") async for f in agent.astream(payload)]
        if any('"RUN_ERROR"' in f for f in frames):
            raise RuntimeError(f"root run failed: {frames[-1][:500]}")

    async def settle() -> None:
        """Run the tree to rest, approving each task's pause as soon as it waits."""
        while True:
            waiting = [t for t in store.tasks.values() if t["status"] == "waiting"]
            for task in waiting:
                interrupts = await runner.pending_interrupts(task)
                await runner.resume(task, {str(i.id): {"decision": "approve"} for i in interrupts})
            if not waiting and not [j for j in runner._jobs if not j.done()]:
                return
            await asyncio.sleep(0.05)

    try:
        await root_leg("root-run-1", {"messages": [{"role": "user", "content": prompt}]})
        await asyncio.wait_for(settle(), 600)
        # The backend wakes the orchestrator with each settled depth-1 task's notification.
        for n, task in enumerate(
            [t for t in store.tasks.values() if t["parent_task_id"] is None], start=2
        ):
            item = await runner.outbox_item(task)
            message = to_human_message(item["notification"])
            await root_leg(f"root-run-{n}", {"messages": [message]})
        await asyncio.wait_for(settle(), 600)
    finally:
        await runner.shutdown()
        set_task_runner(None)
    tasks = [
        {k: task[k] for k in ("task_id", "parent_task_id", "name", "depth", "status")}
        for task in store.tasks.values()
    ]
    return {
        "prompt": prompt,
        "thread_id": "root-run-1",
        "tasks": tasks,
        "streams": [s for s in streams if s["chunks"]],
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main() -> None:
    scenario = sys.argv[1]
    model = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("GEMINI_MODEL", "")
    settings.gemini.model = model
    checkpointer_store.set_runtime_pool(object())
    if scenario.startswith("async"):
        data = asyncio.run(record_async(SCENARIOS[scenario]))
    else:
        data = asyncio.run(record_sync(SCENARIOS[scenario]))
    data["model"] = model
    out = FIXTURES / f"nested_{scenario}_{model.replace('gemini-', '').replace('.', '')}.json"
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"
    out.write_text(text, encoding="utf-8", newline="\n")
    print(out.name, sum(len(s["chunks"]) for s in data["streams"]), "chunks")


if __name__ == "__main__":
    main()
