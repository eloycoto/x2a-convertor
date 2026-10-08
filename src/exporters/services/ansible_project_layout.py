"""Filesystem layout for the generated Ansible project and collection role."""

from dataclasses import dataclass
from pathlib import Path

from src.types import AnsibleModule

DEFAULT_NAMESPACE = "x2a"
DEFAULT_PROJECT = "project"
ANSIBLE_PROJECT_PATH = Path("ansible")


@dataclass(frozen=True)
class AnsibleProjectLayout:
    """Paths and names derived from one migrated module."""

    module: AnsibleModule
    namespace: str
    project_name: str
    project_path: Path
    role_path: Path
    fqcn: str
    run_playbook_path: Path
    molecule_scenario_path: Path

    @classmethod
    def from_module(
        cls,
        module: AnsibleModule,
        project_path: str | Path = ANSIBLE_PROJECT_PATH,
        namespace: str = DEFAULT_NAMESPACE,
        project_name: str = DEFAULT_PROJECT,
    ) -> "AnsibleProjectLayout":
        """Build the complete project layout from its module and project identity."""
        project = Path(project_path)
        role_name = str(module)
        return cls(
            module=module,
            namespace=namespace,
            project_name=project_name,
            project_path=project,
            role_path=(
                project
                / "collections"
                / "ansible_collections"
                / namespace
                / project_name
                / "roles"
                / role_name
            ),
            fqcn=f"{namespace}.{project_name}.{role_name}",
            run_playbook_path=project / f"run_{role_name}.yml",
            molecule_scenario_path=project / "molecule" / role_name,
        )

    @property
    def molecule_requirements_path(self) -> Path:
        """Return the shared test collection requirements path."""
        return self.project_path / "molecule" / "requirements.yml"

    @property
    def molecule_readme_path(self) -> Path:
        """Return the shared Molecule usage guide path."""
        return self.project_path / "molecule" / "README.md"

    @property
    def molecule_verify_path(self) -> Path:
        """Return this scenario's verification playbook path."""
        return self.molecule_scenario_path / "verify.yml"

    def molecule_checklist_targets(self) -> dict[str, str]:
        """Return the deterministic project/scenario artifacts owned by Molecule."""
        scenario = self.molecule_scenario_path
        targets = {
            self.run_playbook_path: "Deployment entry point for the migrated role",
            self.molecule_requirements_path: "Test-only Podman collection dependency",
            self.molecule_readme_path: "Developer instructions for running Molecule",
            scenario / "molecule.yml": "Ansible-native Molecule scenario configuration",
            scenario / "prepare.yml": "Bootstrap Python on the disposable Linux target",
            scenario / "converge.yml": "Run the deployment playbook under test",
            self.molecule_verify_path: "Verify migrated behavior against the source plan",
        }
        return {str(path): description for path, description in targets.items()}
