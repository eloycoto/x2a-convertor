"""Create Ansible playbook projects and collection roles with ansible-creator."""

from pathlib import Path
from typing import Any, Self

from ansible_creator.api import V1, CreatorResult

from src.exporters.services.ansible_project_layout import (
    DEFAULT_NAMESPACE,
    DEFAULT_PROJECT,
    AnsibleProjectLayout,
)
from src.types import AnsibleModule


class AnsibleCreator:
    """Execute ansible-creator operations through its Python API."""

    def __init__(self, api: V1 | None = None) -> None:
        self.api = api or V1()

    def run(self, *command: str, **arguments: Any) -> CreatorResult:
        """Run a creator API operation and raise if scaffolding fails."""
        result = self.api.run(*command, **arguments)
        if result.status != "success":
            raise RuntimeError(result.message or f"ansible-creator failed: {command}")
        return result


class AnsibleProject:
    """An Ansible playbook project containing an adjacent collection."""

    def __init__(
        self,
        path: str | Path,
        creator: AnsibleCreator | None = None,
        namespace: str = DEFAULT_NAMESPACE,
        project_name: str = DEFAULT_PROJECT,
    ) -> None:
        self.path = Path(path)
        self.creator = creator or AnsibleCreator()
        self.namespace = namespace
        self.project_name = project_name

    @classmethod
    def ensure(
        cls,
        path: str | Path,
        creator: AnsibleCreator | None = None,
        namespace: str = DEFAULT_NAMESPACE,
        project_name: str = DEFAULT_PROJECT,
    ) -> Self:
        """Initialize an absent playbook project and return its project wrapper."""
        project_path = Path(path)
        project_creator = creator or AnsibleCreator()
        if not project_path.exists() or not any(project_path.iterdir()):
            project_creator.run(
                "init",
                "playbook",
                collection=f"{namespace}.{project_name}",
                init_path=str(project_path),
            )
        return cls(project_path, project_creator, namespace, project_name)

    @property
    def collection_path(self) -> Path:
        """Return the adjacent collection directory in the playbook project."""
        return (
            self.path
            / "collections"
            / "ansible_collections"
            / self.namespace
            / self.project_name
        )

    def create_role(self, name: str) -> Path:
        """Scaffold a role in the adjacent collection and return its path."""
        role_name = str(AnsibleModule(name))
        role_path = self.collection_path / "roles" / role_name
        if self.check_role(role_name):
            return role_path
        if role_path.exists():
            raise RuntimeError(
                f"Role already exists but is incomplete; refusing to overwrite {role_path}"
            )

        self.creator.run(
            "add",
            "resource",
            "role",
            role_name=role_name,
            path=str(self.collection_path),
        )
        if not self.check_role(role_name):
            raise RuntimeError(f"ansible-creator did not create role at {role_path}")
        return role_path

    def check_role(self, name: str) -> bool:
        """Return whether the named role has its expected scaffold files."""
        role_path = self.collection_path / "roles" / str(AnsibleModule(name))
        return (role_path / "tasks" / "main.yml").is_file() and (
            role_path / "meta" / "main.yml"
        ).is_file()

    def layout(self, module: AnsibleModule) -> AnsibleProjectLayout:
        """Build layout metadata using this project's configured identity."""
        return AnsibleProjectLayout.from_module(
            module,
            project_path=self.path,
            namespace=self.namespace,
            project_name=self.project_name,
        )
