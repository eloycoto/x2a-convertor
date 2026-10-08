"""Render deterministic Ansible-native Molecule project artifacts."""

from pathlib import Path

from src.exporters.services.ansible_project_layout import AnsibleProjectLayout
from src.exporters.services.molecule_contract import (
    COLLECTIONS_PATH_TEMPLATE,
    DEFAULT_LINUX_IMAGE,
    MOLECULE_DRIVER,
    PODMAN_COLLECTION,
    REQUIREMENTS_FILE,
    SYSTEMD_COMMAND,
    SYSTEMD_MODE,
)


class MoleculeScenarioTemplates:
    """Produce scenario file paths and contents without performing file I/O."""

    def __init__(self, layout: AnsibleProjectLayout) -> None:
        self.layout = layout

    def files(self) -> dict[Path, str]:
        """Return deterministic project and scenario artifacts."""
        return {
            self.layout.run_playbook_path: self._deployment_playbook(),
            self.layout.molecule_requirements_path: self._requirements(),
            self.layout.molecule_readme_path: self._instructions(),
            self.layout.molecule_scenario_path
            / "molecule.yml": self._molecule_config(),
            self.layout.molecule_scenario_path
            / "prepare.yml": self._prepare_playbook(),
            self.layout.molecule_scenario_path
            / "converge.yml": self._converge_playbook(),
        }

    def _deployment_playbook(self) -> str:
        module = self.layout.module
        return f"""---
- name: Run migrated role {module}
  hosts: all
  gather_facts: true
  tasks:
    - name: Apply {module} role
      ansible.builtin.include_role:
        name: {self.layout.fqcn}
"""

    @staticmethod
    def _requirements() -> str:
        return f"""---
collections:
  - name: {PODMAN_COLLECTION}
    version: ">=1.10.0"
"""

    def _molecule_config(self) -> str:
        module = self.layout.module
        return f"""---
dependency:
  name: galaxy
  options:
    requirements-file: {REQUIREMENTS_FILE}
  env:
    ANSIBLE_COLLECTIONS_PATH: {COLLECTIONS_PATH_TEMPLATE}

driver:
  name: {MOLECULE_DRIVER}

platforms:
  - name: x2a_{module}
    image: ${{X2A_MOLECULE_IMAGE:-{DEFAULT_LINUX_IMAGE}}}
    command: {SYSTEMD_COMMAND}
    systemd: {SYSTEMD_MODE}
    privileged: true

provisioner:
  name: ansible

ansible:
  executor:
    backend: ansible-playbook
  env:
    ANSIBLE_COLLECTIONS_PATH: {COLLECTIONS_PATH_TEMPLATE}
  playbooks:
    prepare: prepare.yml
    converge: converge.yml
    verify: verify.yml

scenario:
  test_sequence:
    - dependency
    - create
    - prepare
    - converge
    - idempotence
    - verify
    - destroy

verifier:
  name: ansible
"""

    @staticmethod
    def _prepare_playbook() -> str:
        return """---
- name: Prepare Linux test targets
  hosts: all
  gather_facts: false
  tasks:
    - name: Ensure Python is available for Ansible modules
      ansible.builtin.raw: >-
        /bin/sh -c 'if command -v python3 >/dev/null 2>&1; then exit 0;
        elif command -v dnf >/dev/null 2>&1; then dnf install -y python3;
        elif command -v apt-get >/dev/null 2>&1; then apt-get update && apt-get install -y python3;
        else echo "No supported package manager found to install Python 3" >&2; exit 1; fi'
"""

    def _converge_playbook(self) -> str:
        return f"""---
- name: Converge through the project deployment entry point
  ansible.builtin.import_playbook: ../../{self.layout.run_playbook_path.name}
"""

    @staticmethod
    def _instructions() -> str:
        return """# Running generated Molecule scenarios

Install Molecule, its Podman driver plugin in the same Python environment, and Podman. For a uv-managed environment:

```bash
uv pip install --python "$(command -v python)" molecule 'molecule-plugins[podman]'
ANSIBLE_COLLECTIONS_PATH="$PWD/collections" \\
  ansible-galaxy collection install -r molecule/requirements.yml
molecule test --scenario-name <module>
```

Run from the Ansible project root. Scenarios create privileged, disposable Linux
containers using Molecule's native Podman driver; do not point them at production
inventory. Set `X2A_MOLECULE_IMAGE` to use another Linux image that includes systemd at
`/sbin/init` and a supported `dnf` or `apt-get` package manager. Podman systemd
mode is enabled for the disposable container. Tests bootstrap Python before
applying the actual project deployment playbook. The converter generates and
statically validates scenarios but does not execute them; developer/CI results
are the runtime acceptance signal. Windows hosts require a separate future profile.
"""
