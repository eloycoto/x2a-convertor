"""Chef execution domain models.

This module defines Pydantic models for representing Chef recipe execution flow.
These are pure data structures (no business logic) used for LLM structured outputs.
"""

from typing import Any

from pydantic import BaseModel, Field

# ============================================================================
# Execution Item Models
# ============================================================================


class ExecutionItem(BaseModel):
    """Base execution item with sequence number."""

    seq: int
    type: str


class AttributeAssignment(ExecutionItem):
    """Attribute assignment (node.default['key'] = value)."""

    type: str = "attribute_assignment"
    attribute_path: str
    value: Any


class ResourceExecution(ExecutionItem):
    """Standard Chef resource (package, service, directory, etc.)."""

    type: str = "resource"
    resource_type: str
    name: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None


class ConditionalExecution(ExecutionItem):
    """Conditional block (if/unless/case) with nested execution."""

    type: str = "conditional"
    condition: str
    execution_order: list[Any] = Field(default_factory=list)
    note: str | None = None


class CustomResourceExecution(ExecutionItem):
    """Custom resource (LWRP) with provider analysis."""

    type: str = "custom_resource"
    resource_type: str
    name: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    provider_path: str | None = None
    provider_analysis: dict[str, Any] | None = None


class RecipeChildNode(BaseModel):
    """Child recipe node (from include_recipe)."""

    recipe_path: str
    recipe_name: str
    execution_order: list[Any] = Field(default_factory=list)
    circular_dependency_warning: str | None = None


class IncludeRecipeExecution(ExecutionItem):
    """Include recipe statement with child node."""

    type: str = "include_recipe"
    recipe_name: str
    child_node: RecipeChildNode | None = None
    note: str | None = None


# ============================================================================
# LLM Structured Outputs
# ============================================================================


class RecipeExecutionAnalysis(BaseModel):
    """LLM output for recipe execution analysis."""

    execution_order: list[dict[str, Any]] = Field(
        default_factory=list, description="List of execution items in sequence order"
    )


class ProviderAnalysisOutput(BaseModel):
    """LLM output for provider analysis."""

    unconditional_templates: list[dict[str, Any]] = Field(
        default_factory=list, description="Templates created unconditionally"
    )
    conditionals: list[dict[str, Any]] = Field(
        default_factory=list, description="Conditional branches with templates"
    )


class DefaultAttributesOutput(BaseModel):
    """LLM output for default attributes extraction."""

    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted default attribute values as nested dict",
    )
    platform_specific_notes: list[str] = Field(
        default_factory=list, description="Notes about platform-specific attributes"
    )


# ============================================================================
# Analysis Result Models (for workflow)
# ============================================================================


class AnalyzedFile(BaseModel):
    """Base model for individual file analysis result."""

    file_path: str
    file_type: str  # "recipe" | "provider" | "attributes"


class RecipeAnalysisResult(AnalyzedFile):
    """Recipe file analysis with execution order."""

    file_type: str = "recipe"
    analysis: RecipeExecutionAnalysis


class ProviderAnalysisResult(AnalyzedFile):
    """Provider file analysis with templates and conditionals."""

    file_type: str = "provider"
    analysis: ProviderAnalysisOutput


class AttributesAnalysisResult(AnalyzedFile):
    """Attributes file analysis with default values."""

    file_type: str = "attributes"
    analysis: DefaultAttributesOutput


class StructuredAnalysis(BaseModel):
    """Aggregate of all structured analysis results from Chef cookbook.

    This model combines all analysis from recipes, providers, and attributes
    files into a single typed structure.
    """

    recipes: list[RecipeAnalysisResult] = Field(default_factory=list)
    providers: list[ProviderAnalysisResult] = Field(default_factory=list)
    attributes: list[AttributesAnalysisResult] = Field(default_factory=list)
    attribute_collections: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Map of collection attribute names to their item keys (for iteration expansion)",
    )

    def get_total_files_analyzed(self) -> int:
        """Get total number of files analyzed."""
        return len(self.recipes) + len(self.providers) + len(self.attributes)


# ============================================================================
# Aggregate Root
# ============================================================================


class ExecutionTree(BaseModel):
    """Complete execution tree (aggregate root in DDD)."""

    cookbook: str
    starting_recipe: str
    metadata: dict[str, Any]
    execution_tree: RecipeChildNode
    all_recipes: list[str]
    circular_dependencies: list[dict[str, str]]
    custom_resources_used: list[dict[str, str]]
    execution_flow_summary: dict[str, Any] | None = None
