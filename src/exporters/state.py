"""State management for infrastructure-to-Ansible migration workflow.

This module defines the state object that tracks the migration process
through its various phases. Technology-agnostic.
"""

from dataclasses import dataclass, field, replace
from functools import cached_property
from pathlib import Path

from src.exporters.migration_report import MigrationReport
from src.exporters.services.ansible_project_layout import AnsibleProjectLayout
from src.exporters.types import MoleculeStatus
from src.types import (
    AAPDiscoveryResult,
    AnsibleModule,
    BaseState,
    Checklist,
    CredentialConfig,
    DocumentFile,
    MigrationStateInterface,
)
from src.types.technology import Technology

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
    molecule_status: MoleculeStatus = field(
        default=MoleculeStatus.NOT_GENERATED, kw_only=True
    )
    molecule_report: str = field(default="", kw_only=True)

    @cached_property
    def layout(self) -> AnsibleProjectLayout:
        """Return this module's cached Ansible project layout."""
        return AnsibleProjectLayout.from_module(self.module)

    def get_ansible_path(self) -> str:
        """Return the adjacent collection role path for this module."""
        return str(self.layout.role_path)

    def get_ansible_project_path(self) -> Path:
        """Return the project root containing this module's role."""
        return self.layout.project_path

    def get_ansible_fqcn(self) -> str:
        """Return the role's fully qualified collection name."""
        return self.layout.fqcn

    def get_run_playbook_path(self) -> Path:
        """Return this module's project-level deployment playbook path."""
        return self.layout.run_playbook_path

    def get_molecule_scenario_path(self) -> Path:
        """Return this module's project-level Molecule scenario path."""
        return self.layout.molecule_scenario_path

    def get_molecule_checklist_targets(self) -> dict[str, str]:
        """Return deterministic project and scenario artifacts owned by Molecule."""
        return self.layout.molecule_checklist_targets()

    def get_checklist_path(self) -> Path:
        """Get the path to the checklist JSON file.

        Returns:
            Path object pointing to the checklist file
        """
        return self.layout.role_path / CHECKLIST_FILENAME

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
        return MigrationReport.from_state(self).render()
