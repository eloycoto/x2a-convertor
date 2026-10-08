"""Static YAML and contract validation for generated Molecule scenarios."""

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from src.exporters.services.ansible_project_layout import AnsibleProjectLayout
from src.exporters.services.molecule_contract import (
    COLLECTIONS_PATH_TEMPLATE,
    MOLECULE_DRIVER,
    PODMAN_COLLECTION,
    REQUIREMENTS_FILE,
    SYSTEMD_COMMAND,
    SYSTEMD_MODE,
)


class MoleculeScenarioValidator:
    """Validate scenario files from paths, independently of their generator."""

    def __init__(self, layout: AnsibleProjectLayout) -> None:
        self.layout = layout

    def validate(self, paths: Iterable[Path]) -> list[str]:
        """Read YAML files and check deployment, configuration, and verify contracts."""
        documents, errors = self._load_yaml_documents(paths)
        if errors:
            return errors
        errors.extend(self._validate_deployment_playbook(documents))
        errors.extend(self._validate_scenario_configuration(documents))
        errors.extend(self._validate_verification(documents))
        return errors

    @staticmethod
    def _load_yaml_documents(
        paths: Iterable[Path],
    ) -> tuple[dict[Path, list[Any]], list[str]]:
        documents: dict[Path, list[Any]] = {}
        errors: list[str] = []
        for path in paths:
            if path.suffix not in {".yml", ".yaml"}:
                continue
            try:
                with path.open(encoding="utf-8") as stream:
                    documents[path] = list(yaml.safe_load_all(stream))
            except (OSError, yaml.YAMLError) as error:
                errors.append(f"Invalid YAML in {path}: {error}")
        return documents, errors

    def _validate_deployment_playbook(
        self, documents: dict[Path, list[Any]]
    ) -> list[str]:
        path = self.layout.run_playbook_path
        plays = self._first_document(documents, path)
        role_names = [
            task.get("ansible.builtin.include_role", {}).get("name")
            for play in plays or []
            if isinstance(play, dict)
            for task in play.get("tasks", [])
            if isinstance(task, dict)
        ]
        if self.layout.fqcn not in role_names:
            return [f"Deployment playbook does not include {self.layout.fqcn}: {path}"]
        converge = self._first_document(
            documents, self.layout.molecule_scenario_path / "converge.yml"
        )
        expected = f"../../{self.layout.run_playbook_path.name}"
        if not self._contains_value(converge, expected):
            return [
                "Molecule converge does not import this module's deployment playbook"
            ]
        return []

    def _validate_scenario_configuration(
        self, documents: dict[Path, list[Any]]
    ) -> list[str]:
        config = self._first_document(
            documents, self.layout.molecule_scenario_path / "molecule.yml"
        )
        if not isinstance(config, dict):
            return ["Molecule configuration must contain one YAML mapping"]
        driver = config.get("driver")
        if not isinstance(driver, dict) or driver.get("name") != MOLECULE_DRIVER:
            return ["Molecule configuration must use the native Podman driver"]
        errors = self._validate_platforms(config.get("platforms", []))
        if errors:
            return errors
        errors = self._validate_ansible_configuration(config)
        if errors:
            return errors
        errors = self._validate_dependencies(config, documents)
        if errors:
            return errors
        sequence = config.get("scenario", {}).get("test_sequence", [])
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
        return []

    @staticmethod
    def _validate_platforms(platforms: Any) -> list[str]:
        if (
            not isinstance(platforms, list)
            or not platforms
            or not all(
                isinstance(platform, dict)
                and platform.get("command") == SYSTEMD_COMMAND
                and platform.get("systemd") == SYSTEMD_MODE
                and platform.get("privileged") is True
                and "X2A_MOLECULE_IMAGE" in str(platform.get("image", ""))
                for platform in platforms
            )
        ):
            return [
                "Molecule platforms must use configurable privileged systemd images"
            ]
        return []

    @staticmethod
    def _validate_ansible_configuration(config: dict[str, Any]) -> list[str]:
        ansible = config.get("ansible")
        if (
            not isinstance(ansible, dict)
            or not ansible.get("executor")
            or not ansible.get("playbooks")
        ):
            return [
                "Molecule configuration must define the Ansible executor and playbooks"
            ]
        if not {"prepare", "converge", "verify"}.issubset(ansible["playbooks"]):
            return ["Molecule configuration must map prepare, converge, and verify"]
        if (
            ansible.get("env", {}).get("ANSIBLE_COLLECTIONS_PATH")
            != COLLECTIONS_PATH_TEMPLATE
        ):
            return ["Molecule executor must use the project collections path"]
        return []

    def _validate_dependencies(
        self, config: dict[str, Any], documents: dict[Path, list[Any]]
    ) -> list[str]:
        dependency = config.get("dependency")
        if not isinstance(dependency, dict):
            return ["Molecule dependency must reference molecule/requirements.yml"]
        if dependency.get("options", {}).get("requirements-file") != REQUIREMENTS_FILE:
            return ["Molecule dependency must reference molecule/requirements.yml"]
        if (
            dependency.get("env", {}).get("ANSIBLE_COLLECTIONS_PATH")
            != COLLECTIONS_PATH_TEMPLATE
        ):
            return [
                "Molecule dependency must install into the project collections path"
            ]
        requirements = self._first_document(
            documents, self.layout.molecule_requirements_path
        )
        collections = (
            requirements.get("collections", [])
            if isinstance(requirements, dict)
            else []
        )
        if not any(
            isinstance(item, dict) and item.get("name") == PODMAN_COLLECTION
            for item in collections
        ):
            return [f"Molecule test requirements must install {PODMAN_COLLECTION}"]
        return []

    def _validate_verification(self, documents: dict[Path, list[Any]]) -> list[str]:
        verify = self._first_document(documents, self.layout.molecule_verify_path)
        if not isinstance(verify, list):
            return ["verify.yml must contain a play targeting all Molecule instances"]
        plays = [
            play
            for play in verify
            if isinstance(play, dict) and play.get("hosts") == "all"
        ]
        if not plays:
            return ["verify.yml must target all driver-provisioned Molecule instances"]
        assertions = [
            assertion for play in plays for assertion in self._assertions(play)
        ]
        if not assertions:
            if all(not play.get("tasks") for play in plays):
                return []
            return ["verify.yml must contain at least one behavior assertion"]
        if not all(
            self._has_concrete_condition(item.get("that")) for item in assertions
        ):
            return ["verify.yml assertions must check concrete expected behavior"]
        return []

    @classmethod
    def _assertions(cls, play: dict[str, Any]) -> list[dict[str, Any]]:
        tasks = play.get("tasks", [])
        if not isinstance(tasks, list):
            return []
        return [
            task["ansible.builtin.assert"]
            for task in tasks
            if isinstance(task, dict)
            and isinstance(task.get("ansible.builtin.assert"), dict)
        ]

    @staticmethod
    def _first_document(documents: dict[Path, list[Any]], path: Path) -> Any:
        yaml_documents = documents.get(path)
        if not yaml_documents:
            return None
        return yaml_documents[0]

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

    @classmethod
    def _has_concrete_condition(cls, conditions: Any) -> bool:
        if isinstance(conditions, bool) or conditions is None:
            return False
        if isinstance(conditions, list):
            return any(cls._has_concrete_condition(item) for item in conditions)
        if isinstance(conditions, str):
            return conditions.strip().lower() != "true"
        return True
