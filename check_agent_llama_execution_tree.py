#!/usr/bin/env python3
"""
Recipe Dependency Tracer - LLAMA Execution Tree Version

Produces execution-tree structure with sequence numbers like analysis.json.
Optimized for LLAMA using advanced prompt engineering techniques.
"""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src.model import get_model
from src.utils.logging import get_logger

logger = get_logger(__name__)


# Execution Tree Models
class ExecutionItem(BaseModel):
    """Base execution item with sequence number"""

    seq: int
    type: str


class AttributeAssignment(ExecutionItem):
    """Attribute assignment in execution order"""

    type: str = "attribute_assignment"
    attribute_path: str
    value: Any


class ResourceExecution(ExecutionItem):
    """Resource execution item"""

    type: str = "resource"
    resource_type: str
    name: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None


class ConditionalExecution(ExecutionItem):
    """Conditional block with nested execution"""

    type: str = "conditional"
    condition: str
    execution_order: list[Any] = Field(
        default_factory=list
    )  # Will be list[ExecutionItemType] after parsing
    note: str | None = None

    def execute_plan(self, context: "AttributeContext") -> "ConditionalExecution | None":
        """Recursively filter nested execution order.

        For now, keeps all conditionals (used + unknown).
        TODO: Could evaluate condition and return None if unused.

        Args:
            context: AttributeContext with loaded default attributes

        Returns:
            Filtered ConditionalExecution with filtered nested items, or None if unused
        """
        filtered_nested = []

        for nested_item in self.execution_order:
            # Parse to typed model if it's a dict
            if isinstance(nested_item, dict):
                typed_item = ExecutionItemParser.parse_execution_item(nested_item)
            else:
                typed_item = nested_item

            if isinstance(typed_item, ConditionalExecution):
                evaluated = typed_item.execute_plan(context)
                if evaluated:
                    filtered_nested.append(evaluated.model_dump() if isinstance(evaluated, BaseModel) else evaluated)

            elif isinstance(typed_item, CustomResourceExecution):
                evaluated = typed_item.execute_plan(context)
                filtered_nested.append(evaluated.model_dump() if isinstance(evaluated, BaseModel) else evaluated)

            elif isinstance(typed_item, IncludeRecipeExecution):
                evaluated = typed_item.execute_plan(context)
                filtered_nested.append(evaluated.model_dump() if isinstance(evaluated, BaseModel) else evaluated)

            else:
                # Pass through other items
                if isinstance(typed_item, BaseModel):
                    filtered_nested.append(typed_item.model_dump())
                else:
                    filtered_nested.append(nested_item)

        return self.model_copy(update={"execution_order": filtered_nested})


class CustomResourceExecution(ExecutionItem):
    """Custom resource with provider analysis"""

    type: str = "custom_resource"
    resource_type: str
    name: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    provider_path: str | None = None
    provider_analysis: dict[str, Any] | None = None

    def execute_plan(self, context: "AttributeContext") -> "CustomResourceExecution":
        """Filter provider analysis to show only templates that will be created.

        Args:
            context: AttributeContext with loaded default attributes

        Returns:
            New CustomResourceExecution with filtered provider_analysis
        """
        if not self.provider_analysis:
            return self

        # Filter provider analysis
        filtered_analysis = self._filter_provider_analysis(
            self.provider_analysis, context
        )

        return self.model_copy(update={"provider_analysis": filtered_analysis})

    def _filter_provider_analysis(
        self, analysis: dict[str, Any], context: "AttributeContext"
    ) -> dict[str, Any]:
        """Filter provider conditionals to remove unused branches.

        Args:
            analysis: Provider analysis dict
            context: AttributeContext (unused for now, but kept for future)

        Returns:
            Filtered analysis dict with only used/unknown conditionals
        """
        conditionals = analysis.get("conditionals", [])
        filtered_conditionals = []

        for conditional in conditionals:
            usage_status = conditional.get("usage_status", "unknown")
            # Keep 'used' and 'unknown', remove 'unused'
            if usage_status != "unused":
                filtered_conditionals.append(conditional)

        return {
            "templates": analysis.get("templates", []),
            "conditionals": filtered_conditionals,
        }


class RecipeChildNode(BaseModel):
    """Child recipe node in execution tree"""

    recipe_path: str
    recipe_name: str
    execution_order: list[Any] = Field(
        default_factory=list
    )  # Will be list[ExecutionItemType] after parsing
    circular_dependency_warning: str | None = None

    def execute_plan(self, context: "AttributeContext") -> "RecipeChildNode":
        """Filter execution order in child node.

        Args:
            context: AttributeContext with loaded default attributes

        Returns:
            New RecipeChildNode with filtered execution_order
        """
        # Use RecipeExecutionAnalysis to filter
        analysis = RecipeExecutionAnalysis(execution_order=self.execution_order)
        filtered_analysis = analysis.execute_plan(context)

        return self.model_copy(update={"execution_order": filtered_analysis.execution_order})


class IncludeRecipeExecution(ExecutionItem):
    """Include recipe with child node"""

    type: str = "include_recipe"
    recipe_name: str
    child_node: RecipeChildNode | None = None
    note: str | None = None

    def execute_plan(self, context: "AttributeContext") -> "IncludeRecipeExecution":
        """Filter child node execution order.

        Args:
            context: AttributeContext with loaded default attributes

        Returns:
            New IncludeRecipeExecution with filtered child_node
        """
        if not self.child_node:
            return self

        # Filter child node recursively
        filtered_child = self.child_node.execute_plan(context)

        return self.model_copy(update={"child_node": filtered_child})


class ExecutionTree(BaseModel):
    """Complete execution tree structure"""

    cookbook: str
    starting_recipe: str
    metadata: dict[str, Any]
    execution_tree: RecipeChildNode
    all_recipes: list[str]
    circular_dependencies: list[dict[str, str]]
    custom_resources_used: list[dict[str, str]]


class RecipeExecutionAnalysis(BaseModel):
    """Structured output for recipe execution analysis"""

    execution_order: list[dict[str, Any]] = Field(
        default_factory=list, description="List of execution items in sequence order"
    )

    def execute_plan(self, context: "AttributeContext") -> "RecipeExecutionAnalysis":
        """Filter execution order to only items that will execute based on context.

        Args:
            context: AttributeContext with loaded default attributes

        Returns:
            New RecipeExecutionAnalysis with filtered execution_order
        """
        filtered_order = []

        for item in self.execution_order:
            # Parse dict to typed model
            typed_item = ExecutionItemParser.parse_execution_item(item)

            if isinstance(typed_item, ConditionalExecution):
                # Evaluate and filter conditional
                evaluated = typed_item.execute_plan(context)
                if evaluated:  # None if unused
                    filtered_order.append(evaluated.model_dump())

            elif isinstance(typed_item, CustomResourceExecution):
                # Filter provider analysis
                evaluated = typed_item.execute_plan(context)
                filtered_order.append(evaluated.model_dump())

            elif isinstance(typed_item, IncludeRecipeExecution):
                # Filter child node recursively
                evaluated = typed_item.execute_plan(context)
                filtered_order.append(evaluated.model_dump())

            else:
                # Pass through other items (AttributeAssignment, ResourceExecution)
                if isinstance(typed_item, BaseModel):
                    filtered_order.append(typed_item.model_dump())
                else:
                    filtered_order.append(item)

        return RecipeExecutionAnalysis(execution_order=filtered_order)


ExecutionItemType = (
    AttributeAssignment
    | ResourceExecution
    | ConditionalExecution
    | CustomResourceExecution
    | IncludeRecipeExecution
    | dict[str, Any]
)


class ProviderAnalysisOutput(BaseModel):
    """Structured output for provider analysis"""

    unconditional_templates: list[dict[str, Any]] = Field(
        default_factory=list, description="Templates created unconditionally"
    )
    conditionals: list[dict[str, Any]] = Field(
        default_factory=list, description="Conditional branches with templates"
    )

    def execute_plan(self, context: "AttributeContext") -> "ProviderAnalysisOutput":
        """Filter conditionals to remove unused branches.

        Args:
            context: AttributeContext (unused for now, but kept for future)

        Returns:
            New ProviderAnalysisOutput with only used/unknown conditionals
        """
        filtered_conditionals = []

        for conditional in self.conditionals:
            # Keep only used/unknown branches
            usage_status = conditional.get("usage_status", "unknown")
            if usage_status != "unused":
                filtered_conditionals.append(conditional)

        return ProviderAnalysisOutput(
            unconditional_templates=self.unconditional_templates,
            conditionals=filtered_conditionals,
        )


class RecipeName:
    """Value object representing a Chef recipe name."""

    def __init__(self, full_name: str):
        self._full_name = full_name
        self._cookbook, self._recipe = self._parse(full_name)

    @staticmethod
    def _parse(full_name: str) -> tuple[str, str]:
        """Parse recipe name into cookbook and recipe parts."""
        if "::" in full_name:
            parts = full_name.split("::", 1)
            return (parts[0], parts[1])
        return (full_name, "default")

    @property
    def full_name(self) -> str:
        """Get the full recipe name."""
        return self._full_name

    @property
    def cookbook(self) -> str:
        """Get the cookbook name."""
        return self._cookbook

    @property
    def recipe(self) -> str:
        """Get the recipe name."""
        return self._recipe

    @property
    def file_name(self) -> str:
        """Get the expected file name."""
        return f"{self._recipe}.rb"

    def __str__(self) -> str:
        return self._full_name

    def __repr__(self) -> str:
        return f"RecipeName('{self._full_name}')"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RecipeName):
            return False
        return self._full_name == other._full_name

    def __hash__(self) -> int:
        return hash(self._full_name)


class CookbookName:
    """Value object representing a Chef cookbook name."""

    def __init__(self, name: str):
        self._name = name

    @property
    def name(self) -> str:
        """Get the cookbook name."""
        return self._name

    def matches_directory(self, directory_name: str) -> bool:
        """Check if directory name matches this cookbook."""
        return self._name in directory_name or directory_name.startswith(
            f"{self._name}-"
        )

    def __str__(self) -> str:
        return self._name

    def __repr__(self) -> str:
        return f"CookbookName('{self._name}')"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CookbookName):
            return False
        return self._name == other._name

    def __hash__(self) -> int:
        return hash(self._name)


class ResourceTypeName:
    """Value object representing a custom resource type name."""

    def __init__(self, resource_type: str):
        self._resource_type = resource_type
        self._parts = resource_type.split("_")

    @property
    def full_name(self) -> str:
        """Get the full resource type name."""
        return self._resource_type

    @property
    def parts(self) -> list[str]:
        """Get the parts of the resource type name."""
        return self._parts

    def is_valid(self) -> bool:
        """Check if this is a valid custom resource type name."""
        return len(self._parts) >= 2

    def get_cookbook_provider_combinations(self) -> list[tuple[str, str]]:
        """Get all possible cookbook/provider combinations."""
        if not self.is_valid():
            return []

        combinations = []
        for i in range(1, len(self._parts)):
            cookbook = "_".join(self._parts[:i])
            provider = "_".join(self._parts[i:])
            combinations.append((cookbook, provider))

        return combinations

    def __str__(self) -> str:
        return self._resource_type

    def __repr__(self) -> str:
        return f"ResourceTypeName('{self._resource_type}')"


class AttributeContext:
    """Tracks node attribute values throughout execution."""

    def __init__(self):
        self._attributes: dict[str, Any] = {}

    def set_attribute(self, attribute_path: str, value: Any) -> None:
        """Set an attribute value from path like node.default['redis']['port']."""
        # Extract the path parts
        path = self._parse_attribute_path(attribute_path)
        if path:
            self._set_nested(path, value)

    def _parse_attribute_path(self, attribute_path: str) -> list[str] | None:
        """Parse attribute path into list of keys."""
        import re

        # Remove node.default, node.override, etc
        cleaned = re.sub(r"^node\.(default|override|normal|automatic)\s*", "", attribute_path)

        # Extract keys from ['key1']['key2'] format
        keys = re.findall(r"\['([^']+)'\]", cleaned)

        return keys if keys else None

    def _set_nested(self, path: list[str], value: Any) -> None:
        """Set value in nested dict structure."""
        current = self._attributes
        for key in path[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]

        current[path[-1]] = value

    def get_attribute(self, path: list[str]) -> Any | None:
        """Get attribute value from path."""
        current = self._attributes
        for key in path:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        return current

    def get_all_attributes(self) -> dict[str, Any]:
        """Get all tracked attributes."""
        return self._attributes.copy()

    def copy(self) -> "AttributeContext":
        """Create a copy of this context."""
        new_context = AttributeContext()
        new_context._attributes = self._attributes.copy()
        return new_context

    def __repr__(self) -> str:
        return f"AttributeContext({self._attributes})"


class ConditionalEvaluator:
    """Evaluates Chef conditionals against attribute context."""

    @staticmethod
    def evaluate_condition(
        condition: str, condition_type: str, when_value: str | None, context: AttributeContext
    ) -> bool | None:
        """
        Evaluate if a conditional matches the current context.
        Returns True if matches, False if doesn't match, None if can't determine.
        """
        if condition_type == "case":
            # For case/when, extract the attribute being checked
            attribute_path = ConditionalEvaluator._extract_case_attribute(condition)
            if not attribute_path:
                return None

            actual_value = context.get_attribute(attribute_path)
            if actual_value is None:
                return None

            # Check if actual value matches when_value
            return str(actual_value) == when_value

        # For if/unless, we'd need more complex parsing
        # For now, return None (can't determine)
        return None

    @staticmethod
    def _extract_case_attribute(condition: str) -> list[str] | None:
        """Extract attribute path from case condition."""
        import re

        # Pattern: node['key1']['key2'] or node['key1']['key2']['key3']
        keys = re.findall(r"\['([^']+)'\]", condition)
        return keys if keys else None


class ExecutionItemParser:
    """Parses dict representations into typed domain models."""

    @staticmethod
    def parse_execution_item(item: dict[str, Any]) -> ExecutionItemType:
        """Parse a dict into the appropriate ExecutionItem subtype."""
        item_type = item.get("type")

        if item_type == "attribute_assignment":
            return AttributeAssignment(**item)

        if item_type == "resource":
            return ResourceExecution(**item)

        if item_type == "conditional":
            # Recursively parse nested execution order
            nested_items = item.get("execution_order", [])
            parsed_nested = [
                ExecutionItemParser.parse_execution_item(nested)
                for nested in nested_items
            ]
            return ConditionalExecution(
                seq=item["seq"],
                condition=item["condition"],
                execution_order=parsed_nested,
                note=item.get("note"),
            )

        if item_type == "custom_resource":
            return CustomResourceExecution(**item)

        if item_type == "include_recipe":
            return IncludeRecipeExecution(**item)

        # Fallback to raw dict if type is unknown
        return item

    @staticmethod
    def parse_execution_order(
        items: list[dict[str, Any]],
    ) -> list[ExecutionItemType]:
        """Parse a list of dict items into typed models."""
        return [ExecutionItemParser.parse_execution_item(item) for item in items]


class DefaultAttributesOutput(BaseModel):
    """Structured output for default attributes extraction"""

    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted default attribute values as nested dict"
    )
    platform_specific_notes: list[str] = Field(
        default_factory=list,
        description="Notes about platform-specific attributes"
    )


class ChefPromptBuilder:
    """Builds LLM prompts for Chef recipe and provider analysis."""

    @staticmethod
    def build_attributes_extraction_prompt(file_path: str, file_content: str) -> str:
        """Build prompt for extracting default attributes."""
        return f"""You are extracting DEFAULT attribute values from a Chef attributes file.

FILE PATH: {file_path}

FILE CONTENT:
```ruby
{file_content}
```

TASK:
Extract all `default['...']['...']` assignments and return them as a nested dictionary.

RULES:
1. For simple assignments like `default['redis']['port'] = 6379`, extract as {{"redis": {{"port": 6379}}}}
2. For platform-specific conditionals (case/when), extract the MOST COMMON default value:
   - If `systemd?` is used, assume systemd is available (true)
   - If `platform_family?('debian')`, use the debian value as default
   - If rhel/fedora, use rhel value
3. Skip helper variables (like `shell = '/bin/sh'`) unless they're assigned to default[]
4. For complex values (arrays, hashes), preserve the structure
5. Add notes about platform-specific logic in platform_specific_notes

EXAMPLE:

Input:
```ruby
default['redis']['port'] = 6379
default['redis']['host'] = 'localhost'

default['redis']['job_control'] = if systemd?
                                    'systemd'
                                  else
                                    'initd'
                                  end
```

Output:
```json
{{
  "attributes": {{
    "redis": {{
      "port": 6379,
      "host": "localhost",
      "job_control": "systemd"
    }}
  }},
  "platform_specific_notes": [
    "job_control defaults to 'systemd' if systemd? is true, otherwise 'initd'"
  ]
}}
```

Now extract the attributes from the file above and return JSON.
"""

    @staticmethod
    def build_recipe_analysis_prompt(file_path: str, file_content: str) -> str:
        """Build prompt for recipe execution order analysis."""
        return f"""You are a Chef recipe analyzer. Your task is to extract the EXECUTION ORDER of operations from a Chef recipe file.

CHAIN OF THOUGHT PROCESS:
Step 1: Read through the file and identify all operations
Step 2: Assign sequence numbers based on top-to-bottom execution order
Step 3: Classify each operation by type
Step 4: Extract attributes and parameters for each operation
Step 5: Build nested structures for conditionals and includes
Step 6: Return valid JSON

FILE PATH: {file_path}

FILE CONTENT:
```ruby
{file_content}
```

OPERATION TYPES:
1. include_recipe: Include another recipe
2. attribute_assignment: Set node attributes (node.default['key'] = value)
3. resource: Standard Chef resource (directory, package, service, etc.)
4. custom_resource: LWRP/custom resource invocation
5. conditional: if/unless/case blocks with nested execution_order

FEW-SHOT EXAMPLES:

Example 1 - Simple recipe:
```ruby
include_recipe 'cookbook_a'
node.default['app']['port'] = 8080
directory '/var/app' do
  owner 'root'
end
```

Expected JSON:
```json
{{
  "execution_order": [
    {{
      "seq": 1,
      "type": "include_recipe",
      "recipe_name": "cookbook_a"
    }},
    {{
      "seq": 2,
      "type": "attribute_assignment",
      "attribute_path": "node.default['app']['port']",
      "value": 8080
    }},
    {{
      "seq": 3,
      "type": "resource",
      "resource_type": "directory",
      "name": "/var/app",
      "attributes": {{"owner": "root"}}
    }}
  ]
}}
```

Example 2 - With conditional:
```ruby
unless node['app']['skip_install']
  include_recipe 'app::install'
  package 'nginx'
end
```

Expected JSON:
```json
{{
  "execution_order": [
    {{
      "seq": 1,
      "type": "conditional",
      "condition": "unless node['app']['skip_install']",
      "execution_order": [
        {{
          "seq": 1,
          "type": "include_recipe",
          "recipe_name": "app::install"
        }},
        {{
          "seq": 2,
          "type": "resource",
          "resource_type": "package",
          "name": "nginx",
          "attributes": {{}}
        }}
      ]
    }}
  ]
}}
```

Example 3 - Custom resource:
```ruby
my_custom_resource 'instance1' do
  port 8080
  user 'appuser'
  action [:start, :enable]
end
```

Expected JSON:
```json
{{
  "execution_order": [
    {{
      "seq": 1,
      "type": "custom_resource",
      "resource_type": "my_custom_resource",
      "name": "instance1",
      "attributes": {{
        "port": "8080",
        "user": "appuser",
        "action": ["start", "enable"]
      }}
    }}
  ]
}}
```

CRITICAL REQUIREMENTS:
- Sequence numbers start at 1 and increment
- Preserve Ruby interpolations like "#{{var}}" as-is
- Conditionals have their own nested execution_order
- Each operation must have a "type" field
- Return ONLY valid JSON, no explanations

Now analyze the file above and return the execution_order JSON:
```json
{{
  "execution_order": [

  ]
}}
```"""

    @staticmethod
    def build_provider_analysis_prompt(file_path: str, file_content: str) -> str:
        """Build prompt for provider template/resource analysis."""
        return f"""You are a Chef provider analyzer. Extract what this provider CREATES when invoked.

CHAIN OF THOUGHT:
Step 1: Identify unconditional templates (outside case/when blocks)
Step 2: Identify case/when blocks and templates inside each branch
Step 3: Extract files and resources created
Step 4: Assign when_value to each case branch
Step 5: Return JSON with templates categorized correctly

FILE PATH: {file_path}

FILE CONTENT:
```ruby
{file_content}
```

FEW-SHOT EXAMPLE:

Provider with case/when:
```ruby
template "/etc/app/config.conf" do
  source 'config.erb'
end

case node['app']['init']
when 'systemd'
  template "/lib/systemd/system/app.service" do
    source 'app.service.erb'
  end
when 'initd'
  template "/etc/init.d/app" do
    source 'app.init.erb'
  end
end
```

Expected JSON:
```json
{{
  "unconditional_templates": [
    {{
      "destination": "/etc/app/config.conf",
      "source": "templates/default/config.erb"
    }}
  ],
  "conditionals": [
    {{
      "condition": "node['app']['init']",
      "condition_type": "case",
      "when_value": "systemd",
      "templates": [
        {{
          "destination": "/lib/systemd/system/app.service",
          "source": "templates/default/app.service.erb"
        }}
      ]
    }},
    {{
      "condition": "node['app']['init']",
      "condition_type": "case",
      "when_value": "initd",
      "templates": [
        {{
          "destination": "/etc/init.d/app",
          "source": "templates/default/app.init.erb"
        }}
      ]
    }}
  ]
}}
```

REQUIREMENTS:
- Templates OUTSIDE case/when go in unconditional_templates
- Each when branch creates ONE conditional object
- when_value must be the actual value ("systemd", "initd", etc.), NOT null
- Prefix template sources with "templates/default/"
- Return ONLY valid JSON

Analyze the provider and return JSON:
```json
{{
  "unconditional_templates": [],
  "conditionals": []
}}
```"""


class ChefPathResolver:
    """Resolves Chef recipe and provider paths using domain value objects."""

    @staticmethod
    def resolve_recipe_path(
        recipe_name: RecipeName, dependency_paths: list[str]
    ) -> str | None:
        """Resolve recipe name to full file path."""
        cookbook_name = CookbookName(recipe_name.cookbook)

        for dep_path in dependency_paths:
            dep_dir = Path(dep_path)
            recipe_path = ChefPathResolver._find_recipe_in_directory(
                dep_dir, cookbook_name, recipe_name
            )
            if recipe_path:
                return str(recipe_path)

        return None

    @staticmethod
    def _find_recipe_in_directory(
        dep_dir: Path, cookbook: CookbookName, recipe: RecipeName
    ) -> Path | None:
        """Find recipe file in a directory."""
        if not dep_dir.is_dir():
            return None

        # Check if dep_path itself is a cookbook
        if (dep_dir / "recipes").exists() and cookbook.matches_directory(dep_dir.name):
            recipe_path = dep_dir / "recipes" / recipe.file_name
            if recipe_path.exists():
                return recipe_path

        # Check subdirectories
        for cookbook_dir in dep_dir.iterdir():
            if not cookbook_dir.is_dir():
                continue

            if cookbook.matches_directory(cookbook_dir.name):
                recipe_path = cookbook_dir / "recipes" / recipe.file_name
                if recipe_path.exists():
                    return recipe_path

        return None

    @staticmethod
    def resolve_provider_path(
        resource_type: ResourceTypeName, dependency_paths: list[str]
    ) -> str | None:
        """Resolve custom resource type to provider file path."""
        if not resource_type.is_valid():
            return None

        for (
            cookbook_name,
            provider_name,
        ) in resource_type.get_cookbook_provider_combinations():
            cookbook = CookbookName(cookbook_name)

            for dep_path in dependency_paths:
                dep_dir = Path(dep_path)
                provider_path = ChefPathResolver._find_provider_in_directory(
                    dep_dir, cookbook, provider_name
                )
                if provider_path:
                    return str(provider_path)

        return None

    @staticmethod
    def _find_provider_in_directory(
        dep_dir: Path, cookbook: CookbookName, provider_name: str
    ) -> Path | None:
        """Find provider file in a directory."""
        if not dep_dir.is_dir():
            return None

        # Check if dep_path itself is a cookbook
        if (dep_dir / "providers").exists() and cookbook.matches_directory(
            dep_dir.name
        ):
            provider_path = dep_dir / "providers" / f"{provider_name}.rb"
            if provider_path.exists():
                return provider_path

        # Check subdirectories
        for cookbook_dir in dep_dir.iterdir():
            if not cookbook_dir.is_dir():
                continue

            if cookbook.matches_directory(cookbook_dir.name):
                provider_path = cookbook_dir / "providers" / f"{provider_name}.rb"
                if provider_path.exists():
                    return provider_path

        return None

    @staticmethod
    def resolve_attributes_path(
        cookbook_name: CookbookName, dependency_paths: list[str]
    ) -> str | None:
        """Resolve cookbook name to attributes/default.rb file path."""
        for dep_path in dependency_paths:
            dep_dir = Path(dep_path)
            attributes_path = ChefPathResolver._find_attributes_in_directory(
                dep_dir, cookbook_name
            )
            if attributes_path:
                return str(attributes_path)

        return None

    @staticmethod
    def _find_attributes_in_directory(
        dep_dir: Path, cookbook: CookbookName
    ) -> Path | None:
        """Find attributes/default.rb file in a directory."""
        if not dep_dir.is_dir():
            return None

        # Check if dep_path itself is a cookbook
        if (dep_dir / "attributes").exists() and cookbook.matches_directory(
            dep_dir.name
        ):
            attributes_path = dep_dir / "attributes" / "default.rb"
            if attributes_path.exists():
                return attributes_path

        # Check subdirectories
        for cookbook_dir in dep_dir.iterdir():
            if not cookbook_dir.is_dir():
                continue

            if cookbook.matches_directory(cookbook_dir.name):
                attributes_path = cookbook_dir / "attributes" / "default.rb"
                if attributes_path.exists():
                    return attributes_path

        return None


class AttributeFileAnalyzer:
    """Analyzes Chef attributes files to extract default values."""

    def __init__(self, model):
        self.model = model
        self.prompt_builder = ChefPromptBuilder()

    def analyze(self, file_path: str) -> dict[str, Any]:
        """Analyze attributes file and extract default values."""
        path_obj = Path(file_path)
        if not path_obj.exists():
            logger.warning(f"Attributes file not found: {file_path}")
            return {}

        file_content = path_obj.read_text()
        prompt = self.prompt_builder.build_attributes_extraction_prompt(
            file_path, file_content
        )

        try:
            structured_model = self.model.with_structured_output(DefaultAttributesOutput)
            result = structured_model.invoke(prompt)

            if result.platform_specific_notes:
                logger.info(f"Platform-specific attributes found:")
                for note in result.platform_specific_notes:
                    logger.info(f"  - {note}")

            logger.info(f"✓ Extracted {len(result.attributes)} top-level default attributes")
            return result.attributes
        except Exception as e:
            logger.error(f"Failed to analyze attributes {file_path}: {e}")
            return {}


class RecipeAnalyzer:
    """Analyzes Chef recipes using LLM with structured output."""

    def __init__(self, model):
        self.model = model
        self.prompt_builder = ChefPromptBuilder()

    def analyze(self, file_path: str) -> dict:
        """Analyze recipe and extract execution order."""
        path_obj = Path(file_path)
        if not path_obj.exists():
            logger.warning(f"File not found: {file_path}")
            return {"execution_order": []}

        file_content = path_obj.read_text()
        prompt = self.prompt_builder.build_recipe_analysis_prompt(
            file_path, file_content
        )

        try:
            structured_model = self.model.with_structured_output(
                RecipeExecutionAnalysis
            )
            result = structured_model.invoke(prompt)
            logger.info(f"✓ Extracted {len(result.execution_order)} execution items")
            return result.model_dump()
        except Exception as e:
            logger.error(f"Failed to analyze {file_path}: {e}")
            return {"execution_order": []}


class ProviderAnalyzer:
    """Analyzes Chef providers using LLM with structured output."""

    def __init__(self, model):
        self.model = model
        self.prompt_builder = ChefPromptBuilder()

    def analyze(self, file_path: str) -> dict:
        """Analyze provider and extract templates/resources created."""
        path_obj = Path(file_path)
        if not path_obj.exists():
            logger.warning(f"Provider not found: {file_path}")
            return {"unconditional_templates": [], "conditionals": []}

        file_content = path_obj.read_text()
        prompt = self.prompt_builder.build_provider_analysis_prompt(
            file_path, file_content
        )

        try:
            structured_model = self.model.with_structured_output(ProviderAnalysisOutput)
            result = structured_model.invoke(prompt)
            logger.info(
                f"✓ Provider has {len(result.unconditional_templates)} unconditional templates, {len(result.conditionals)} conditional branches"
            )
            return result.model_dump()
        except Exception as e:
            logger.error(f"Failed to analyze provider {file_path}: {e}")
            return {"unconditional_templates": [], "conditionals": []}


class RecipeDependencyTracerLLAMAExecutionTree:
    """LLAMA-optimized tracer producing execution-tree structure."""

    def __init__(self, model=None):
        self.model = model or get_model()
        self.recipe_analyzer = RecipeAnalyzer(self.model)
        self.provider_analyzer = ProviderAnalyzer(self.model)
        self.attribute_analyzer = AttributeFileAnalyzer(self.model)
        self.path_resolver = ChefPathResolver()
        self.visited_files = set()
        self.all_recipes = []
        self.circular_deps = []
        self.custom_resources_used = []
        self.attribute_context = AttributeContext()
        self.used_templates = []  # Track templates that will actually be created
        self.conditional_templates = []  # Track templates that might be created
        self.dependency_cookbooks_loaded = set()  # Track which cookbooks have defaults loaded
        self.dependency_paths = []  # Store dependency paths for lazy loading

    def analyze_recipe_execution(self, file_path: str) -> list[ExecutionItemType]:
        """Analyze recipe and extract execution order as typed models."""
        if file_path in self.visited_files:
            logger.info(f"Already analyzed: {file_path}")
            return []

        logger.info(f"Analyzing recipe: {file_path}")
        self.visited_files.add(file_path)
        self.all_recipes.append(file_path)

        analysis_dict = self.recipe_analyzer.analyze(file_path)
        execution_order_dicts = analysis_dict.get("execution_order", [])

        # Parse dicts into typed models
        return ExecutionItemParser.parse_execution_order(execution_order_dicts)

    def analyze_provider(self, file_path: str) -> dict:
        """Analyze provider and extract templates/resources created."""
        logger.info(f"Analyzing provider: {file_path}")
        return self.provider_analyzer.analyze(file_path)

    def load_cookbook_defaults(
        self, cookbook_name: str, dependency_paths: list[str]
    ) -> None:
        """Load default attributes from cookbook's attributes/default.rb file."""
        logger.info(f"Loading default attributes for cookbook: {cookbook_name}")

        cookbook = CookbookName(cookbook_name)
        attributes_path = self.path_resolver.resolve_attributes_path(
            cookbook, dependency_paths
        )

        if not attributes_path:
            logger.info(f"No attributes/default.rb found for {cookbook_name}")
            return

        # Analyze the attributes file
        defaults = self.attribute_analyzer.analyze(attributes_path)

        # Merge defaults into attribute context
        # The defaults are returned as a nested dict structure
        for key, value in defaults.items():
            # Build attribute path like node.default['key']
            self._merge_default_attributes(key, value)

        logger.info(
            f"✓ Loaded {len(defaults)} top-level default attributes for {cookbook_name}"
        )

    def _merge_default_attributes(
        self, key: str, value: Any, prefix: str = ""
    ) -> None:
        """Recursively merge default attributes into context."""
        current_path = f"{prefix}['{key}']" if prefix else f"node.default['{key}']"

        if isinstance(value, dict):
            # Set the dict itself first
            self.attribute_context.set_attribute(current_path, value)
            # Then recursively set nested values
            for nested_key, nested_value in value.items():
                self._merge_default_attributes(
                    nested_key, nested_value, current_path
                )
        else:
            # Leaf value - set it directly
            self.attribute_context.set_attribute(current_path, value)
            logger.debug(f"Set default: {current_path} = {value}")

    def process_execution_order(
        self, execution_order: list[ExecutionItemType], dependency_paths: list[str]
    ) -> list[ExecutionItemType]:
        """Process execution order, expanding includes and custom resources."""
        return [
            self._process_execution_item(item, dependency_paths)
            for item in execution_order
        ]

    def _process_execution_item(
        self, item: ExecutionItemType, dependency_paths: list[str]
    ) -> ExecutionItemType:
        """Process a single execution item based on its type."""
        if isinstance(item, AttributeAssignment):
            # Track attribute assignments in context
            self.attribute_context.set_attribute(item.attribute_path, item.value)
            logger.debug(f"Tracked attribute: {item.attribute_path} = {item.value}")
            return item

        if isinstance(item, IncludeRecipeExecution):
            return self._process_include_recipe(item, dependency_paths)

        if isinstance(item, CustomResourceExecution):
            return self._process_custom_resource(item, dependency_paths)

        if isinstance(item, ConditionalExecution):
            return self._process_conditional(item, dependency_paths)

        return item

    def _process_include_recipe(
        self, item: IncludeRecipeExecution, dependency_paths: list[str]
    ) -> IncludeRecipeExecution:
        """Process include_recipe item."""
        if not item.recipe_name:
            return item

        recipe_name = RecipeName(item.recipe_name)

        # Load default attributes for this cookbook if not already loaded
        cookbook_name_str = recipe_name.cookbook
        if cookbook_name_str not in self.dependency_cookbooks_loaded:
            logger.info(
                f"Loading defaults for dependency cookbook: {cookbook_name_str}"
            )
            self.load_cookbook_defaults(cookbook_name_str, self.dependency_paths)
            self.dependency_cookbooks_loaded.add(cookbook_name_str)

        recipe_path = self.path_resolver.resolve_recipe_path(
            recipe_name, dependency_paths
        )

        if not recipe_path:
            return item

        if recipe_path in self.visited_files:
            logger.warning(f"Circular dependency: {item.recipe_name}")
            self.circular_deps.append(
                {"recipe": item.recipe_name, "warning": "Circular reference detected"}
            )
            return item.model_copy(
                update={
                    "note": "CIRCULAR DEPENDENCY - already loaded",
                    "child_node": None,
                }
            )

        child_analysis = self.analyze_recipe_execution(recipe_path)
        child_exec_order = self.process_execution_order(
            child_analysis, dependency_paths
        )

        child_node = RecipeChildNode(
            recipe_path=recipe_path,
            recipe_name=item.recipe_name,
            execution_order=child_exec_order,
        )

        return item.model_copy(update={"child_node": child_node})

    def _process_custom_resource(
        self, item: CustomResourceExecution, dependency_paths: list[str]
    ) -> CustomResourceExecution:
        """Process custom_resource item."""
        if not item.resource_type:
            return item

        resource_type = ResourceTypeName(item.resource_type)
        provider_path = self.path_resolver.resolve_provider_path(
            resource_type, dependency_paths
        )

        if not provider_path:
            return item

        provider_data = self.analyze_provider(provider_path)
        self.custom_resources_used.append(
            {"type": item.resource_type, "provider_path": provider_path}
        )

        # Evaluate conditionals against attribute context
        evaluated_analysis = self._evaluate_provider_conditionals(
            provider_data, item.resource_type
        )

        return item.model_copy(
            update={
                "provider_path": provider_path,
                "provider_analysis": evaluated_analysis,
            }
        )

    def _evaluate_provider_conditionals(
        self, provider_data: dict, resource_type: str
    ) -> dict:
        """Evaluate provider conditionals against attribute context."""
        unconditional = provider_data.get("unconditional_templates", [])
        conditionals = provider_data.get("conditionals", [])

        # Track unconditional templates (these are always used)
        for template in unconditional:
            self.used_templates.append(
                {
                    "resource_type": resource_type,
                    "template": template,
                    "usage": "always",
                    "reason": "Unconditional in provider",
                }
            )

        # Evaluate each conditional branch
        evaluated_conditionals = []
        for conditional in conditionals:
            condition = conditional.get("condition", "")
            condition_type = conditional.get("condition_type", "")
            when_value = conditional.get("when_value")

            # Evaluate if this branch will execute
            will_execute = ConditionalEvaluator.evaluate_condition(
                condition, condition_type, when_value, self.attribute_context
            )

            # Mark usage status
            if will_execute is True:
                usage_status = "used"
                reason = f"Condition '{condition}' == '{when_value}' matches cookbook attributes"

                # Track these templates as actually used
                for template in conditional.get("templates", []):
                    self.used_templates.append(
                        {
                            "resource_type": resource_type,
                            "template": template,
                            "usage": "conditional_match",
                            "reason": reason,
                            "condition": condition,
                            "when_value": when_value,
                        }
                    )

            elif will_execute is False:
                usage_status = "unused"
                reason = f"Condition '{condition}' != '{when_value}'"

            else:
                usage_status = "unknown"
                reason = f"Cannot determine value of '{condition}' (not set in cookbook)"

                # Track as conditional (might be used)
                for template in conditional.get("templates", []):
                    self.conditional_templates.append(
                        {
                            "resource_type": resource_type,
                            "template": template,
                            "condition": condition,
                            "when_value": when_value,
                            "reason": reason,
                        }
                    )

            # Add usage metadata to conditional
            conditional_with_usage = conditional.copy()
            conditional_with_usage["usage_status"] = usage_status
            conditional_with_usage["usage_reason"] = reason
            evaluated_conditionals.append(conditional_with_usage)

        return {
            "templates": unconditional,
            "conditionals": evaluated_conditionals,
        }

    def _process_conditional(
        self, item: ConditionalExecution, dependency_paths: list[str]
    ) -> ConditionalExecution:
        """Process conditional item with nested execution order."""
        processed_nested = self.process_execution_order(
            item.execution_order, dependency_paths
        )
        return item.model_copy(update={"execution_order": processed_nested})

    def trace_execution_tree(
        self, starting_recipe: str, dependency_paths: list[str]
    ) -> dict:
        """Trace complete execution tree."""
        logger.info(f"Starting execution tree trace from: {starting_recipe}")

        starting_dir = str(Path(starting_recipe).parent.parent.parent)
        all_paths = [starting_dir, *dependency_paths]

        # Store dependency paths for lazy loading
        self.dependency_paths = all_paths

        # Extract cookbook name
        cookbook_name = Path(starting_recipe).parent.parent.name

        # Load default attributes BEFORE analyzing recipes
        logger.info("=" * 80)
        logger.info("LOADING COOKBOOK DEFAULT ATTRIBUTES")
        logger.info("=" * 80)

        # Load defaults for the starting cookbook
        self.load_cookbook_defaults(cookbook_name, all_paths)
        self.dependency_cookbooks_loaded.add(cookbook_name)

        logger.info("=" * 80)
        logger.info("ANALYZING RECIPES")
        logger.info("=" * 80)

        # Analyze starting recipe (returns typed models)
        root_execution_order = self.analyze_recipe_execution(starting_recipe)

        # Process execution order recursively (still working with typed models)
        processed_execution_order = self.process_execution_order(
            root_execution_order, all_paths
        )

        # Convert typed models to dicts for JSON serialization
        execution_order_dicts = [
            (item.model_dump() if isinstance(item, BaseModel) else item)
            for item in processed_execution_order
        ]

        # Generate evaluated execution tree (filtered based on attribute context)
        logger.info("=" * 80)
        logger.info("GENERATING EVALUATED EXECUTION TREE")
        logger.info("=" * 80)

        execution_tree_analysis = RecipeExecutionAnalysis(
            execution_order=execution_order_dicts
        )
        evaluated_analysis = execution_tree_analysis.execute_plan(self.attribute_context)

        execution_order_evaluated = evaluated_analysis.execution_order

        logger.info(
            f"✓ Evaluated tree: {len(execution_order_dicts)} items -> {len(execution_order_evaluated)} items after filtering"
        )

        # Build execution flow summary
        execution_flow_summary = {
            "cookbook_attributes": self.attribute_context.get_all_attributes(),
            "templates_will_be_created": self.used_templates,
            "templates_might_be_created": self.conditional_templates,
            "summary": {
                "total_templates_confirmed": len(self.used_templates),
                "total_templates_conditional": len(self.conditional_templates),
            },
        }

        # Build execution tree
        execution_tree = {
            "cookbook": cookbook_name,
            "starting_recipe": starting_recipe,
            "metadata": {
                "generated_at": "2025-11-17",
                "total_recipes": len(self.all_recipes),
                "has_circular_dependencies": len(self.circular_deps) > 0,
            },
            "execution_tree": {
                "recipe_path": starting_recipe,
                "recipe_name": f"{cookbook_name}::default",
                "execution_order": execution_order_dicts,
            },
            "execution_tree_evaluated": {
                "recipe_path": starting_recipe,
                "recipe_name": f"{cookbook_name}::default",
                "execution_order": execution_order_evaluated,
            },
            "all_recipes": self.all_recipes,
            "circular_dependencies": self.circular_deps,
            "custom_resources_used": self.custom_resources_used,
            "execution_flow_summary": execution_flow_summary,
        }

        return execution_tree


def main():
    """Run the LLAMA execution tree tracer."""
    logger.info("Starting Recipe Dependency Tracer - LLAMA Execution Tree Version...")

    starting_recipe = "/home/eloy/dev/upstream/x2ansible/chef-examples/cookbooks/cache/recipes/default.rb"
    dependency_base = "/home/eloy/dev/upstream/x2ansible/chef-examples/migration-dependencies/cookbook_artifacts"

    if not Path(starting_recipe).exists():
        logger.error(f"Starting recipe not found: {starting_recipe}")
        return

    dependency_paths = []
    base_path = Path(dependency_base)
    if base_path.exists():
        dependency_paths = [str(p) for p in base_path.iterdir() if p.is_dir()]

    logger.info(f"Found {len(dependency_paths)} dependency cookbooks")

    tracer = RecipeDependencyTracerLLAMAExecutionTree()

    try:
        result = tracer.trace_execution_tree(starting_recipe, dependency_paths)

        print("\n" + "=" * 80)
        print("LLAMA EXECUTION TREE RESULTS")
        print("=" * 80)
        print(f"\nCookbook: {result['cookbook']}")
        print(f"Starting Recipe: {result['starting_recipe']}")
        print(f"Total Recipes: {result['metadata']['total_recipes']}")
        print(f"Circular Dependencies: {len(result['circular_dependencies'])}")
        print(f"Custom Resources: {len(result['custom_resources_used'])}")

        # Print execution flow summary
        flow_summary = result.get("execution_flow_summary", {})
        print("\n--- EXECUTION FLOW SUMMARY ---")
        print(
            f"Templates WILL be created: {flow_summary.get('summary', {}).get('total_templates_confirmed', 0)}"
        )
        print(
            f"Templates MIGHT be created: {flow_summary.get('summary', {}).get('total_templates_conditional', 0)}"
        )

        # Save to JSON
        output_file = Path("execution_tree_output.json")
        with output_file.open("w") as f:
            json.dump(result, f, indent=2)

        print(f"\n✓ Saved to: {output_file}")

    except Exception as e:
        logger.error(f"Trace failed: {e}", exc_info=True)
        print(f"✗ Error: {e}")


if __name__ == "__main__":
    main()
