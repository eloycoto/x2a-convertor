"""APME (Ansible Playbook Migration Engine) integration.

Provides native Python access to APME's formatting, validation, and rule documentation
without subprocess calls.
"""

from dataclasses import dataclass, field
from pathlib import Path

from apme_engine.formatter import (
    FormatResult,
    format_directory,
    format_file,
)
from apme_engine.graph.scanner import (
    GraphScanReport,
    graph_report_to_violations,
    load_graph_rules,
    native_rules_dir,
    scan,
)
from apme_engine.runner import run_scan

from src.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class FormatReport:
    """Summary of formatting operations.

    Attributes:
        files_checked: Total files examined.
        files_changed: Files that were reformatted.
        results: Detailed results per file.
    """

    files_checked: int = 0
    files_changed: int = 0
    results: list[FormatResult] = field(default_factory=list)

    def summary(self) -> str:
        """Return a human-readable summary."""
        if self.files_changed == 0:
            return f"All {self.files_checked} file(s) already formatted."
        return f"Reformatted {self.files_changed}/{self.files_checked} file(s)."


@dataclass
class CheckViolation:
    """A single validation violation.

    Attributes:
        rule_id: Rule identifier (e.g., L021, R108).
        severity: Violation severity (error, warning, info).
        message: Human-readable violation description.
        file: File path where the violation occurred.
        line: Line number(s) of the violation.
        scope: Rule scope (task, play, role, etc.).
    """

    rule_id: str
    severity: str
    message: str
    file: str
    line: int | list[int] | None = None
    scope: str = "task"


@dataclass
class CheckReport:
    """Summary of validation checks.

    Attributes:
        violations: List of detected violations.
        rules_evaluated: Number of rules that were evaluated.
        nodes_scanned: Number of graph nodes scanned.
        elapsed_ms: Time spent scanning in milliseconds.
    """

    violations: list[CheckViolation] = field(default_factory=list)
    rules_evaluated: int = 0
    nodes_scanned: int = 0
    elapsed_ms: float = 0.0

    @property
    def has_violations(self) -> bool:
        """Return True if any violations were found."""
        return len(self.violations) > 0

    @property
    def error_count(self) -> int:
        """Count of error-level violations."""
        return sum(1 for v in self.violations if v.severity == "error")

    @property
    def warning_count(self) -> int:
        """Count of warning-level violations."""
        return sum(1 for v in self.violations if v.severity == "warning")

    def summary(self) -> str:
        """Return a human-readable summary."""
        if not self.violations:
            return f"No violations found ({self.nodes_scanned} nodes scanned)."
        return (
            f"Found {len(self.violations)} violation(s): "
            f"{self.error_count} error(s), {self.warning_count} warning(s)."
        )

    def to_markdown(self) -> str:
        """Return violations as markdown grouped by file path.

        Format:
            ## APME Check Results

            ### path/to/file.yml
            - L42: L021 (warning): Set mode explicitly for file/copy/template
            - L58: R108 (error): Privilege escalation detected

            ### path/to/other.yml
            - L10: L003 (warning): Each play should have a name
        """
        if not self.violations:
            return "## APME Check Results\n\nNo violations found."

        # Group violations by file
        by_file: dict[str, list[CheckViolation]] = {}
        for v in self.violations:
            file_path = self._relative_path(v.file)
            if file_path not in by_file:
                by_file[file_path] = []
            by_file[file_path].append(v)

        lines = ["## APME Check Results", ""]
        lines.append(f"Found {len(self.violations)} violation(s): "
                     f"{self.error_count} error(s), {self.warning_count} warning(s).")
        lines.append("")

        for file_path in sorted(by_file.keys()):
            lines.append(f"### {file_path}")
            file_violations = sorted(by_file[file_path], key=lambda v: self._sort_key(v))
            for v in file_violations:
                line_str = self._format_line(v.line)
                lines.append(f"- {line_str}: {v.rule_id} ({v.severity}): {v.message}")
            lines.append("")

        return "\n".join(lines).rstrip()

    @staticmethod
    def _relative_path(file_path: str) -> str:
        """Convert absolute path to relative path from cwd."""
        if not file_path:
            return "<unknown>"
        try:
            return str(Path(file_path).relative_to(Path.cwd()))
        except ValueError:
            return file_path

    @staticmethod
    def _format_line(line: int | list[int] | None) -> str:
        """Format line number(s) for display."""
        if line is None:
            return "L?"
        if isinstance(line, list):
            return f"L{line[0]}" if line else "L?"
        return f"L{line}"

    @staticmethod
    def _sort_key(v: CheckViolation) -> int:
        """Return sort key for ordering violations by line number."""
        if v.line is None:
            return 0
        if isinstance(v.line, list):
            return v.line[0] if v.line else 0
        return v.line



class APME:
    """APME integration for Ansible content validation and formatting.

    Provides native Python access to:
    - format(): YAML formatting with Ansible-specific normalization
    - check(): Graph-based rule evaluation for Ansible best practices
    - get_documentation_for_rule(): Rule documentation lookup

    Example:
        apme = APME()
        report = apme.format("/path/to/ansible/role")
        if report.files_changed:
            print(f"Reformatted {report.files_changed} files")

        check_report = apme.check("/path/to/ansible/role")
        for violation in check_report.violations:
            print(f"{violation.rule_id}: {violation.message}")
    """

    def __init__(self) -> None:
        """Initialize APME instance."""
        self._rules_dir = native_rules_dir()

    def format(
        self,
        path: str | Path,
        *,
        apply: bool = True,
        exclude_patterns: list[str] | None = None,
    ) -> FormatReport:
        """Format Ansible YAML files with APME's formatter.

        Applies Ansible-specific YAML normalization:
        - Task key ordering (name first, then action, then metadata)
        - Jinja2 spacing normalization ({{ var }} style)
        - Tab-to-space conversion
        - Task list blank line insertion
        - Name capitalization
        - Inline key=value expansion to YAML dict form

        Args:
            path: File or directory to format.
            apply: If True, write changes to disk. If False, dry-run only.
            exclude_patterns: Glob patterns to exclude (e.g., ["vendor/*"]).

        Returns:
            FormatReport with summary and per-file results.
        """
        path = Path(path).resolve()
        slog = logger.bind(path=str(path), apply=apply)

        if not path.exists():
            slog.warning("Path does not exist")
            return FormatReport()

        if path.is_file():
            results = [format_file(path)]
        else:
            results = format_directory(path, exclude_patterns=exclude_patterns)

        files_changed = 0
        for result in results:
            if result.changed:
                files_changed += 1
                if apply:
                    result.path.write_text(result.formatted, encoding="utf-8")
                    slog.debug("Formatted file", file=str(result.path))

        report = FormatReport(
            files_checked=len(results),
            files_changed=files_changed,
            results=results,
        )

        slog.info(report.summary())
        return report

    def check(
        self,
        path: str | Path,
        *,
        rule_ids: list[str] | None = None,
        exclude_rule_ids: list[str] | None = None,
        include_test_contents: bool = False,
    ) -> CheckReport:
        """Run APME validation checks on Ansible content.

        Uses the native graph-based scanner to evaluate rules against
        the Ansible project structure. This is the core validation engine
        that powers `apme check`.

        Args:
            path: File or directory to check.
            rule_ids: If provided, only run these specific rules.
            exclude_rule_ids: Rule IDs to skip.
            include_test_contents: Include test directories in the scan.

        Returns:
            CheckReport with violations and scan statistics.
        """
        path = Path(path).resolve()
        slog = logger.bind(path=str(path))

        if not path.exists():
            slog.warning("Path does not exist")
            return CheckReport()

        # Run the engine scanner to build the content graph
        slog.debug("Running APME scan")
        context = run_scan(
            target_path=str(path),
            project_root=str(path) if path.is_dir() else str(path.parent),
            include_scandata=True,
            include_test_contents=include_test_contents,
        )

        # Load and filter graph rules
        rules, _ = load_graph_rules(
            rules_dir=self._rules_dir,
            rule_id_list=rule_ids,
            exclude_rule_ids=exclude_rule_ids,
        )

        # Get the content graph from scandata
        scandata = context.scandata
        if scandata is None or not hasattr(scandata, "content_graph"):
            slog.warning("No content graph available from scan")
            return CheckReport()

        content_graph = scandata.content_graph
        if content_graph is None:
            slog.warning("Content graph is None")
            return CheckReport()

        # Run graph-based rule evaluation
        slog.debug("Running graph rule evaluation", rules_count=len(rules))
        graph_report: GraphScanReport = scan(content_graph, rules, owned_only=True)

        # Convert to violation dicts
        violation_dicts = graph_report_to_violations(graph_report)

        # Convert to our dataclass format
        violations = [
            CheckViolation(
                rule_id=str(v.get("rule_id", "")),
                severity=str(v.get("severity", "warning")),
                message=str(v.get("message", "")),
                file=str(v.get("file", "")),
                line=self._normalize_line(v.get("line")),
                scope=str(v.get("scope", "task")),
            )
            for v in violation_dicts
        ]

        report = CheckReport(
            violations=violations,
            rules_evaluated=graph_report.rules_evaluated,
            nodes_scanned=graph_report.nodes_scanned,
            elapsed_ms=graph_report.elapsed_ms,
        )

        slog.info(report.summary())
        return report

    @staticmethod
    def _normalize_line(line: object) -> int | list[int] | None:
        """Normalize line value to int, list[int], or None."""
        if line is None:
            return None
        if isinstance(line, int):
            return line
        if isinstance(line, list):
            return [int(x) for x in line if isinstance(x, int | float)]
        return None
