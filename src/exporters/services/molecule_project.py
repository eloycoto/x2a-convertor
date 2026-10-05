"""Create and statically validate project-level Ansible-native Molecule scenarios."""

from pathlib import Path
from typing import Any

import yaml

from src.exporters.state import ExportState

DEFAULT_LINUX_IMAGE = "registry.access.redhat.com/ubi9/ubi-init:latest"


class MoleculeProject:
    """Own deterministic playbooks and configuration for a Molecule scenario."""

    def __init__(self, state: ExportState) -> None:
        self.state = state
        self.project_path = state.get_ansible_project_path()
        self.scenario_path = state.get_molecule_scenario_path()

    def scaffold(self) -> None:
        """Create missing project/scenario files without replacing user edits."""
        self.scenario_path.mkdir(parents=True, exist_ok=True)
        for path, content in self._files().items():
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(content, encoding="utf-8")

    def validate(self) -> list[str]:
        """Check YAML syntax and core playbook/Molecule contracts."""
        documents = self._load_yaml_documents()
        errors = [
            f"Invalid YAML in {path}: {error}"
            for path, error in documents.items()
            if isinstance(error, Exception)
        ]
        if errors:
            return errors

        parsed = {str(path): value for path, value in documents.items()}
        errors.extend(self._validate_deployment_playbook(parsed))
        errors.extend(self._validate_scenario_configuration(parsed))
        errors.extend(self._validate_verification(parsed))
        return errors

    def _files(self) -> dict[Path, str]:
        """Build expected artifacts from the owning export state."""
        scenario = self.scenario_path
        return {
            self.state.get_run_playbook_path(): self._deployment_playbook(),
            self.project_path / "molecule" / "requirements.yml": self._requirements(),
            self.project_path / "molecule" / "README.md": self._instructions(),
            scenario / "molecule.yml": self._molecule_config(),
            scenario / "prepare.yml": self._prepare_playbook(),
            scenario / "converge.yml": self._converge_playbook(),
        }

    def _deployment_playbook(self) -> str:
        return f"""---
- name: Run migrated role {self.state.module}
  hosts: all
  gather_facts: true
  tasks:
    - name: Apply {self.state.module} role
      ansible.builtin.include_role:
        name: {self.state.get_ansible_fqcn()}
"""

    @staticmethod
    def _requirements() -> str:
        return """---
collections:
  - name: containers.podman
    version: ">=1.10.0"
"""

    def _molecule_config(self) -> str:
        return f"""---
dependency:
  name: galaxy
  options:
    requirements-file: molecule/requirements.yml
  env:
    ANSIBLE_COLLECTIONS_PATH: ${{MOLECULE_PROJECT_DIRECTORY}}/collections

driver:
  name: podman

platforms:
  - name: x2a_{self.state.module}
    image: ${{X2A_MOLECULE_IMAGE:-{DEFAULT_LINUX_IMAGE}}}
    command: /sbin/init
    systemd: always
    privileged: true

provisioner:
  name: ansible

ansible:
  executor:
    backend: ansible-playbook
  env:
    ANSIBLE_COLLECTIONS_PATH: ${{MOLECULE_PROJECT_DIRECTORY}}/collections
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
  ansible.builtin.import_playbook: ../../run_{self.state.module}.yml
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

    def _load_yaml_documents(self) -> dict[Path, Any | Exception]:
        documents: dict[Path, Any | Exception] = {}
        yaml_files = (
            path for path in self._files() if path.suffix in {".yml", ".yaml"}
        )
        for path in yaml_files:
            try:
                with path.open(encoding="utf-8") as stream:
                    documents[path] = list(yaml.safe_load_all(stream))
            except (OSError, yaml.YAMLError) as error:
                documents[path] = error
        verify_path = self.scenario_path / "verify.yml"
        if verify_path.exists():
            try:
                with verify_path.open(encoding="utf-8") as stream:
                    documents[verify_path] = list(yaml.safe_load_all(stream))
            except (OSError, yaml.YAMLError) as error:
                documents[verify_path] = error
        return documents

    def _validate_deployment_playbook(self, parsed: dict[str, Any]) -> list[str]:
        path = self.state.get_run_playbook_path()
        plays = self._first_document(parsed, path)
        role_names = [
            task.get("ansible.builtin.include_role", {}).get("name")
            for play in plays or []
            if isinstance(play, dict)
            for task in play.get("tasks", [])
            if isinstance(task, dict)
        ]
        if self.state.get_ansible_fqcn() not in role_names:
            return [
                f"Deployment playbook does not include {self.state.get_ansible_fqcn()}: {path}"
            ]
        converge = self._first_document(parsed, self.scenario_path / "converge.yml")
        if not self._contains_value(converge, f"../../run_{self.state.module}.yml"):
            return [
                "Molecule converge does not import this module's deployment playbook"
            ]
        return []

    def _validate_scenario_configuration(self, parsed: dict[str, Any]) -> list[str]:
        config = self._first_document(parsed, self.scenario_path / "molecule.yml")
        if not isinstance(config, dict):
            return ["Molecule configuration must contain one YAML mapping"]
        if config.get("driver", {}).get("name") != "podman":
            return ["Molecule configuration must use the native Podman driver"]
        platforms = config.get("platforms", [])
        if not platforms or not all(
            isinstance(platform, dict)
            and platform.get("command") == "/sbin/init"
            and platform.get("systemd") == "always"
            and platform.get("privileged") is True
            and "X2A_MOLECULE_IMAGE" in str(platform.get("image", ""))
            for platform in platforms
        ):
            return [
                "Molecule platforms must use configurable privileged systemd images"
            ]
        ansible = config.get("ansible", {})
        sequence = config.get("scenario", {}).get("test_sequence", [])
        if not ansible.get("executor") or not ansible.get("playbooks"):
            return [
                "Molecule configuration must define the Ansible executor and playbooks"
            ]
        required_playbooks = {"prepare", "converge", "verify"}
        if not required_playbooks.issubset(ansible.get("playbooks", {})):
            return ["Molecule configuration must map prepare, converge, and verify"]
        dependency = config.get("dependency", {})
        if (
            dependency.get("options", {}).get("requirements-file")
            != "molecule/requirements.yml"
        ):
            return ["Molecule dependency must reference molecule/requirements.yml"]
        collections_path = "${MOLECULE_PROJECT_DIRECTORY}/collections"
        if (
            dependency.get("env", {}).get("ANSIBLE_COLLECTIONS_PATH")
            != collections_path
        ):
            return [
                "Molecule dependency must install into the project collections path"
            ]
        if ansible.get("env", {}).get("ANSIBLE_COLLECTIONS_PATH") != collections_path:
            return ["Molecule executor must use the project collections path"]
        required_actions = {
            "create",
            "prepare",
            "converge",
            "idempotence",
            "verify",
            "destroy",
        }
        if not required_actions.issubset(sequence):
            return [
                "Molecule test sequence must include lifecycle, idempotence, and verify"
            ]
        requirements = self._first_document(
            parsed, self.project_path / "molecule" / "requirements.yml"
        )
        collections = (
            requirements.get("collections", [])
            if isinstance(requirements, dict)
            else []
        )
        if not any(
            isinstance(item, dict) and item.get("name") == "containers.podman"
            for item in collections
        ):
            return ["Molecule test requirements must install containers.podman"]
        return []

    def _validate_verification(self, parsed: dict[str, Any]) -> list[str]:
        verify = self._first_document(parsed, self.scenario_path / "verify.yml")
        assertions = self._assertions(verify)
        if not assertions:
            return ["verify.yml must contain at least one behavior assertion"]
        if not all(
            self._has_concrete_condition(item.get("that")) for item in assertions
        ):
            return ["verify.yml assertions must check concrete expected behavior"]
        if not any(
            isinstance(play, dict) and play.get("hosts") == "all" for play in verify
        ):
            return ["verify.yml must target all driver-provisioned Molecule instances"]
        return []

    @staticmethod
    def _first_document(parsed: dict[str, Any], path: Path) -> Any:
        documents = parsed.get(str(path))
        if not isinstance(documents, list) or not documents:
            return None
        return documents[0]

    @classmethod
    def _contains_value(cls, value: Any, expected: str) -> bool:
        if isinstance(value, dict):
            return any(
                cls._contains_value(key, expected)
                or cls._contains_value(item, expected)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(cls._contains_value(item, expected) for item in value)
        return value == expected

    @staticmethod
    def _assertions(verify: Any) -> list[dict[str, Any]]:
        if not isinstance(verify, list):
            return []
        return [
            task["ansible.builtin.assert"]
            for play in verify
            if isinstance(play, dict)
            for task in play.get("tasks", [])
            if isinstance(task, dict)
            and isinstance(task.get("ansible.builtin.assert"), dict)
        ]

    @classmethod
    def _has_concrete_condition(cls, conditions: Any) -> bool:
        if isinstance(conditions, bool) or conditions is None:
            return False
        if isinstance(conditions, list):
            return any(cls._has_concrete_condition(item) for item in conditions)
        if isinstance(conditions, str):
            return conditions.strip().lower() != "true"
        return True
