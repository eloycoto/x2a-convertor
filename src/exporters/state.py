"""State management for Chef to Ansible migration workflow.

This module defines the state object that tracks the migration process
through its various phases.
"""

from dataclasses import dataclass
from pathlib import Path

from src.types import DocumentFile


# Constants
ANSIBLE_PATH_TEMPLATE = "./ansible/{module}"
CHECKLIST_FILENAME = ".checklist.json"


@dataclass
class ChefState:
    """State object for tracking Chef to Ansible migration workflow.

    This state is passed through the LangGraph workflow and tracks:
    - Source Chef module information
    - Migration plans and documentation
    - Workflow phase and attempt counters
    - Validation reports and outputs

    Attributes:
        path: Path to the Chef cookbook/module
        module: Name of the module being migrated
        user_message: Original user message/requirements
        module_migration_plan: Detailed migration plan document
        high_level_migration_plan: High-level migration strategy document
        directory_listing: List of files in the source directory
        current_phase: Current phase of the migration workflow
        write_attempt_counter: Number of write attempts made
        validation_attempt_counter: Number of validation attempts made
        validation_report: Latest validation report
        last_output: Last output from the workflow
    """

    path: str
    module: str
    user_message: str
    module_migration_plan: DocumentFile
    high_level_migration_plan: DocumentFile
    directory_listing: list[str]
    current_phase: str
    write_attempt_counter: int
    validation_attempt_counter: int
    validation_report: str
    last_output: str

    def get_ansible_path(self) -> str:
        """Get the Ansible output path for this module.

        Returns:
            Path string in format ./ansible/{module}
        """
        return ANSIBLE_PATH_TEMPLATE.format(module=self.module)

    def get_checklist_path(self) -> Path:
        """Get the path to the checklist JSON file.

        Returns:
            Path object pointing to the checklist file
        """
        return Path(self.get_ansible_path()) / CHECKLIST_FILENAME
