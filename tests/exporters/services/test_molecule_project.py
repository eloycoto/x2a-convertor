from pathlib import Path

import yaml

from src.exporters.services.molecule_project import MoleculeProject
from src.exporters.state import ExportState
from src.exporters.types import MigrationCategory
from src.types import AnsibleModule, Checklist, DocumentFile


def create_state(tmp_path: Path) -> ExportState:
    return ExportState(
        user_message="migrate module",
        path=str(tmp_path / "source"),
        module=AnsibleModule("web_server"),
        module_migration_plan=DocumentFile(
            path=Path("plan.md"), content="# Plan\n\nCheck the web service."
        ),
        high_level_migration_plan=DocumentFile(
            path=Path("high-level.md"), content="# High-level plan"
        ),
        directory_listing=[],
        current_phase="molecule_testing",
        write_attempt_counter=0,
        validation_attempt_counter=0,
        validation_report="",
        last_output="",
        checklist=Checklist("web_server", MigrationCategory),
    )


def valid_verify() -> str:
    return """---
- name: Verify migrated web service
  hosts: all
  gather_facts: false
  tasks:
    - name: Check the service state
      ansible.builtin.service_facts:
    - name: Assert the service is running
      ansible.builtin.assert:
        that:
          - ansible_facts['services']['httpd.service']['state'] == 'running'
"""


def test_scaffolds_project_level_native_scenario_and_role_fqcn(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = create_state(tmp_path)
    project = MoleculeProject(state)

    project.scaffold()

    scenario = Path("ansible/molecule/web_server")
    assert not (Path(state.get_ansible_path()) / "molecule").exists()
    assert (scenario / "molecule.yml").is_file()
    config = yaml.safe_load((scenario / "molecule.yml").read_text())
    assert config["driver"]["name"] == "podman"
    assert config["platforms"][0]["name"] == "x2a_web_server"
    assert config["platforms"][0]["image"] == (
        "${X2A_MOLECULE_IMAGE:-registry.access.redhat.com/ubi9/ubi-init:latest}"
    )
    assert config["platforms"][0]["command"] == "/sbin/init"
    assert config["platforms"][0]["systemd"] == "always"
    assert config["platforms"][0]["privileged"] is True
    assert config["ansible"]["executor"]["backend"] == "ansible-playbook"
    assert "args" not in config["ansible"]["executor"]
    assert (
        config["dependency"]["options"]["requirements-file"]
        == "molecule/requirements.yml"
    )
    assert (
        config["dependency"]["env"]["ANSIBLE_COLLECTIONS_PATH"]
        == "${MOLECULE_PROJECT_DIRECTORY}/collections"
    )
    assert "idempotence" in config["scenario"]["test_sequence"]
    assert not (scenario / "inventory").exists()
    assert not (scenario / "create.yml").exists()
    assert not (scenario / "destroy.yml").exists()
    prepare = yaml.safe_load((scenario / "prepare.yml").read_text())
    assert prepare[0]["hosts"] == "all"
    raw_script = prepare[0]["tasks"][0]["ansible.builtin.raw"]
    assert "/bin/sh -c" in raw_script
    playbook = yaml.safe_load(Path("ansible/run_web_server.yml").read_text())
    assert playbook[0]["tasks"][0]["ansible.builtin.include_role"]["name"] == (
        "x2a.project.web_server"
    )
    assert "../../run_web_server.yml" in (scenario / "converge.yml").read_text()


def test_scaffold_preserves_existing_project_artifacts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = create_state(tmp_path)
    project = MoleculeProject(state)
    project.scaffold()
    deployment = state.get_run_playbook_path()
    deployment.write_text("# user-maintained deployment entry point\n")

    project.scaffold()

    assert deployment.read_text() == "# user-maintained deployment entry point\n"


def test_static_validation_rejects_missing_or_debug_only_verify(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = create_state(tmp_path)
    project = MoleculeProject(state)
    project.scaffold()

    errors = project.validate()
    assert any("verify.yml" in error for error in errors)

    verify_path = state.get_molecule_scenario_path() / "verify.yml"
    verify_path.write_text(
        "---\n- hosts: all\n  tasks:\n"
        "    - ansible.builtin.debug:\n        msg: placeholder\n"
    )
    assert (
        "verify.yml must contain at least one behavior assertion" in project.validate()
    )


def test_static_validation_accepts_source_grounded_assertion(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = create_state(tmp_path)
    project = MoleculeProject(state)
    project.scaffold()
    (state.get_molecule_scenario_path() / "verify.yml").write_text(valid_verify())

    assert project.validate() == []
