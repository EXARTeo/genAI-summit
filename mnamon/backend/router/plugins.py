"""Plugin routes (``/v1/systems/{id}/plugins``): the system graph with each component's plugin,
the defaults the plugin form shows in grey (graph + local MLflow), and saving a plugin.

A plugin is the wrapper around one model (how the agent calls it). It is stored as
``plugins/<name>/plugin.yaml`` in the system folder; logic lives in ``utils.plugins``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.logging import get_logger
from core.security.client import Caller, get_caller
from core.security.rate_limit import workspace_rate_limit
from schema.plugins import (
    PLUGIN_NAME_PATTERN,
    ComponentIn,
    PluginDefaultsOut,
    PluginGraphOut,
    PluginIn,
    PluginWriteOut,
)
from utils.plugins import (
    add_component,
    plugin_defaults,
    remove_component,
    save_plugin,
    system_graph,
)
from utils.systems import actor_for
from utils.workspace import get_system_or_404

router = APIRouter()
logger = get_logger(__name__)

CallerDep = Annotated[Caller, Depends(get_caller)]
Limited = Annotated[None, Depends(workspace_rate_limit)]
Db = Annotated[AsyncSession, Depends(get_db)]


@router.get(
    "/{system_id}/plugins",
    response_model=PluginGraphOut,
    summary="The system graph (architecture.yaml) with each component's plugin",
)
async def get_plugin_graph(
    system_id: str, _caller: CallerDep, _limited: Limited, db: Db
) -> PluginGraphOut:
    await get_system_or_404(db, system_id)
    graph = await system_graph(db, system_id)
    logger.info(
        "plugin_graph_read",
        "Plugin graph read",
        system_id=system_id,
        item_count=len(graph["components"]),
    )
    return PluginGraphOut.model_validate(graph)


@router.get(
    "/{system_id}/plugins/defaults",
    response_model=PluginDefaultsOut,
    summary="Defaults for a plugin form, from the graph and the local MLflow registry",
)
async def get_plugin_defaults(
    system_id: str,
    _caller: CallerDep,
    _limited: Limited,
    db: Db,
    component: Annotated[str | None, Query(max_length=200)] = None,
    model: Annotated[str | None, Query(max_length=300)] = None,
    name: Annotated[str | None, Query(pattern=PLUGIN_NAME_PATTERN)] = None,
) -> PluginDefaultsOut:
    await get_system_or_404(db, system_id)
    out = await plugin_defaults(db, system_id, component_id=component, model=model, name=name)
    logger.info(
        "plugin_defaults_read",
        "Plugin defaults built",
        system_id=system_id,
        plugin=out["name"],
        mlflow_status=out["mlflow"].status,
    )
    return PluginDefaultsOut.model_validate(out)


@router.put(
    "/{system_id}/plugins/{name}",
    response_model=PluginWriteOut,
    summary="Save a plugin (a new version of plugins/<name>/plugin.yaml)",
)
async def put_plugin(
    system_id: str, name: str, payload: PluginIn, caller: CallerDep, _limited: Limited, db: Db
) -> PluginWriteOut:
    await get_system_or_404(db, system_id)
    out = await save_plugin(
        db,
        system_id,
        name,
        payload.card,
        actor=actor_for(caller.id),
        component_id=payload.component,
        reason=payload.reason,
        upstream=payload.upstream,
        downstream=payload.downstream,
    )
    await db.commit()
    logger.info(
        "plugin_saved",
        "Plugin saved",
        system_id=system_id,
        plugin=name,
        version=out["version"],
        changed=out["changed"],
    )
    return PluginWriteOut.model_validate(out)


@router.post(
    "/{system_id}/plugins/components",
    response_model=PluginGraphOut,
    status_code=201,
    summary="Add a box to the system graph (a model, an upstream system or a human step)",
)
async def post_component(
    system_id: str, payload: ComponentIn, caller: CallerDep, _limited: Limited, db: Db
) -> PluginGraphOut:
    await get_system_or_404(db, system_id)
    graph = await add_component(
        db,
        system_id,
        name=payload.name,
        kind=payload.kind,
        model=payload.model,
        note=payload.note,
        upstream=payload.upstream,
        downstream=payload.downstream,
        actor=actor_for(caller.id),
    )
    await db.commit()
    logger.info("graph_component_added", "Graph component added", system_id=system_id)
    return PluginGraphOut.model_validate(graph)


@router.delete(
    "/{system_id}/plugins/components/{component_id}",
    response_model=PluginGraphOut,
    summary="Remove a box and its edges from the system graph (plugin files stay)",
)
async def delete_component(
    system_id: str, component_id: str, caller: CallerDep, _limited: Limited, db: Db
) -> PluginGraphOut:
    await get_system_or_404(db, system_id)
    graph = await remove_component(db, system_id, component_id, actor=actor_for(caller.id))
    await db.commit()
    logger.info("graph_component_removed", "Graph component removed", system_id=system_id)
    return PluginGraphOut.model_validate(graph)
