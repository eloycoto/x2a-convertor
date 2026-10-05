"""State management for infrastructure-to-Ansible migration workflow.

This module defines the state object that tracks the migration process
through its various phases. Technology-agnostic.
"""

from dataclasses import dataclass, field, replace
from pathlib import Path

from src.types import (
    AAPDiscoveryResult,
    AnsibleModule,
    BaseState,
    Checklist,
    CredentialConfig,
    DocumentFile,
    MigrationStateInterface,
)
from src.types.checklist import ChecklistStats
from src.types.technology import Technology

# Constants
ANSIBLE_PROJECT_PATH = Path("ansible")
ANSIBLE_PATH_TEMPLATE = (
    "ansible/collections/ansible_collections/x2a/project/roles/{module}"
)
CHECKLIST_FILENAME = ".checklist.json"


@dataclass
class ExportState(BaseState, MigrationStateInterface):
    """State object for tracking infrastructure-to-Ansible migration workflow.

    Inherits from BaseState for common fields (user_message, path, telemetry,
    failed, failure_reason).

    This is the aggregate root for the migration domain in DDD terms.
    All domain state flows through this object, making agents stateless
    and ensuring proper separation of concerns.

    This state is passed through the LangGraph workflow and tracks:
    - Source module information
    - Migration plans and documentation
    - Workflow phase and attempt counters
    - Validation reports and outputs
    - Migration checklist (domain state)
    - Failure state and reason

    Migration-specific attributes:
        module: AnsibleModule value object representing the module being migrated
        module_migration_plan: Detailed migration plan document
        high_level_migration_plan: High-level migration strategy document
        directory_listing: List of files in the source directory
        current_phase: Current phase of the migration workflow
        write_attempt_counter: Number of write attempts made
        validation_attempt_counter: Number of validation attempts made
        validation_report: Latest validation report
        last_output: Last output from the workflow
        checklist: Migration checklist tracking file transformations
        aap_discovery: Result of AAP collection discovery for deduplication
        credential_config: Extracted credential configuration for AAP
        review_report: Semantic review findings and fixes from ReviewAgent
    """

    # Fields inherited from BaseState:
    # - user_message: str
    # - path: str
    # - telemetry: Telemetry | None (kw_only)
    # - failed: bool (kw_only)
    # - failure_reason: str (kw_only)

    # Migration-specific fields (all keyword-only since they follow kw_only fields from BaseState)
    module: AnsibleModule = field(kw_only=True)
    module_migration_plan: DocumentFile = field(kw_only=True)
    high_level_migration_plan: DocumentFile = field(kw_only=True)
    directory_listing: list[str] = field(kw_only=True)
    current_phase: str = field(kw_only=True)
    write_attempt_counter: int = field(kw_only=True)
    validation_attempt_counter: int = field(kw_only=True)
    validation_report: str = field(kw_only=True)
    last_output: str = field(kw_only=True)
    checklist: Checklist | None = field(default=None, kw_only=True)
    aap_discovery: AAPDiscoveryResult | None = field(default=None, kw_only=True)
    credential_config: CredentialConfig | None = field(default=None, kw_only=True)
    source_technology: Technology = field(default=Technology.CHEF, kw_only=True)
    review_report: str = field(default="", kw_only=True)
    molecule_status: str = field(default="not_generated", kw_only=True)
    molecule_report: str = field(default="", kw_only=True)

    def get_ansible_path(self) -> str:
        """Get the Ansible output path for this module.

        Returns:
            Path string for the role in the adjacent Ansible collection
        """
        return ANSIBLE_PATH_TEMPLATE.format(module=str(self.module))

    def get_ansible_project_path(self) -> Path:
        """Get the root path for the Ansible project containing this role."""
        return ANSIBLE_PROJECT_PATH

    def get_ansible_fqcn(self) -> str:
        """Get the role's fully qualified collection name."""
        return f"x2a.project.{self.module}"

    def get_run_playbook_path(self) -> Path:
        """Get this module's project-level deployment playbook path."""
        return self.get_ansible_project_path() / f"run_{self.module}.yml"

    def get_molecule_scenario_path(self) -> Path:
        """Get this module's project-level Molecule scenario path."""
        return self.get_ansible_project_path() / "molecule" / str(self.module)

    def get_molecule_checklist_targets(self) -> dict[str, str]:
        """Return deterministic project and scenario artifacts owned by Molecule."""
        scenario = self.get_molecule_scenario_path()
        targets = {
            self.get_run_playbook_path(): "Deployment entry point for the migrated role",
            self.get_ansible_project_path()
            / "molecule"
            / "requirements.yml": "Test-only Podman collection dependency",
            self.get_ansible_project_path()
            / "molecule"
            / "README.md": "Developer instructions for running Molecule",
        }
        targets.update(
            {
                scenario / relative: description
                for relative, description in {
                    "molecule.yml": "Ansible-native Molecule scenario configuration",
                    "prepare.yml": "Bootstrap Python on the disposable Linux target",
                    "converge.yml": "Run the deployment playbook under test",
                    "verify.yml": "Verify migrated behavior against the source plan",
                }.items()
            }
        )
        return {str(path): description for path, description in targets.items()}

    def ensure_molecule_checklist(self) -> None:
        """Add deterministic Molecule artifacts to the migration checklist."""
        if self.checklist is None:
            return
        for target_path, description in self.get_molecule_checklist_targets().items():
            self.checklist.add_task(
                category="molecule",
                source_path="N/A",
                target_path=target_path,
                description=description,
            )

    def get_checklist_path(self) -> Path:
        """Get the path to the checklist JSON file.

        Returns:
            Path object pointing to the checklist file
        """
        return Path(self.get_ansible_path()) / CHECKLIST_FILENAME

    def update(self, **kwargs) -> "ExportState":
        """Create a new ExportState instance with updated fields.

        Args:
            **kwargs: Fields to update (must be valid ExportState attributes)

        Returns:
            New ExportState instance with updated fields

        Example:
            new_state = state.update(checklist=new_checklist, current_phase="writing")
        """
        return replace(self, **kwargs)

    def mark_failed(self, reason: str) -> "ExportState":
        """Mark this migration as failed with a reason.

        Args:
            reason: Human-readable failure reason

        Returns:
            New ExportState with failed=True and failure_reason set
        """
        return self.update(failed=True, failure_reason=reason)

    def did_fail(self) -> bool:
        """Check if the migration failed.

        Returns:
            True if migration failed, False otherwise
        """
        return self.failed

    def get_failure_reason(self) -> str:
        """Get the reason for migration failure.

        Returns:
            Human-readable failure reason string, empty if not failed
        """
        return self.failure_reason

    def get_output(self) -> str:
        """Get the final migration output/summary.

        Returns:
            Migration output string (success or failure summary)
        """
        return self.last_output

    def report_status(self) -> str:
        """Build the full human-readable migration report."""
        assert self.checklist is not None, (
            "Checklist must be initialized before reporting"
        )
        checklist = self.checklist
        stats = checklist.get_stats()
        lines = (
            self._failure_report(stats, checklist)
            if self.failed
            else self._success_report(stats, checklist)
        )

        if self.telemetry:
            lines.extend(
                ["", "## Telemetry", "", "```", self.telemetry.to_summary(), "```"]
            )

        return "\n".join(lines)

    def _failure_report(self, stats: ChecklistStats, checklist: Checklist) -> list[str]:
        """Build summary lines for a failed migration."""
        lines = [
            f"# MIGRATION FAILED for {self.module}",
            "",
            f"**Failure Reason:** {self.failure_reason}",
            "",
            "## Migration Summary",
            "",
            stats.to_markdown(),
            f"- **Write attempts:** {self.write_attempt_counter}",
            f"- **Validation attempts:** {self.validation_attempt_counter}",
            "",
            "## Partial Validation Report",
            "",
            self.validation_report or "_Not run_",
        ]
        if self.review_report:
            lines.extend(["", "### Review Report", "", self.review_report])
        lines.extend(self._molecule_report_lines())
        lines.extend(["", "### Partial Checklist", "", checklist.to_markdown()])
        return lines

    def _success_report(self, stats: ChecklistStats, checklist: Checklist) -> list[str]:
        """Build summary lines for a successful migration."""
        lines = [
            f"# Migration Summary for {self.module}",
            "",
            stats.to_markdown(),
            f"- **Write attempts:** {self.write_attempt_counter}",
            f"- **Validation attempts:** {self.validation_attempt_counter}",
            "",
            "## Final Validation Report",
            "",
            self.validation_report,
        ]
        if self.review_report:
            lines.extend(["", "### Review Report", "", str(self.review_report)])
        lines.extend(self._molecule_report_lines())
        lines.extend(["", "### Final Checklist", "", checklist.to_markdown()])
        return lines

    def _molecule_report_lines(self) -> list[str]:
        """Report generated test status without implying runtime execution."""
        if self.molecule_status == "not_generated":
            return []
        return [
            "",
            "### Molecule Test Generation",
            "",
            f"**Status:** {self.molecule_status}",
            "",
            self.molecule_report
            or "Molecule tests were not executed by the converter.",
        ]
