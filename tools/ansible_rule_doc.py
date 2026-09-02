"""Rule documentation lookup tool backed by APME's rule catalog.

Gives LLM agents access to the same rule documentation and AI-remediation
guidance that ``apme check`` reports reference (rule IDs like ``R114``,
``L039``, ``M006``), without shelling out or re-implementing the catalog.
"""

from apme_engine.rule_catalog import (
    get_rule_documentation,
    get_rule_guidance,
    list_rules_with_guidance,
)
from langchain_core.tools.base import ArgsSchema
from pydantic import BaseModel, Field

from src.utils.logging import get_logger
from tools.base_tool import X2ATool

logger = get_logger(__name__)


class AnsibleRuleDocInput(BaseModel):
    """Input schema for the rule documentation lookup tool."""

    rule_id: str = Field(
        description=(
            "Rule identifier reported by ansible_role_check or apme check, "
            "e.g. 'R114', 'L039', 'M006'."
        )
    )


class AnsibleRuleDocTool(X2ATool):
    """Tool to look up documentation and remediation guidance for an APME rule.

    Use this after ``ansible_role_check`` reports a violation to understand
    why the rule exists, see pass/fail examples, and decide between fixing
    the code or adding a justified ``# noqa: RULE_ID`` comment.
    """

    name: str = "ansible_rule_doc"
    description: str = (
        "Looks up documentation for an APME rule ID (e.g. R114, L039, M006) "
        "reported by ansible_role_check or apme check. Returns the rule's "
        "full documentation (description, pass/fail examples) plus, when "
        "available, AI-remediation guidance describing concrete resolution "
        "options (fix the code, or justify a `# noqa: RULE_ID - reason` "
        "comment). Call this before adding a noqa comment to know what a "
        "valid justification looks like for that rule."
    )
    args_schema: ArgsSchema | None = AnsibleRuleDocInput

    # pyrefly: ignore
    def _run(self, rule_id: str) -> str:
        """Return documentation and guidance for the given rule ID."""
        self.log.debug(f"AnsibleRuleDocTool looking up {rule_id}")

        documentation = get_rule_documentation(rule_id)
        guidance = get_rule_guidance(rule_id)

        if documentation is None and guidance is None:
            available = ", ".join(list_rules_with_guidance())
            return (
                f"No documentation found for rule '{rule_id}'. "
                f"Rules with AI-remediation guidance: {available}"
            )

        sections = [f"# {rule_id}"]
        if documentation:
            sections.append(documentation)
        if guidance:
            sections.append(f"## Remediation guidance\n\n{guidance}")

        return "\n\n".join(sections)
