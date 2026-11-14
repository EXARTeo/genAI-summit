"""Agent abstractions: the base classes and the configurable agent kind.

* :class:`BaseAgent` — identity, config, MCP tool selection, manifest, the
  stream loop, error encoding.
* :class:`LangGraphAgent` — the ``StateGraph`` base for graph-shaped agents.
* :class:`DeepAgent` — the deepagents base: workspace, builtins, sub-agents, HITL.
* :class:`AgentSpec` (+ ``ModelSpec``/``SubAgentSpec``/``ToolRef``) — the schema
  that makes an agent configurable rather than coded.
* :class:`YamlDeepAgent` — one generic deep agent driven entirely by an
  ``AgentSpec``, so a folder of config is a working agent.
"""

from harness.abstractions.agent_spec import AgentSpec, ModelSpec, SubAgentSpec, ToolRef
from harness.abstractions.base_agent import AgentType, BaseAgent
from harness.abstractions.deep_agent import DeepAgent
from harness.abstractions.langgraph_agent import LangGraphAgent
from harness.abstractions.yaml_agent import YamlDeepAgent

__all__ = [
    "AgentSpec",
    "AgentType",
    "BaseAgent",
    "DeepAgent",
    "LangGraphAgent",
    "ModelSpec",
    "SubAgentSpec",
    "ToolRef",
    "YamlDeepAgent",
]
