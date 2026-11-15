"""Plugin DTOs: the system graph (architecture.yaml components + their plugins), the
defaults the plugin form shows in grey, and a plugin write.

A plugin is the wrapper around one model: how the agent reaches it (``access``), where it
sits in the system (``placement``), its I/O and expected behaviour. It is stored as
``plugins/<name>/plugin.yaml`` in the system folder (docs/architecture/agent-context.md § 3).
"""

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field

#: Folder name of a plugin: ``cv-ranker``.
PLUGIN_NAME_PATTERN = r"^[a-z0-9][a-z0-9-]{0,62}$"


class GraphComponent(BaseModel):
    """One box of the system graph."""

    id: str
    name: str
    kind: str = ""
    model: str | None = None
    note: str | None = None
    #: The plugin folder (``cv-ranker``) when one is configured.
    plugin: str | None = None
    configured: bool = False
    #: A model or endpoint the agent can call (an upstream system or a human step is not).
    testable: bool = False


class GraphEdge(BaseModel):
    """An edge of the graph; read from ``from``/``to`` (architecture.yaml), sent as
    ``source``/``target``."""

    source: str = Field(..., validation_alias=AliasChoices("from", "source"))
    target: str = Field(..., validation_alias=AliasChoices("to", "target"))
    data: str | None = None


class PluginGraphOut(BaseModel):
    system: str
    components: list[GraphComponent]
    edges: list[GraphEdge]
    entry: str | None = None
    #: Every plugin.yaml, parsed, keyed by folder name.
    plugins: dict[str, dict[str, Any]] = Field(default_factory=dict)


class MlflowModelInfo(BaseModel):
    """What the registry says about the model (best effort)."""

    status: str  # ok | not_found | unreachable | not_mlflow
    name: str | None = None
    alias: str | None = None
    version: str | None = None
    run_id: str | None = None
    description: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    inputs: list[dict[str, Any]] = Field(default_factory=list)
    outputs: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class PluginDefaultsOut(BaseModel):
    name: str
    component: str | None = None
    #: A complete plugin card built from the graph + MLflow: the form's grey placeholders.
    defaults: dict[str, Any]
    #: The saved plugin.yaml, when the plugin exists.
    existing: dict[str, Any] | None = None
    mlflow: MlflowModelInfo
    #: The seed case plugin for this model ("Fill example"), and its other files.
    example: dict[str, Any] | None = None
    example_files: list[str] = Field(default_factory=list)


class PluginIn(BaseModel):
    """A plugin card to save; empty fields are filled from the defaults by the client."""

    card: dict[str, Any]
    #: The graph component this plugin wraps (linked in architecture.yaml).
    component: str | None = Field(None, max_length=200)
    reason: str | None = Field(None, max_length=500)
    #: Edges to add for this model: components before it / after it in the pipeline.
    upstream: list[str] = Field(default_factory=list, max_length=20)
    downstream: list[str] = Field(default_factory=list, max_length=20)
    #: Copy the seed plugin's docs and data dictionary (after "Fill example").
    copy_example_files: bool = False


class PluginWriteOut(BaseModel):
    name: str
    path: str
    version: int
    changed: bool
    card: dict[str, Any]
    architecture_updated: bool = False
    files_copied: list[str] = Field(default_factory=list)


class ComponentIn(BaseModel):
    """A box added to the system graph (architecture.yaml)."""

    name: str = Field(..., min_length=1, max_length=120)
    kind: Literal["ml_model", "upstream_system", "human_review"] = "ml_model"
    model: str | None = Field(None, max_length=300)
    note: str | None = Field(None, max_length=500)
    upstream: list[str] = Field(default_factory=list, max_length=20)
    downstream: list[str] = Field(default_factory=list, max_length=20)
