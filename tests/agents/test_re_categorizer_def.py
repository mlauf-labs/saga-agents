"""Load and validate the re-categorizer agent definition."""

from saga_agents.config.loader import load_agent_files
from saga_agents.config.models import AgentDefinition, ScheduleTrigger


def test_re_categorizer_loads() -> None:
    defs: dict[str, AgentDefinition] = {d.id: d for d in load_agent_files("config/agents")}
    d = defs["re-categorizer"]
    assert d.autonomy == "proposal"
    assert "assign_document_to_folder" in d.tools.write
    assert "set_primary_folder" in d.tools.write
    assert "set_document_folders" in d.tools.write
    assert d.system_prompt.strip() != ""


def test_re_categorizer_schedule_trigger() -> None:
    defs: dict[str, AgentDefinition] = {d.id: d for d in load_agent_files("config/agents")}
    d = defs["re-categorizer"]
    schedule_triggers = [t for t in d.triggers if isinstance(t, ScheduleTrigger)]
    assert any(t.cron == "0 4 * * *" for t in schedule_triggers)


def test_re_categorizer_tools_write_subset_of_allow() -> None:
    defs: dict[str, AgentDefinition] = {d.id: d for d in load_agent_files("config/agents")}
    d = defs["re-categorizer"]
    assert set(d.tools.write).issubset(set(d.tools.allow))


def test_both_agents_load_without_duplicate_id() -> None:
    agents = load_agent_files("config/agents")
    ids = [a.id for a in agents]
    assert "event-deduplicator" in ids
    assert "re-categorizer" in ids
    assert len(ids) == len(set(ids)), "Duplicate agent ids found"
