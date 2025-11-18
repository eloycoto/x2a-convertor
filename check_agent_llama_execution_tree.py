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


class CustomResourceExecution(ExecutionItem):
    """Custom resource with provider analysis"""

    type: str = "custom_resource"
    resource_type: str
    name: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    provider_path: str | None = None
    provider_analysis: dict[str, Any] | None = None


class RecipeChildNode(BaseModel):
    """Child recipe node in execution tree"""

    recipe_path: str
    recipe_name: str
    execution_order: list[Any] = Field(
        default_factory=list
    )  # Will be list[ExecutionItemType] after parsing
    circular_dependency_warning: str | None = None


class IncludeRecipeExecution(ExecutionItem):
    """Include recipe with child node"""

    type: str = "include_recipe"
    recipe_name: str
    child_node: RecipeChildNode | None = None
    note: str | None = None


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


class ChefPromptBuilder:
    """Builds LLM prompts for Chef recipe and provider analysis."""

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
        self.path_resolver = ChefPathResolver()
        self.visited_files = set()
        self.all_recipes = []
        self.circular_deps = []
        self.custom_resources_used = []

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

        return item.model_copy(
            update={
                "provider_path": provider_path,
                "provider_analysis": {
                    "templates": provider_data.get("unconditional_templates", []),
                    "conditionals": provider_data.get("conditionals", []),
                },
            }
        )

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

        # Extract cookbook name
        cookbook_name = Path(starting_recipe).parent.parent.name

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
            "all_recipes": self.all_recipes,
            "circular_dependencies": self.circular_deps,
            "custom_resources_used": self.custom_resources_used,
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
