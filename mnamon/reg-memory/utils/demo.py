from __future__ import annotations

from fastapi import HTTPException, status

from core.settings import settings
from engine.demo import edit_mirror, read_mirror
from schema.watch import MirrorEdit, MirrorOut


def mirror_html() -> str:
    return read_mirror(settings.store.data_dir)


def mirror_out() -> MirrorOut:
    html = mirror_html()
    return MirrorOut(url=settings.watch.demo_mirror_url, bytes=len(html.encode()), html=html)


def edit(body: MirrorEdit) -> MirrorOut:
    if not (body.reset or body.html is not None or body.find is not None or body.append_html):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "give html, find/replace, append_html or reset"
        )
    try:
        html = edit_mirror(
            settings.store.data_dir,
            html=body.html,
            find=body.find,
            replace=body.replace,
            append_html=body.append_html,
            reset=body.reset,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return MirrorOut(url=settings.watch.demo_mirror_url, bytes=len(html.encode()), html=html)
