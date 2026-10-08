"""Tests for ExportState's Ansible layout delegation."""

from pathlib import Path

from src.exporters.state import ExportState
from src.exporters.types import MigrationCategory, MoleculeStatus
from src.types import AnsibleModule, Checklist, DocumentFile


def create_state(tmp_path: Path) -> ExportState:
    return ExportState(
        user_message="migrate this",
        path=str(tmp_path),
        module=AnsibleModule("test_module"),
        module_migration_plan=DocumentFile(path=Path("plan.md"), content="# Plan"),
        high_level_migration_plan=DocumentFile(path=Path("hl.md"), content="# HL"),
        directory_listing=["recipes/default.rb"],
        current_phase="complete",
        write_attempt_counter=2,
        validation_attempt_counter=1,
        validation_report="All checks passed",
        last_output="",
        checklist=Checklist("test_module", MigrationCategory),
    )


def test_state_caches_and_delegates_to_project_layout(tmp_path):
    state = create_state(tmp_path)

    assert state.layout is state.layout
    assert state.get_ansible_project_path() == Path("ansible")
    assert state.get_ansible_path() == (
        "ansible/collections/ansible_collections/x2a/project/roles/test_module"
    )
    assert state.get_ansible_fqcn() == "x2a.project.test_module"
    assert state.get_run_playbook_path() == Path("ansible/run_test_module.yml")
    assert state.get_molecule_scenario_path() == Path("ansible/molecule/test_module")


def test_layout_exposes_the_seven_generated_molecule_targets(tmp_path):
    targets = create_state(tmp_path).layout.molecule_checklist_targets()

    assert len(targets) == 7
    assert set(targets) == {
        "ansible/run_test_module.yml",
        "ansible/molecule/requirements.yml",
        "ansible/molecule/README.md",
        "ansible/molecule/test_module/molecule.yml",
        "ansible/molecule/test_module/prepare.yml",
        "ansible/molecule/test_module/converge.yml",
        "ansible/molecule/test_module/verify.yml",
    }


def test_molecule_status_defaults_to_not_generated(tmp_path):
    assert create_state(tmp_path).molecule_status == MoleculeStatus.NOT_GENERATED
