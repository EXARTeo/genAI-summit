"""``BaseAgent`` config validation: the contract its signature advertises.

``_validate_config`` takes a ``Mapping`` and returns a ``dict``. A ``Mapping`` is
the read-only protocol, so validation must not write into the object it was
handed: a ``MappingProxyType`` must be accepted, and the caller's ``dict`` must
come back untouched. It still validates: every run carries a non-empty
``client_id`` (the backend's anonymous browser id) and ``conversation_id``.
"""

from __future__ import annotations

import types

import pytest
from conftest import CLIENT_ID, CONVERSATION_ID

from harness.abstractions.base_agent import REQUIRED_CONTEXT_KEYS, BaseAgent


class _Agent(BaseAgent):
    name = "probe"


VALID_CONTEXT = {"client_id": CLIENT_ID, "conversation_id": CONVERSATION_ID}


def test_the_required_keys_are_the_contracts():
    assert REQUIRED_CONTEXT_KEYS == ("client_id", "conversation_id")


# ---------------------------------------------------------------------------
# It does not mutate what it was given
# ---------------------------------------------------------------------------
def test_the_callers_config_is_left_alone():
    config = {"context": dict(VALID_CONTEXT), "run_config": {"configurable": {"thread_id": "t"}}}
    snapshot = {"context": dict(VALID_CONTEXT), "run_config": {"configurable": {"thread_id": "t"}}}

    _Agent(config=config)

    assert config == snapshot, "validation wrote back into the caller's mapping"


def test_a_read_only_mapping_is_accepted():
    # The signature says Mapping. This is a Mapping; it must not raise.
    config = types.MappingProxyType({"context": types.MappingProxyType(dict(VALID_CONTEXT))})
    agent = _Agent(config=config)

    assert agent.context["client_id"] == CLIENT_ID
    assert agent.client_id == CLIENT_ID


def test_the_returned_config_is_a_separate_object():
    config = {"context": dict(VALID_CONTEXT)}
    agent = _Agent(config=config)

    assert agent.config is not config


# ---------------------------------------------------------------------------
# It still validates
# ---------------------------------------------------------------------------
def test_context_is_normalised_on_the_copy():
    config = {"context": {"client_id": f"  {CLIENT_ID}  ", "conversation_id": CONVERSATION_ID}}
    agent = _Agent(config=config)

    assert agent.context["client_id"] == CLIENT_ID
    # The caller's copy keeps its original, untrimmed value.
    assert config["context"]["client_id"] == f"  {CLIENT_ID}  "


@pytest.mark.parametrize("missing", ["client_id", "conversation_id"])
def test_a_context_missing_an_id_is_refused(missing):
    context = dict(VALID_CONTEXT)
    del context[missing]
    with pytest.raises(ValueError, match=missing):
        _Agent(config={"context": context})


@pytest.mark.parametrize("bad", ["", "   ", None, 7])
def test_a_blank_or_non_string_id_is_refused(bad):
    with pytest.raises(ValueError, match="client_id"):
        _Agent(config={"context": {**VALID_CONTEXT, "client_id": bad}})


def test_a_user_id_does_not_stand_in_for_the_client_id():
    # The service has no users: the old key must not satisfy the check.
    with pytest.raises(ValueError, match="client_id"):
        _Agent(config={"context": {"user_id": "u1", "conversation_id": CONVERSATION_ID}})


def test_a_non_mapping_run_config_is_refused():
    with pytest.raises(TypeError, match="run_config"):
        _Agent(config={"context": dict(VALID_CONTEXT), "run_config": ["not", "a", "mapping"]})


def test_a_non_mapping_configurable_is_refused():
    with pytest.raises(TypeError, match="configurable"):
        _Agent(config={"context": dict(VALID_CONTEXT), "run_config": {"configurable": []}})


def test_a_non_mapping_context_is_refused():
    with pytest.raises(TypeError, match="context"):
        _Agent(config={"context": "not-a-mapping"})


def test_no_context_means_no_client():
    # Registry warmup builds an agent without a run: it has no owner.
    agent = _Agent()
    assert agent.context == {}
    assert agent.client_id == ""
