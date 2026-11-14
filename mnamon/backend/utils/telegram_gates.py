"""HITL gates on Telegram: announce every gate with inline buttons
(Approve / Reject / Open in app) and turn a button press into the same
decision the UI records.

Gates announced:

* **audit gate** (``scenarios``, ``datasets``): an audit moves to
  ``waiting_approval``; Approve/Reject = ``POST /v1/audits/{id}/approvals``
  logic (``record_approval``), which is what resumes the pipeline.
* **public dataset pick**: a ``public_dataset_candidates`` artifact is
  proposed; one button per top candidate (sets ``data.selected``, approves).
* **regulation change**: reg-memory POSTs a RegChange; Accept = activate the
  candidate release (``decide_change``), Reject = mark it rejected.
* **chat tool approval**: a chat run pauses on a ``HITL_INTERRUPT`` with
  ``action_requests``; Approve/Reject = the inference resume
  (``request_run_resume``, the same queue ``/v1/inference/runs/{id}/resume`` uses).

Reject asks for a reason first: reason-category buttons, then a ForceReply for
a free-text comment (``-`` skips it). Only allow-listed chats
(``TELEGRAM_CHAT_ID``) can decide; a gate decided anywhere (UI or another
chat) answers "already decided by X". Decisions are recorded as
``telegram:<username>``; the message is edited to show who decided.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import (
    ApprovalTable,
    AuditArtifactTable,
    AuditTable,
    MessageTable,
    SessionLocal,
    SystemTable,
    TelegramPromptTable,
)
from core.logging import get_logger
from core.settings import settings
from schema.audits import ApprovalIn
from utils.audit_pipeline import forward_gate_decision
from utils.audits import record_approval
from utils.inference_runs import request_run_resume
from utils.regulation import decide_change
from utils.telegram import TelegramClient, button, get_bot, inline_keyboard, url_button

logger = get_logger(__name__)

REASONS = (
    ("wrong_fact", "Wrong fact"),
    ("wrong_interpretation", "Wrong interpretation"),
    ("missing_info", "Missing info"),
    ("wrong_metric", "Wrong metric"),
    ("unrealistic_data", "Unrealistic data"),
    ("org_policy", "Org policy"),
    ("other", "Other"),
)
GATE_STEP = {"scenarios": "approve_scenarios", "datasets": "approve_datasets"}
GATE_LABEL = {"scenarios": "Approve test scenarios", "datasets": "Approve synthetic datasets"}
GATE_REVIEWS = {
    "scenarios": ("scenario_analysis", "scenarios"),
    "datasets": ("dataset_analysis", "generation_spec"),
}
PUBLIC_DATASET_KIND = "public_dataset_candidates"
SKIP_COMMENT = {"-", "/skip", "skip"}


class AlreadyDecided(Exception):
    def __init__(self, by: str | None) -> None:
        super().__init__(by or "someone")
        self.by = by or "someone"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def app_url(path: str) -> str:
    return f"{settings.telegram.app_public_url.rstrip('/')}{path}"


def gate_for_stage(stage: str) -> str:
    s = (stage or "").lower()
    if "public" in s:
        return "public_data"
    if "scenario" in s:
        return "scenarios"
    if "dataset" in s or "spec" in s or "generate" in s:
        return "datasets"
    return s or "gate"


def allowed_chat(chat_id: Any) -> bool:
    return str(chat_id) in settings.telegram.chat_ids


def actor_of(user: dict[str, Any] | None) -> str:
    user = user or {}
    name = user.get("username") or user.get("first_name") or user.get("id") or "unknown"
    return f"telegram:{name}"


# ---- announcing --------------------------------------------------------------


def _keyboard(
    prompt_id: str,
    link: str,
    *,
    approve: str = "Approve",
    picks: list[str] | None = None,
    reject: str = "Reject",
) -> dict[str, Any]:
    rows: list[list[dict[str, str]]] = []
    if picks:
        rows += [
            [button(f"Use {label}"[:60], f"g:{prompt_id}:p{i}")] for i, label in enumerate(picks)
        ]
    else:
        rows.append([button(f"✅ {approve}", f"g:{prompt_id}:a")])
    rows[-1].append(button(f"❌ {reject}", f"g:{prompt_id}:r"))
    open_button = url_button("Open in app", link)
    if open_button:
        rows.append([open_button])
    return inline_keyboard(rows)


async def announce(
    db: AsyncSession,
    *,
    kind: str,
    key: str,
    text: str,
    link: str,
    data: dict[str, Any],
    approve: str = "Approve",
    reject: str = "Reject",
    picks: list[str] | None = None,
) -> TelegramPromptTable | None:
    """Send a gate to every allow-listed chat, once per open gate (``key``)."""
    bot = get_bot()
    if bot is None or not settings.telegram.chat_ids:
        return None
    existing = await db.scalar(
        select(TelegramPromptTable).where(
            TelegramPromptTable.key == key, TelegramPromptTable.status == "open"
        )
    )
    if existing is not None:
        return existing
    prompt = TelegramPromptTable(
        id=secrets.token_hex(5),
        kind=kind,
        key=key,
        status="open",
        data={**data, "text": text, "link": link},
        messages=[],
    )
    full_text = f"{text}\n{link}"
    markup = _keyboard(prompt.id, link, approve=approve, picks=picks, reject=reject)
    sent = []
    for chat_id in settings.telegram.chat_ids:
        message = await bot.send_message(chat_id, full_text, markup)
        if message:
            sent.append({"chat_id": chat_id, "message_id": message.get("message_id")})
    prompt.messages = sent
    db.add(prompt)
    await db.flush()
    logger.info("telegram_gate_sent", "Gate sent to Telegram", kind=kind, chats=len(sent))
    return prompt


async def _artifacts(db: AsyncSession, audit_id: str) -> list[AuditArtifactTable]:
    rows = await db.scalars(
        select(AuditArtifactTable)
        .where(AuditArtifactTable.audit_id == audit_id, AuditArtifactTable.status != "superseded")
        .order_by(AuditArtifactTable.created_at, AuditArtifactTable.version)
    )
    return list(rows.all())


def _key_numbers(gate: str, artifacts: list[AuditArtifactTable]) -> list[str]:
    by_kind: dict[str, dict[str, Any]] = {a.kind: a.data or {} for a in artifacts}
    out: list[str] = []
    scen = by_kind.get("scenarios", {})
    analysis = by_kind.get("scenario_analysis", {})
    dataset = by_kind.get("dataset_analysis", {})
    if gate == "scenarios":
        if isinstance(scen.get("scenarios"), list):
            out.append(f"{len(scen['scenarios'])} scenarios")
        if isinstance(analysis.get("risks"), list):
            out.append(f"{len(analysis['risks'])} risks")
        if isinstance(analysis.get("notTestable"), list):
            out.append(f"{len(analysis['notTestable'])} not testable")
    if gate == "datasets":
        gates = dataset.get("gates") if isinstance(dataset.get("gates"), dict) else {}
        statuses = [str((g or {}).get("status")) for g in gates.values() if isinstance(g, dict)]
        if statuses:
            out.append(f"failed gates {statuses.count('fail')}/{len(statuses)}")
            if statuses.count("warn"):
                out.append(f"{statuses.count('warn')} warnings")
        if dataset.get("rows"):
            out.append(f"{dataset['rows']} rows")
    findings = sum(1 for a in artifacts if a.kind == "finding")
    if findings:
        out.append(f"{findings} findings")
    return out[:3]


async def notify_audit_gate(db: AsyncSession, audit: AuditTable) -> TelegramPromptTable | None:
    """The audit waits at a gate: announce it (once)."""
    if get_bot() is None:
        return None
    gate = gate_for_stage(audit.stage)
    artifacts = await _artifacts(db, audit.id)
    if gate == "public_data":
        candidates = [a for a in artifacts if a.kind == PUBLIC_DATASET_KIND]
        return await notify_public_dataset(db, audit, candidates[-1]) if candidates else None
    system = await db.get(SystemTable, audit.system_id)
    reviewed = [a for a in artifacts if a.kind in GATE_REVIEWS.get(gate, ())]
    artifact = next(
        (a for kind in GATE_REVIEWS.get(gate, ()) for a in reversed(reviewed) if a.kind == kind),
        None,
    )
    numbers = _key_numbers(gate, artifacts)
    system_name = (audit.data or {}).get("systemName") or (
        system.name if system else audit.system_id
    )
    text = "\n".join(
        [
            f"⏸ {system_name} ({audit.system_id}) is waiting for you",
            f"Gate: {GATE_LABEL.get(gate, gate)}",
            *([" · ".join(numbers)] if numbers else []),
            f"Audit {audit.id[:8]}",
        ]
    )
    step = GATE_STEP.get(gate, audit.stage)
    return await announce(
        db,
        kind="audit_gate",
        key=f"audit:{audit.id}:{gate}",
        text=text,
        link=app_url(f"/audits/{audit.id}?step={step}"),
        data={"audit_id": audit.id, "gate": gate, "artifact_id": artifact.id if artifact else None},
    )


async def notify_public_dataset(
    db: AsyncSession, audit: AuditTable, artifact: AuditArtifactTable
) -> TelegramPromptTable | None:
    """The agent proposes public datasets: the human picks one."""
    if get_bot() is None:
        return None
    all_candidates = [
        c for c in (artifact.data or {}).get("candidates") or [] if isinstance(c, dict)
    ]
    candidates = all_candidates[:3]
    system = await db.get(SystemTable, audit.system_id)
    lines = [
        f"⏸ {(system.name if system else audit.system_id)}: pick a public reference dataset",
        f"Plugin: {artifact.name} · {len(all_candidates)} candidates",
    ]
    for i, c in enumerate(candidates, 1):
        score = c.get("score")
        lines.append(
            f"{i}. {c.get('name') or c.get('id')}"
            + (f" (score {score:.2f})" if isinstance(score, int | float) else "")
            + (f", {c['n_rows']} rows" if c.get("n_rows") else "")
        )
    return await announce(
        db,
        kind="public_dataset",
        key=f"audit:{audit.id}:public_data",
        text="\n".join(lines),
        link=app_url(f"/audits/{audit.id}?step=find_public_data"),
        data={
            "audit_id": audit.id,
            "gate": "public_data",
            "artifact_id": artifact.id,
            "candidates": [str(c.get("id")) for c in candidates],
        },
        picks=[f"#{i} {c.get('name') or c.get('id')}" for i, c in enumerate(candidates, 1)],
    )


async def notify_regulation_change(
    db: AsyncSession, change: dict[str, Any]
) -> TelegramPromptTable | None:
    if get_bot() is None:
        return None
    items = change.get("items") or []
    impacted = change.get("impacted_requirements") or []
    types = change.get("change_types") or {}
    text = "\n".join(
        [
            "📜 Regulation change detected",
            f"{change['id']}: kb {change.get('from_kb_version') or '-'}"
            f" → {change.get('to_kb_version')}",
            str(change.get("summary") or "")[:300],
            f"{len(items)} items · {len(impacted)} requirements affected"
            + (f" · {', '.join(f'{k} {v}' for k, v in types.items())}" if types else ""),
        ]
    )
    return await announce(
        db,
        kind="regulation_change",
        key=f"regchange:{change['id']}",
        text=text,
        link=app_url(f"/regulation?tab=changes&change={change['id']}"),
        data={"change_id": change["id"]},
        approve=f"Accept kb {change.get('to_kb_version')}",
    )


async def notify_chat_interrupt(run_id: str, interrupt_id: str, value: Any) -> None:
    """Interrupt hook: a chat run waits for a tool approval."""
    if get_bot() is None:
        return
    interrupt = value.get("interrupt") if isinstance(value, dict) else None
    inner = interrupt.get("value") if isinstance(interrupt, dict) else None
    actions = inner.get("action_requests") if isinstance(inner, dict) else None
    if not isinstance(actions, list) or not actions:
        return  # ask_user and other questions need typed answers: the UI only
    try:
        async with SessionLocal() as db:
            run = await db.get(MessageTable, run_id)
            conversation_id = run.conversation_id if run else ""
            names = ", ".join(str(a.get("name")) for a in actions if isinstance(a, dict))
            first = actions[0] if isinstance(actions[0], dict) else {}
            args = str(first.get("args") or "")[:200]
            text = "\n".join(
                [
                    "🛠 The agent asks to run a tool",
                    f"Tool: {names}",
                    *([f"Args: {args}"] if args else []),
                ]
            )
            await announce(
                db,
                kind="chat_hitl",
                key=f"chat:{run_id}:{interrupt_id}",
                text=text,
                link=app_url(f"/chat/{conversation_id}"),
                data={"run_id": run_id, "interrupt_id": interrupt_id, "actions": len(actions)},
            )
            await db.commit()
    except Exception:
        logger.warning("telegram_chat_notify_failed", "Chat HITL notify failed", exc_info=True)


async def safe(coro: Any) -> None:
    """Run a notifier best effort: Telegram never breaks the caller."""
    try:
        await coro
    except Exception:
        logger.warning("telegram_notify_failed", "Telegram notify failed", exc_info=True)


# ---- deciding ----------------------------------------------------------------


async def _decided_elsewhere(db: AsyncSession, prompt: TelegramPromptTable) -> str | None:
    """Who decided this gate outside Telegram, if anyone."""
    data = prompt.data or {}
    if prompt.kind in ("audit_gate", "public_dataset"):
        query = select(ApprovalTable).where(
            ApprovalTable.audit_id == data.get("audit_id"),
            ApprovalTable.at >= prompt.created_at,
        )
        if prompt.kind == "public_dataset":
            query = query.where(ApprovalTable.artifact_id == data.get("artifact_id"))
        else:
            query = query.where(ApprovalTable.gate == data.get("gate"))
        row = await db.scalar(query.order_by(ApprovalTable.at.desc()))
        return row.decided_by if row else None
    return None


async def _apply(
    db: AsyncSession,
    prompt: TelegramPromptTable,
    decision: str,
    actor: str,
    *,
    category: str | None = None,
    comment: str | None = None,
    pick: int | None = None,
) -> None:
    """Record the decision exactly like the UI does (and so resume the agent)."""
    data = prompt.data or {}
    approve = decision == "approve"
    if prompt.kind in ("audit_gate", "public_dataset"):
        audit = await db.get(AuditTable, data.get("audit_id"))
        if audit is None:
            raise AlreadyDecided("nobody (the audit is gone)")
        artifact_id = data.get("artifact_id")
        edits: dict[str, Any] = {}
        candidates = data.get("candidates") or []
        if pick is not None and artifact_id and pick < len(candidates):
            edits["selected"] = candidates[pick]
            artifact = await db.get(AuditArtifactTable, artifact_id)
            if artifact is not None:
                artifact.data = {**(artifact.data or {}), "selected": candidates[pick]}
        payload = ApprovalIn(
            gate=str(data.get("gate")),
            decision="approved" if approve else "rejected",
            artifactId=artifact_id,
            reasonCategory=category,
            comment=comment or ("Approved via Telegram" if approve else None),
            edits=edits,
        )
        approval, _artifact = await record_approval(db, audit, payload, actor)
        # Same as POST /v1/audits/{id}/approvals: the waiting pipeline resumes.
        await forward_gate_decision(audit, approval)
    elif prompt.kind == "regulation_change":
        try:
            await decide_change(
                db,
                str(data["change_id"]),
                "accepted" if approve else "rejected",
                actor,
                reason=" — ".join(x for x in (category, comment) if x) or None,
            )
        except HTTPException as exc:
            if exc.status_code == 409:
                raise AlreadyDecided(str(exc.detail).rsplit(" by ", 1)[-1].rstrip(".")) from exc
            raise
    elif prompt.kind == "chat_hitl":
        run = await db.get(MessageTable, data.get("run_id"))
        if run is None:
            raise AlreadyDecided("nobody (the run is gone)")
        reason = " — ".join(x for x in (category, comment) if x) or None
        verb = "approve" if approve else "reject"
        resume: dict[str, Any] = {
            "decision": verb,
            "reason": reason,
            "value": None,
            "interrupt_id": data.get("interrupt_id"),
            "decisions": None,
        }
        if int(data.get("actions") or 1) > 1:
            resume["decisions"] = [{"decision": verb, "reason": reason}] * int(data["actions"])
        outcome = request_run_resume(run, resume)
        if not outcome.accepted:
            raise AlreadyDecided("the app (no longer pending)")
    prompt.status = "decided"
    prompt.decision = "approved" if approve else "rejected"
    prompt.decided_by = actor
    prompt.decided_at = _now()
    await db.flush()


def _outcome_line(
    decision: str, by: str, category: str | None = None, comment: str | None = None
) -> str:
    who = by.replace("telegram:", "@", 1) if by.startswith("telegram:") else by
    if decision == "approved":
        return f"✅ Approved by {who}"
    why = ": " + " — ".join(x for x in (category, comment) if x) if (category or comment) else ""
    return f"❌ Rejected by {who}{why}"


async def _close_messages(bot: TelegramClient, prompt: TelegramPromptTable, line: str) -> None:
    data = prompt.data or {}
    text = f"{data.get('text', '')}\n{data.get('link', '')}\n\n{line}"
    for m in prompt.messages or []:
        await bot.edit_message_text(m["chat_id"], m["message_id"], text)


async def close_prompts(db: AsyncSession, key: str, decision: str, by: str) -> None:
    """A gate was decided in the app: mark its Telegram prompt and edit the message."""
    bot = get_bot()
    if bot is None:
        return
    rows = (
        await db.scalars(
            select(TelegramPromptTable).where(
                TelegramPromptTable.key == key, TelegramPromptTable.status == "open"
            )
        )
    ).all()
    for prompt in rows:
        prompt.status = "decided"
        prompt.decision = decision
        prompt.decided_by = by
        prompt.decided_at = _now()
        await _close_messages(bot, prompt, _outcome_line(decision, by) + " (in the app)")
    await db.flush()


async def _finish(
    db: AsyncSession,
    bot: TelegramClient,
    prompt: TelegramPromptTable,
    callback_id: str | None,
    line: str,
) -> None:
    await db.commit()
    await _close_messages(bot, prompt, line)
    if callback_id:
        await bot.answer_callback(callback_id, line)


async def _decide(
    db: AsyncSession,
    bot: TelegramClient,
    prompt: TelegramPromptTable,
    decision: str,
    actor: str,
    callback_id: str | None,
    **kwargs: Any,
) -> None:
    prompt_id = prompt.id
    try:
        await _apply(db, prompt, decision, actor, **kwargs)
    except HTTPException as exc:
        await db.rollback()
        if callback_id:
            await bot.answer_callback(callback_id, f"Could not record it: {exc.detail}")
        return
    except AlreadyDecided as exc:
        await db.rollback()
        fresh = await db.get(TelegramPromptTable, prompt_id)
        if fresh is not None:
            fresh.status = "decided"
            fresh.decided_by = fresh.decided_by or exc.by
            fresh.decided_at = _now()
            await db.commit()
        if callback_id:
            await bot.answer_callback(callback_id, f"Already decided by {exc.by}")
        return
    line = _outcome_line(
        prompt.decision or "", actor, kwargs.get("category"), kwargs.get("comment")
    )
    await _finish(db, bot, prompt, callback_id, line)
    logger.info(
        "telegram_gate_decided",
        "Gate decided on Telegram",
        kind=prompt.kind,
        decision=prompt.decision,
    )


async def _on_callback(db: AsyncSession, bot: TelegramClient, query: dict[str, Any]) -> None:
    callback_id = str(query.get("id"))
    message = query.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    if not allowed_chat(chat_id):
        logger.warning("telegram_unauthorized_chat", "Callback from a chat not on the allow-list")
        await bot.answer_callback(callback_id, "This chat may not decide gates.")
        return
    parts = str(query.get("data") or "").split(":")
    if len(parts) != 3 or parts[0] != "g":
        await bot.answer_callback(callback_id, "Unknown button.")
        return
    _, prompt_id, action = parts
    prompt = await db.get(TelegramPromptTable, prompt_id)
    if prompt is None:
        await bot.answer_callback(callback_id, "Unknown gate.")
        return
    if prompt.status != "open":
        await bot.answer_callback(callback_id, f"Already decided by {prompt.decided_by}")
        return
    elsewhere = await _decided_elsewhere(db, prompt)
    if elsewhere:
        prompt.status, prompt.decided_by, prompt.decided_at = "decided", elsewhere, _now()
        await db.commit()
        await _close_messages(bot, prompt, f"Already decided by {elsewhere}")
        await bot.answer_callback(callback_id, f"Already decided by {elsewhere}")
        return
    actor = actor_of(query.get("from"))
    if action == "a":
        await _decide(db, bot, prompt, "approve", actor, callback_id)
    elif action.startswith("p") and action[1:].isdigit():
        await _decide(db, bot, prompt, "approve", actor, callback_id, pick=int(action[1:]))
    elif action == "r":
        rows = [
            [
                button(label, f"g:{prompt.id}:c{i}")
                for i, (_v, label) in enumerate(REASONS[j : j + 2], j)
            ]
            for j in range(0, len(REASONS), 2)
        ]
        await bot.edit_reply_markup(chat_id, message.get("message_id"), inline_keyboard(rows))
        await bot.answer_callback(callback_id, "Why? Pick a reason.")
    elif action.startswith("c") and action[1:].isdigit() and int(action[1:]) < len(REASONS):
        category = REASONS[int(action[1:])][0]
        ask = await bot.send_message(
            chat_id,
            f"Rejecting ({category}). Reply with a comment, or '-' to skip.",
            {"force_reply": True, "input_field_placeholder": "What should change?"},
        )
        prompt.data = {
            **(prompt.data or {}),
            "pending_reject": {
                "category": category,
                "chat_id": str(chat_id),
                "message_id": (ask or {}).get("message_id"),
                "by": actor,
            },
        }
        await db.commit()
        await bot.answer_callback(callback_id, "Reply with a comment.")
    else:
        await bot.answer_callback(callback_id, "Unknown button.")


async def _on_message(db: AsyncSession, bot: TelegramClient, message: dict[str, Any]) -> None:
    chat_id = (message.get("chat") or {}).get("id")
    text = str(message.get("text") or "").strip()
    if text.startswith(("/start", "/chatid")):
        await bot.send_message(chat_id, f"This chat id is {chat_id}. Put it in TELEGRAM_CHAT_ID.")
        return
    reply_to = (message.get("reply_to_message") or {}).get("message_id")
    if reply_to is None or not allowed_chat(chat_id):
        return
    prompts = (
        await db.scalars(select(TelegramPromptTable).where(TelegramPromptTable.status == "open"))
    ).all()
    for prompt in prompts:
        pending = (prompt.data or {}).get("pending_reject") or {}
        if pending.get("message_id") == reply_to and pending.get("chat_id") == str(chat_id):
            comment = None if text.lower() in SKIP_COMMENT else text[:4000]
            await _decide(
                db,
                bot,
                prompt,
                "reject",
                actor_of(message.get("from")),
                None,
                category=pending.get("category"),
                comment=comment,
            )
            return


async def handle_update(db: AsyncSession, update: dict[str, Any]) -> None:
    """One Telegram update (from getUpdates or the webhook)."""
    bot = get_bot()
    if bot is None:
        return
    if update.get("callback_query"):
        await _on_callback(db, bot, update["callback_query"])
    elif update.get("message"):
        await _on_message(db, bot, update["message"])


# ---- the long-polling worker ---------------------------------------------------


class TelegramWorker:
    """getUpdates long polling (no public URL needed), or webhook registration."""

    def __init__(self) -> None:
        self._task: asyncio.Task[Any] | None = None
        self._offset: int | None = None

    async def start(self) -> None:
        bot = get_bot()
        if bot is None:
            return
        if settings.telegram.webhook_url:
            await bot.set_webhook(
                settings.telegram.webhook_url, settings.telegram.webhook_secret.get_secret_value()
            )
            logger.info("telegram_webhook_set", "Telegram webhook mode")
            return
        await bot.delete_webhook()  # getUpdates refuses while a webhook is set
        self._task = asyncio.create_task(self._loop(bot))
        logger.info("telegram_polling_started", "Telegram long polling started")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def poll_once(self, bot: TelegramClient) -> int:
        updates = await bot.get_updates(self._offset, settings.telegram.poll_timeout_seconds)
        if updates is None:
            await asyncio.sleep(3)
            return 0
        for update in updates:
            self._offset = int(update["update_id"]) + 1
            try:
                async with SessionLocal() as db:
                    await handle_update(db, update)
            except Exception:
                logger.error("telegram_update_failed", "Telegram update failed", exc_info=True)
        return len(updates)

    async def _loop(self, bot: TelegramClient) -> None:
        while True:
            await self.poll_once(bot)


telegram_worker = TelegramWorker()


# ---- hooks the audit routes call ---------------------------------------------


async def on_audit_patched(db: AsyncSession, audit: AuditTable, previous: tuple[str, str]) -> None:
    """An audit entering ``waiting_approval`` (or moving gate while waiting) is a new gate."""
    if audit.status == "waiting_approval" and (audit.status, audit.stage) != previous:
        await safe(notify_audit_gate(db, audit))


async def on_artifact_created(
    db: AsyncSession, audit: AuditTable, artifact: AuditArtifactTable
) -> None:
    if artifact.kind == PUBLIC_DATASET_KIND and artifact.status == "proposed":
        await safe(notify_public_dataset(db, audit, artifact))


async def on_approval_recorded(db: AsyncSession, approval: ApprovalTable) -> None:
    """Decided in the app: close the matching Telegram prompts."""
    key = f"audit:{approval.audit_id}:{approval.gate}"
    await safe(close_prompts(db, key, approval.decision, approval.decided_by))
