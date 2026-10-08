from pathlib import Path

from src.exporters.services.ansible_project_layout import AnsibleProjectLayout
from src.exporters.services.molecule_scenario_templates import MoleculeScenarioTemplates
from src.exporters.services.molecule_scenario_validator import MoleculeScenarioValidator
from src.exporters.services.molecule_scenario_writer import MoleculeScenarioWriter
from src.types import AnsibleModule

VALID_VERIFY = """---
- name: Verify migrated service
  hosts: all
  tasks:
    - name: Assert service state
      ansible.builtin.assert:
        that:
          - ansible_facts['services']['httpd.service']['state'] == 'running'
"""


def create_validator(
    tmp_path: Path,
) -> tuple[MoleculeScenarioValidator, AnsibleProjectLayout]:
    layout = AnsibleProjectLayout.from_module(
        AnsibleModule("web_server"), project_path=tmp_path / "ansible"
    )
    files = MoleculeScenarioTemplates(layout).files()
    MoleculeScenarioWriter().write_missing(files)
    return MoleculeScenarioValidator(layout), layout


def test_validator_rejects_missing_verify_playbook(tmp_path):
    validator, layout = create_validator(tmp_path)
    files = MoleculeScenarioTemplates(layout).files()

    errors = validator.validate(list(files))

    assert any("verify.yml" in error for error in errors)


def test_validator_rejects_debug_only_verify_playbook(tmp_path):
    validator, layout = create_validator(tmp_path)
    layout.molecule_verify_path.write_text(
        "---\n- hosts: all\n  tasks:\n"
        "    - ansible.builtin.debug:\n        msg: placeholder\n"
    )

    assert (
        "verify.yml must contain at least one behavior assertion"
        in validator.validate([layout.molecule_verify_path])
    )


def test_validator_accepts_concrete_assertions(tmp_path):
    validator, layout = create_validator(tmp_path)
    layout.molecule_verify_path.write_text(VALID_VERIFY)
    files = MoleculeScenarioTemplates(layout).files()

    assert validator.validate([*files, layout.molecule_verify_path]) == []


def test_validator_accepts_no_supported_expectations(tmp_path):
    validator, layout = create_validator(tmp_path)
    layout.molecule_verify_path.write_text(
        "---\n- name: No supported pre-flight checks\n  hosts: all\n  tasks: []\n"
    )
    files = MoleculeScenarioTemplates(layout).files()

    assert validator.validate([*files, layout.molecule_verify_path]) == []


def test_validator_reports_invalid_yaml(tmp_path):
    validator, layout = create_validator(tmp_path)
    layout.molecule_verify_path.write_text("- tasks: [\n")

    errors = validator.validate([layout.molecule_verify_path])

    assert errors and "Invalid YAML" in errors[0]
