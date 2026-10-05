from pathlib import Path
from unittest.mock import MagicMock

from src.exporters.molecule_agent import (
    MOLECULE_GENERATION_FAILED,
    MOLECULE_NOT_EXECUTED,
    MoleculeAgent,
)
from src.exporters.state import ExportState
from src.exporters.to_ansible import MigrationPhase, ToAnsibleSubagent
from src.exporters.types import MigrationCategory
from src.types import AnsibleModule, Checklist, DocumentFile


def create_state(tmp_path: Path) -> ExportState:
    return ExportState(
        user_message="migrate module",
        path=str(tmp_path / "source"),
        module=AnsibleModule("web_server"),
        module_migration_plan=DocumentFile(
            path=Path("plan.md"),
            content=(
                "# Plan\n\nSummary context is available.\n\n"
                "## Pre-flight checks\n\n```bash\nsystemctl is-active nginx\n```\n\n"
                "## Other checks\nOther plan detail must not add a test."
            ),
        ),
        high_level_migration_plan=DocumentFile(
            path=Path("high-level.md"), content="# High-level plan"
        ),
        directory_listing=[],
        current_phase="writing",
        write_attempt_counter=0,
        validation_attempt_counter=0,
        validation_report="",
        last_output="",
        checklist=Checklist("web_server", MigrationCategory),
    )


def create_agent() -> MoleculeAgent:
    agent = object.__new__(MoleculeAgent)
    agent._log = MagicMock()
    return agent


def write_valid_verification(agent):
    captured_messages: list[list[dict[str, str]]] = []

    def invoke_react(state, messages, metrics):
        captured_messages.append(messages)
        verify = state.get_molecule_scenario_path() / "verify.yml"
        verify.write_text(
            "---\n- hosts: all\n  tasks:\n"
            "    - name: Assert service state\n"
            "      ansible.builtin.assert:\n"
            "        that: ansible_facts['services']['httpd.service']['state'] == 'running'\n"
        )
        return {"messages": []}

    agent.invoke_react = invoke_react
    return captured_messages


def test_generation_marks_files_static_only_not_executed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    agent = create_agent()
    captured_messages = write_valid_verification(agent)
    state = create_state(tmp_path)
    metrics = MagicMock()

    result = agent.execute(state, metrics)

    assert result.molecule_status == MOLECULE_NOT_EXECUTED
    assert "not run by the converter" in result.molecule_report
    system_prompt = captured_messages[0][0]["content"]
    task_prompt = captured_messages[0][1]["content"]
    assert "Summary context is available" in task_prompt
    assert "Other plan detail must not add a test" in task_prompt
    assert "Do not derive checks from other sections" in task_prompt
    assert "systemctl is-active nginx" in task_prompt
    assert "only source of verification expectations" in system_prompt
    assert (
        "Write only the `verify.yml` file at the path provided in the task."
        in system_prompt
    )
    assert "Write only ``." not in system_prompt
    assert str(state.get_molecule_scenario_path() / "verify.yml") in task_prompt
    assert "Final role task files" not in task_prompt
    assert result.checklist is not None
    assert all(
        item.status.value == "complete"
        for item in result.checklist.items_by_category(include={"molecule"})
    )
    metrics.record_metric.assert_any_call("molecule_static_validation", True)


def test_generation_failure_is_reported_and_verify_remains_incomplete(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    agent = create_agent()
    agent.invoke_react = MagicMock(return_value={"messages": []})
    state = create_state(tmp_path)

    result = agent.execute(state, None)

    verify_path = str(state.get_molecule_scenario_path() / "verify.yml")
    assert result.checklist is not None
    verify_item = result.checklist.find_task("N/A", verify_path)
    assert verify_item is not None
    assert result.molecule_status == MOLECULE_GENERATION_FAILED
    assert verify_item.status.value == "error"
    assert "behavior assertion" in result.molecule_report
    assert agent.invoke_react.call_count == agent.MAX_GENERATION_ATTEMPTS


def test_workflow_generates_molecule_after_review():
    orchestrator = object.__new__(ToAnsibleSubagent)
    state = create_state(Path())

    state = state.update(current_phase=MigrationPhase.WRITING)
    assert orchestrator._check_failure_after_agent(state) == "review_role"
    state = state.update(current_phase=MigrationPhase.REVIEWING)
    assert orchestrator._check_failure_after_agent(state) == "molecule_testing"
    state = state.update(current_phase=MigrationPhase.MOLECULE_TESTING)
    assert orchestrator._check_failure_after_agent(state) == "validate_migration"
