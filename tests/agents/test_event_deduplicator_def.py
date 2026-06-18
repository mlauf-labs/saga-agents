"""Load and validate the event-deduplicator agent definition."""

from saga_agents.config.loader import load_agent_files
from saga_agents.config.models import AgentDefinition, EventTrigger


def test_event_deduplicator_loads() -> None:
    defs: dict[str, AgentDefinition] = {d.id: d for d in load_agent_files("config/agents")}
    d = defs["event-deduplicator"]
    assert d.autonomy == "proposal"
    assert "merge_events" in d.tools.write
    assert d.system_prompt.startswith("You are the **Event Deduplicator**")


def test_event_deduplicator_tools_write_subset_of_allow() -> None:
    defs: dict[str, AgentDefinition] = {d.id: d for d in load_agent_files("config/agents")}
    d = defs["event-deduplicator"]
    assert set(d.tools.write).issubset(set(d.tools.allow))


def test_event_deduplicator_system_prompt_nonempty() -> None:
    defs: dict[str, AgentDefinition] = {d.id: d for d in load_agent_files("config/agents")}
    d = defs["event-deduplicator"]
    assert d.system_prompt.strip() != ""


def test_both_agents_load_without_duplicate_id() -> None:
    agents = load_agent_files("config/agents")
    ids = [a.id for a in agents]
    assert "event-deduplicator" in ids
    assert "re-categorizer" in ids
    assert len(ids) == len(set(ids)), "Duplicate agent ids found"


def test_event_deduplicator_event_trigger() -> None:
    defs: dict[str, AgentDefinition] = {d.id: d for d in load_agent_files("config/agents")}
    d = defs["event-deduplicator"]
    event_triggers = [t for t in d.triggers if isinstance(t, EventTrigger)]
    assert len(event_triggers) == 1, "Expected exactly one EventTrigger"
    et = event_triggers[0]
    assert "document.ingested" in et.topics
    assert et.debounce_minutes == 15
