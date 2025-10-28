from enum import Enum
from pathlib import Path
from typing import Literal, Optional

from langchain_community.tools.file_management.file_search import FileSearchTool
from langchain_community.tools.file_management.list_dir import ListDirectoryTool
from langchain_community.tools.file_management.read import ReadFileTool
from langchain_community.tools.file_management.write import WriteFileTool
from langchain_core.messages.tool import ToolMessage
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import create_react_agent

from src.types import DocumentFile
from src.exporters.state import ChefState
from src.exporters.types import MigrationCategory
from src.model import (
    get_model,
    get_last_ai_message,
    report_tool_calls,
    get_runnable_config,
)
from src.types import (
    SUMMARY_SUCCESS_MESSAGE,
    AnsibleModule,
    Checklist,
    ChecklistStatus,
)
from src.utils.config import get_config_int
from src.utils.logging import get_logger
from src.validation.service import ValidationService
from src.validation.validators import AnsibleLintValidator, RoleStructureValidator
from prompts.get_prompt import get_prompt
from tools.ansible_lint import ANSIBLE_LINT_TOOL_SUCCESS_MESSAGE, AnsibleLintTool
from tools.ansible_role_check import AnsibleRoleCheckTool
from tools.ansible_write import AnsibleWriteTool
from tools.copy_file import CopyFileWithMkdirTool
from tools.diff_file import DiffFileTool

logger = get_logger(__name__)


# Constants
PROCESSABLE_STATUSES = {
    ChecklistStatus.PENDING,
    ChecklistStatus.MISSING,
    ChecklistStatus.ERROR,
}

ROLE_VALIDATION_SUCCESS_MESSAGE = "Role Validation Passed"


class MigrationPhase(str, Enum):
    """Phases of the migration workflow"""

    INITIALIZING = "initializing"
    PLANNING = "planning"
    WRITING = "writing"
    VALIDATING = "validating"
    COMPLETE = "complete"


class AgentType(str, Enum):
    """Types of agents used in the migration workflow"""

    PLANNING = "planning"
    WRITE = "write"
    VALIDATION = "validation"


class ChefToAnsibleSubagent:
    """Subagent called by the MigrationAgent to do the actual Chef -> Ansible export

    Uses a three-agent workflow:
    1. Planning Agent: Analyzes migration plan and creates detailed checklist
    2. Write Agent: Creates all files from checklist (loops until all files exist)
    3. Validation Agent: Runs lint/role-check and fixes issues in batch mode
    """

    # Configuration mapping: agent type -> list of tool factory functions
    # This serves as a single source of truth for agent tool configurations
    AGENT_TOOL_CONFIGS = {
        AgentType.PLANNING: [
            lambda: ListDirectoryTool(),
            lambda: ReadFileTool(),
            lambda: FileSearchTool(),
        ],
        AgentType.WRITE: [
            lambda: FileSearchTool(),
            lambda: ListDirectoryTool(),
            lambda: ReadFileTool(),
            lambda: WriteFileTool(),
            lambda: CopyFileWithMkdirTool(),
            lambda: AnsibleWriteTool(),
            lambda: AnsibleLintTool(),
        ],
        AgentType.VALIDATION: [
            lambda: ReadFileTool(),
            lambda: DiffFileTool(),
            lambda: ListDirectoryTool(),
            lambda: FileSearchTool(),
            lambda: WriteFileTool(),
            lambda: AnsibleWriteTool(),
            lambda: CopyFileWithMkdirTool(),
            lambda: AnsibleLintTool(),
            lambda: AnsibleRoleCheckTool(),
        ],
    }

    def __init__(self, model=None, module: Optional[str] = None) -> None:
        self.model = model or get_model()
        if module is None:
            raise ValueError("module parameter is required")
        self.module = AnsibleModule(module)
        self.checklist: Checklist = Checklist(str(self.module), MigrationCategory)

        # NEW: Initialize validators for new architecture
        self.validators = [
            AnsibleLintValidator(),
            RoleStructureValidator(),
        ]
        self.validation_service = ValidationService(self.validators)

        self._workflow = self._create_workflow()
        logger.debug(self._workflow.get_graph().draw_mermaid())

    def _create_agent(self, agent_type: AgentType, pre_model_hook=None):
        """Factory method to create an agent with configured tools

        Args:
            agent_type: Type of agent to create (planning, execution, or validation)
            pre_model_hook: Optional hook to run before model invocation

        Returns:
            Configured react agent with appropriate tools
        """
        logger.info(f"Creating migration {agent_type.value} agent")

        # Get base tools for this agent type
        tool_factories = self.AGENT_TOOL_CONFIGS.get(agent_type, [])
        tools = [factory() for factory in tool_factories]

        # All agents get checklist tools
        tools.extend(self.checklist.get_tools())

        # pyrefly: ignore
        agent = create_react_agent(
            model=self.model,
            tools=tools,
            pre_model_hook=pre_model_hook,
        )
        return agent

    def _create_planning_agent(self):
        """Create agent for analyzing migration plan and building checklist"""
        return self._create_agent(AgentType.PLANNING)

    def _create_write_agent(self):
        """Create agent for writing all files from checklist"""
        return self._create_agent(AgentType.WRITE)

    def _create_validation_agent(self):
        """Create agent for validating migration completeness and correctness"""
        return self._create_agent(AgentType.VALIDATION)

    def _create_workflow(self):
        workflow = StateGraph(ChefState)
        workflow.add_node("plan_migration", lambda state: self._plan_migration(state))
        workflow.add_node("write_migration", lambda state: self._write_migration(state))
        workflow.add_node(
            "validate_migration", lambda state: self._validate_migration(state)
        )
        workflow.add_node("finalize", lambda state: self._finalize(state))

        workflow.add_edge(START, "plan_migration")
        workflow.add_edge("plan_migration", "write_migration")
        workflow.add_conditional_edges("write_migration", self._evaluate_write)
        workflow.add_conditional_edges("validate_migration", self._evaluate_validation)
        workflow.add_edge("finalize", END)

        return workflow.compile()

    def _load_checklist(self, state: ChefState):
        checklist_path = state.get_checklist_path()
        if checklist_path.exists():
            logger.info(f"Loaded checklist from previous run: {checklist_path}")
            self.checklist = self.checklist.load(checklist_path, MigrationCategory)
            return

        logger.info(f"Created empty checklist at {checklist_path}")
        checklist_path.parent.mkdir(parents=True, exist_ok=True)
        self.checklist.save(checklist_path)

    def _plan_migration(self, state: ChefState) -> ChefState:
        """Phase 1: Analyze migration plan and create detailed checklist"""
        slog = logger.bind(phase="plan_migration")
        slog.info("Planning migration: analyzing migration plan and creating checklist")
        state.current_phase = MigrationPhase.PLANNING
        self._load_checklist(state)

        # Create planning agent with checklist tools
        planning_agent = self._create_planning_agent()

        system_message = get_prompt("export_ansible_planning_system")

        user_prompt = get_prompt("export_ansible_planning_task").format(
            module=state.module,
            high_level_migration_plan=state.high_level_migration_plan.to_document(),
            module_migration_plan=state.module_migration_plan.to_document(),
            directory_listing="\n".join(state.directory_listing),
            path=state.path,
            existing_checklist=self.checklist.to_markdown(),
        )

        result = planning_agent.invoke(
            {
                "messages": [
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_prompt},
                ]
            },
            get_runnable_config(),
        )
        slog.info(f"Planning agent tools: {report_tool_calls(result).to_string()}")
        self.checklist.save(state.get_checklist_path())
        slog.info(f"Checklist after planning:\n{self.checklist.to_markdown()}")

        return state

    def _write_migration(self, state: ChefState) -> ChefState:
        """Phase 2: Write all files from checklist"""
        slog = logger.bind(phase="write_migration", attempt=state.write_attempt_counter)
        slog.info("Writing migration files")
        state.current_phase = MigrationPhase.WRITING

        slog.debug(f"Checklist before writing:\n{self.checklist.to_markdown()}")

        checklist_path = state.get_checklist_path()
        # Check if all files are already created
        if all(item.target_exists() for item in self.checklist.items):
            slog.info("All files already created!")
            return state

        write_agent = self._create_write_agent()

        checklist_md = self.checklist.to_markdown()
        ansible_path = state.get_ansible_path()

        system_message = get_prompt("export_ansible_write_system")
        user_prompt = get_prompt("export_ansible_write_task").format(
            module=state.module,
            chef_path=state.path,
            ansible_path=ansible_path,
            high_level_migration_plan=state.high_level_migration_plan.to_document(),
            migration_plan=state.module_migration_plan.to_document(),
            checklist=checklist_md,
        )
        result = write_agent.invoke(
            input={
                "messages": [
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_prompt},
                ]
            },
            config=get_runnable_config(),
        )
        slog.info(f"Write agent tools: {report_tool_calls(result).to_string()}")
        self.checklist.save(checklist_path)

        slog.info(f"Checklist after writing:\n{self.checklist.to_markdown()}")
        message = get_last_ai_message(result)
        if message:
            state.last_output = message.content
            slog.info("Write phase completed")
        else:
            slog.warning("Write agent did not produce output")

        state.write_attempt_counter += 1
        return state

    def _validate_role_check(self, state: ChefState) -> tuple[bool, str]:
        """Structural validation (delegates to new validator)"""
        slog = logger.bind(phase="validate_migration_role_check")
        ansible_path = state.get_ansible_path()
        slog.info(f"Running ansible_role_check on {ansible_path}")

        # Delegate to new validator
        validator = self.validators[1]  # RoleStructureValidator
        result = validator.validate(ansible_path)

        # Log appropriate message
        if result.success:
            if "warning" in result.message.lower():
                slog.info(
                    "Role validation passed with warnings (check-mode limitations)"
                )
            else:
                slog.info("Role validation passed")
        else:
            slog.warning(f"Role validation has issues: {result.message}")

        # Convert to tuple for backward compatibility
        return result.success, result.message

    def _validate_ansible_lint(self, state: ChefState) -> tuple[bool, str]:
        """Run ansible_lint (delegates to new validator)"""
        slog = logger.bind(phase="validate_migration_ansible_lint")
        slog.info("Validating ansible_lint")

        ansible_path = state.get_ansible_path()

        # Delegate to new validator
        validator = self.validators[0]  # AnsibleLintValidator
        result = validator.validate(ansible_path)

        # Convert to tuple for backward compatibility
        return result.success, result.message

    def _validate_migration(self, state: ChefState) -> ChefState:
        """Phase 3: Validate and fix issues in batch mode.

        Uses the new service-based validation architecture with clean separation of concerns.
        """
        slog = logger.bind(
            phase="validate_migration", attempt=state.validation_attempt_counter
        )
        slog.info("Validating and fixing migration output")
        state.current_phase = MigrationPhase.VALIDATING
        state.validation_report = ""

        ansible_path = state.get_ansible_path()
        checklist_md = self.checklist.to_markdown()

        # Simple, clean validation using service
        results = self.validation_service.validate_all(ansible_path)

        # Check if all validations pass
        if not self.validation_service.has_errors(results):
            slog.info("All validations passed")
            state.validation_report = (
                f"{SUMMARY_SUCCESS_MESSAGE}\n\n"
                + self.validation_service.get_success_message(results)
            )
            state.validation_attempt_counter += 1
            return state

        # Format errors for agent
        error_report = self.validation_service.format_error_report(results)
        slog.warning(f"Validation errors found:\n{error_report}")

        # Create validation agent to fix errors
        validation_agent = self._create_validation_agent()

        validation_system = get_prompt("export_ansible_validation_system")
        validation_task = get_prompt("export_ansible_validation_task").format(
            module=state.module,
            chef_path=state.path,
            ansible_path=ansible_path,
            high_level_migration_plan=state.high_level_migration_plan.to_document(),
            migration_plan=state.module_migration_plan.to_document(),
            checklist=checklist_md,
            error_report=error_report,
            fragment_yaml_hints=get_prompt("fragment_yaml_hints"),
        )

        result = validation_agent.invoke(
            {
                "messages": [
                    {"role": "system", "content": validation_system},
                    {"role": "user", "content": validation_task},
                ]
            },
            get_runnable_config(),
        )

        slog.info(f"Validation agent tools: {report_tool_calls(result).to_string()}")
        self.checklist.save(state.get_checklist_path())

        # Extract validation report
        message = get_last_ai_message(result)
        state.validation_report = message.content if message else "No validation output"

        slog.info("Validation phase completed")
        state.validation_attempt_counter += 1

        return state

    def _evaluate_write(
        self, state: ChefState
    ) -> Literal["write_migration", "validate_migration"]:
        """Decide whether to retry writing or proceed to validation"""
        slog = logger.bind(phase="evaluate_write")
        slog.info("Evaluating write results")

        # Check file existence for all checklist items
        missing_files = []
        for item in self.checklist.items:
            if not item.target_exists():
                missing_files.append(item.target_path)
                self.checklist.update_task(
                    item.source_path, item.target_path, ChecklistStatus.MISSING
                )

        self.checklist.save(state.get_checklist_path())
        slog.info("All files created, proceeding to validation")

        if missing_files:
            slog.warning(f"Missing {len(missing_files)} files: {missing_files[:5]}...")
            if state.write_attempt_counter >= get_config_int("MAX_WRITE_ATTEMPTS"):
                slog.error(
                    f"Max write attempts ({get_config_int('MAX_WRITE_ATTEMPTS')}) reached, proceeding to validation anyway"
                )
                return "validate_migration"
            slog.info("Retrying write phase")
            return "write_migration"
        return "validate_migration"

    def _evaluate_validation(
        self, state: ChefState
    ) -> Literal["finalize", "validate_migration"]:
        """Decide whether to finalize or retry validation based on results"""
        slog = logger.bind(phase="evaluate_validation")
        slog.info("Evaluating validation results")

        # Check if validation passed
        if SUMMARY_SUCCESS_MESSAGE in state.validation_report:
            slog.info("Migration complete - validation passed")
            return "finalize"

        if state.validation_attempt_counter >= get_config_int(
            "MAX_VALIDATION_ATTEMPTS"
        ):
            slog.error(
                f"Max validation attempts ({get_config_int('MAX_VALIDATION_ATTEMPTS')}) reached, finalizing with validation issues"
            )
            return "finalize"

        slog.info(
            f"Retrying validation phase. Current report: {state.validation_report}"
        )
        return "validate_migration"

    def _finalize(self, state: ChefState) -> ChefState:
        """Finalize migration and report results"""
        slog = logger.bind(phase="finalize")
        slog.info("Finalizing migration")
        state.current_phase = MigrationPhase.COMPLETE

        stats = self.checklist.get_stats()

        summary_lines = [
            f"Migration Summary for {state.module}:",
            f"  Total items: {stats['total']}",
            f"  Completed: {stats['complete']}",
            f"  Pending: {stats['pending']}",
            f"  Missing: {stats['missing']}",
            f"  Errors: {stats['error']}",
            f"  Write attempts: {state.write_attempt_counter}",
            f"  Validation attempts: {state.validation_attempt_counter}",
            "",
            "Final Validation Report:",
            state.validation_report,
            "",
            "Final checklist:",
            self.checklist.to_markdown(),
        ]

        state.last_output = "\n".join(summary_lines)
        slog.info(
            f"Migration finalized: {stats['complete']}/{stats['total']} completed"
        )

        return state

    def invoke(
        self,
        path: str,
        user_message: str,
        module_migration_plan: DocumentFile,
        high_level_migration_plan: DocumentFile,
        directory_listing: list[str],
    ) -> ChefState:
        """Execute the complete Chef to Ansible migration workflow"""
        logger.info(f"Starting Chef to Ansible migration for module: {self.module}")

        initial_state = ChefState(
            path=path,
            module=self.module,
            user_message=user_message,
            module_migration_plan=module_migration_plan,
            high_level_migration_plan=high_level_migration_plan,
            directory_listing=directory_listing,
            current_phase=MigrationPhase.INITIALIZING,
            write_attempt_counter=0,
            validation_attempt_counter=0,
            validation_report="",
            last_output="",
        )

        result = self._workflow.invoke(
            input=initial_state, config=get_runnable_config()
        )
        return ChefState(**result)
