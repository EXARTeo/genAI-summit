"""The agent registry: slug -> :class:`~schema.catalog.AgentDefinition`.

Two sources:

1. **Declarative (YAML) agents**: ``<AGENTS_DIR>/<slug>/agent.yaml`` parsed into
   an :class:`~harness.abstractions.agent_spec.AgentSpec` and served by the
   shared :class:`~harness.abstractions.yaml_agent.YamlDeepAgent`. The image
   ships ``definitions/``, empty until the product agent is written.
2. **Python agents**: ``DeepAgent`` / ``LangGraphAgent`` subclasses listed in
   :data:`PYTHON_AGENTS`. A YAML agent with the same slug wins.

Built once at import: the definitions are build-time content, so a change is a
rebuild of the image, never a runtime edit.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import yaml
from pipeline.agent import AuditPipelineAgent

from core.logging import get_logger
from core.settings import settings
from harness.abstractions import AgentSpec, BaseAgent, YamlDeepAgent
from harness.filesystem import layout
from harness.tools.registry import is_known_native_tool
from schema.catalog import AgentDefinition, AgentManifest
from utils.declarative import manifest_from_spec

logger = get_logger(__name__)

#: Python-class agents, registered by their ``name``. Add a class here to ship it.
PYTHON_AGENTS: tuple[type[BaseAgent], ...] = (AuditPipelineAgent,)


def _is_known_model(model_id: str) -> bool:
    """Any ``provider:model`` id: a model the provider does not know fails at run time,
    loudly, rather than hiding an agent at boot."""
    return isinstance(model_id, str) and ":" in model_id


def _python_agents() -> dict[str, AgentDefinition]:
    return {
        cls.name: AgentDefinition(
            slug=cls.name, manifest=cls.manifest(), factory=lambda cfg, c=cls: c(config=cfg)
        )
        for cls in PYTHON_AGENTS
    }


def _scan_yaml_agents(root: Path) -> dict[str, AgentDefinition]:
    """Discover declarative agents under ``<root>/<slug>/agent.yaml``.

    Each is validated structurally (``AgentSpec``) and referentially (models,
    native tools, locked gates); an invalid spec is logged and skipped, never
    fatal: one bad folder must not take the others down.
    """
    registry: dict[str, AgentDefinition] = {}
    if not root.is_dir():
        logger.warning(
            "agents_dir_missing", "The agents folder does not exist", agents_dir=str(root)
        )
        return registry
    for entry in sorted(root.iterdir()):
        manifest_path = entry / "agent.yaml"
        if not manifest_path.is_file():
            continue
        try:
            raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            spec = AgentSpec.model_validate(raw)
            ref_errors = spec.reference_errors(
                is_known_model=_is_known_model, is_known_native_tool=is_known_native_tool
            )
            if ref_errors:
                raise ValueError("; ".join(ref_errors))
            if spec.slug != entry.name:
                raise ValueError(f"slug {spec.slug!r} does not match its folder {entry.name!r}")
        except (OSError, ValueError, yaml.YAMLError):
            logger.error(
                "yaml_agent_invalid",
                "Skipping an invalid declarative agent",
                agent_dir=entry.name,
                exc_info=True,
            )
            continue
        registry[spec.slug] = AgentDefinition(
            slug=spec.slug,
            manifest=manifest_from_spec(spec),
            factory=lambda cfg, s=spec, sd=entry: YamlDeepAgent(s, sd, config=cfg),
            spec=spec,
        )
    return registry


def build_registry(root: Path) -> dict[str, AgentDefinition]:
    """Python agents, then the YAML agents under ``root`` (YAML wins on a slug clash)."""
    registry = _python_agents()
    yaml_agents = _scan_yaml_agents(root)
    for slug in yaml_agents.keys() & registry.keys():
        logger.info(
            "agent_yaml_overrides_python",
            "A declarative agent overrides the Python agent of the same slug",
            agent_slug=slug,
        )
    registry.update(yaml_agents)
    logger.info(
        "agent_registry_discovered",
        "Agent registry discovered",
        count=len(registry),
        yaml_count=len(yaml_agents),
    )
    return registry


AGENT_REGISTRY: dict[str, AgentDefinition] = build_registry(layout.agents_root())


def resolve_agent_definition(slug: str) -> AgentDefinition | None:
    """The single lookup for "give me this agent"; None for an unknown slug."""
    return AGENT_REGISTRY.get(slug)


async def definition_candidates(slug: str) -> AsyncIterator[AgentDefinition]:
    """The definitions a pinned task tree may have been started on: the current one.

    The task runner builds each candidate and keeps the one whose fingerprint
    is the task's pinned ``definition_version``; none matching fails the run
    closed rather than running a different agent.
    """
    current = resolve_agent_definition(slug)
    if current is not None:
        yield current


def list_agent_manifests() -> list[AgentManifest]:
    """Every registered agent's manifest, by name, the default one marked."""
    default = settings.registry.default_agent_slug
    manifests = [
        AgentManifest.model_validate({**definition.manifest, "default": slug == default})
        for slug, definition in AGENT_REGISTRY.items()
    ]
    return sorted(manifests, key=lambda item: item.name)
