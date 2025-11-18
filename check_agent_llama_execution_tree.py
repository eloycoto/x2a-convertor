#!/usr/bin/env python3
"""
Recipe Dependency Tracer - LLAMA Execution Tree Version

Produces execution-tree structure with sequence numbers like analysis.json.
Optimized for LLAMA using advanced prompt engineering techniques.
"""

import json
import re
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
    execution_order: list[Any] = Field(default_factory=list)
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
    execution_order: list[Any] = Field(default_factory=list)
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


class RecipeDependencyTracerLLAMAExecutionTree:
    """LLAMA-optimized tracer producing execution-tree structure."""

    def __init__(self, model=None):
        self.model = model or get_model()
        self.visited_files = set()
        self.all_recipes = []
        self.circular_deps = []
        self.custom_resources_used = []

    def extract_json_from_text(self, text: str) -> dict:
        """Extract JSON from LLAMA response."""
        # Try JSON code block first
        json_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try to find raw JSON
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                json_str = text

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
            logger.debug(f"Text was: {json_str[:500]}")
            return {}

    def create_analysis_prompt(self, file_path: str, file_content: str, is_recipe: bool = True) -> str:
        """Create LLAMA-optimized prompt with Chain-of-Thought and few-shot examples."""

        if is_recipe:
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
        else:
            # Provider analysis prompt
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

    def analyze_recipe_execution(self, file_path: str) -> dict:
        """Analyze recipe and extract execution order."""
        if file_path in self.visited_files:
            logger.info(f"Already analyzed: {file_path}")
            return {"execution_order": [], "cached": True}

        logger.info(f"Analyzing recipe: {file_path}")
        self.visited_files.add(file_path)
        self.all_recipes.append(file_path)

        path_obj = Path(file_path)
        if not path_obj.exists():
            logger.warning(f"File not found: {file_path}")
            return {"execution_order": []}

        file_content = path_obj.read_text()
        prompt = self.create_analysis_prompt(file_path, file_content, is_recipe=True)

        try:
            response = self.model.invoke(prompt)
            response_text = response.content if hasattr(response, 'content') else str(response)

            data = self.extract_json_from_text(response_text)
            if not data or 'execution_order' not in data:
                logger.error(f"Invalid JSON from LLAMA for {file_path}")
                return {"execution_order": []}

            logger.info(f"✓ Extracted {len(data['execution_order'])} execution items")
            return data

        except Exception as e:
            logger.error(f"Failed to analyze {file_path}: {e}")
            return {"execution_order": []}

    def analyze_provider(self, file_path: str) -> dict:
        """Analyze provider and extract templates/resources created."""
        logger.info(f"Analyzing provider: {file_path}")

        path_obj = Path(file_path)
        if not path_obj.exists():
            logger.warning(f"Provider not found: {file_path}")
            return {"unconditional_templates": [], "conditionals": []}

        file_content = path_obj.read_text()
        prompt = self.create_analysis_prompt(file_path, file_content, is_recipe=False)

        try:
            response = self.model.invoke(prompt)
            response_text = response.content if hasattr(response, 'content') else str(response)

            data = self.extract_json_from_text(response_text)
            if not data:
                logger.error(f"Invalid JSON from LLAMA for provider {file_path}")
                return {"unconditional_templates": [], "conditionals": []}

            logger.info(f"✓ Provider has {len(data.get('unconditional_templates', []))} unconditional templates, {len(data.get('conditionals', []))} conditional branches")
            return data

        except Exception as e:
            logger.error(f"Failed to analyze provider {file_path}: {e}")
            return {"unconditional_templates": [], "conditionals": []}

    def resolve_recipe_path(self, recipe_name: str, dependency_paths: list[str]) -> str | None:
        """Resolve recipe name to full path."""
        if '::' in recipe_name:
            cookbook, recipe = recipe_name.split('::', 1)
        else:
            cookbook = recipe_name
            recipe = 'default'

        for dep_path in dependency_paths:
            dep_dir = Path(dep_path)

            # Check if dep_path itself is a cookbook
            if (dep_dir / 'recipes').exists():
                if cookbook in dep_dir.name or dep_dir.name == cookbook:
                    recipe_path = dep_dir / 'recipes' / f'{recipe}.rb'
                    if recipe_path.exists():
                        return str(recipe_path)

            # Check subdirectories
            if dep_dir.is_dir():
                for cookbook_dir in dep_dir.iterdir():
                    if cookbook_dir.is_dir():
                        if cookbook in cookbook_dir.name or cookbook_dir.name.startswith(f"{cookbook}-"):
                            recipe_path = cookbook_dir / 'recipes' / f'{recipe}.rb'
                            if recipe_path.exists():
                                return str(recipe_path)

        return None

    def resolve_provider_path(self, resource_type: str, dependency_paths: list[str]) -> str | None:
        """Resolve custom resource to provider path."""
        parts = resource_type.split('_')
        if len(parts) < 2:
            return None

        for i in range(1, len(parts)):
            cookbook = '_'.join(parts[:i])
            provider = '_'.join(parts[i:])

            for dep_path in dependency_paths:
                dep_dir = Path(dep_path)

                if (dep_dir / 'providers').exists():
                    if cookbook in dep_dir.name or dep_dir.name == cookbook:
                        provider_path = dep_dir / 'providers' / f'{provider}.rb'
                        if provider_path.exists():
                            return str(provider_path)

                if dep_dir.is_dir():
                    for cookbook_dir in dep_dir.iterdir():
                        if cookbook_dir.is_dir():
                            if cookbook in cookbook_dir.name or cookbook_dir.name.startswith(f"{cookbook}-"):
                                provider_path = cookbook_dir / 'providers' / f'{provider}.rb'
                                if provider_path.exists():
                                    return str(provider_path)

        return None

    def process_execution_order(self, execution_order: list[dict], dependency_paths: list[str]) -> list[dict]:
        """Process execution order, expanding includes and custom resources."""
        processed = []

        for item in execution_order:
            item_type = item.get('type')

            if item_type == 'include_recipe':
                # Resolve and analyze child recipe
                recipe_name = item.get('recipe_name')
                recipe_path = self.resolve_recipe_path(recipe_name, dependency_paths)

                if recipe_path:
                    # Check for circular dependency
                    if recipe_path in self.visited_files:
                        logger.warning(f"Circular dependency: {recipe_name}")
                        self.circular_deps.append({
                            "recipe": recipe_name,
                            "warning": "Circular reference detected"
                        })
                        item['note'] = "CIRCULAR DEPENDENCY - already loaded"
                        item['child_node'] = None
                    else:
                        # Analyze child recipe
                        child_analysis = self.analyze_recipe_execution(recipe_path)
                        child_exec_order = self.process_execution_order(
                            child_analysis.get('execution_order', []),
                            dependency_paths
                        )

                        item['child_node'] = {
                            "recipe_path": recipe_path,
                            "recipe_name": recipe_name,
                            "execution_order": child_exec_order
                        }

                processed.append(item)

            elif item_type == 'custom_resource':
                # Analyze provider
                resource_type = item.get('resource_type')
                provider_path = self.resolve_provider_path(resource_type, dependency_paths)

                if provider_path:
                    provider_data = self.analyze_provider(provider_path)
                    item['provider_path'] = provider_path
                    item['provider_analysis'] = {
                        "templates": provider_data.get('unconditional_templates', []),
                        "conditionals": provider_data.get('conditionals', [])
                    }

                    # Track custom resource
                    self.custom_resources_used.append({
                        "type": resource_type,
                        "provider_path": provider_path
                    })

                processed.append(item)

            elif item_type == 'conditional':
                # Process nested execution order
                nested = item.get('execution_order', [])
                item['execution_order'] = self.process_execution_order(nested, dependency_paths)
                processed.append(item)

            else:
                # Other items pass through
                processed.append(item)

        return processed

    def trace_execution_tree(self, starting_recipe: str, dependency_paths: list[str]) -> dict:
        """Trace complete execution tree."""
        logger.info(f"Starting execution tree trace from: {starting_recipe}")

        starting_dir = str(Path(starting_recipe).parent.parent.parent)
        all_paths = [starting_dir] + dependency_paths

        # Extract cookbook name
        cookbook_name = Path(starting_recipe).parent.parent.name

        # Analyze starting recipe
        root_analysis = self.analyze_recipe_execution(starting_recipe)

        # Process execution order recursively
        execution_order = self.process_execution_order(
            root_analysis.get('execution_order', []),
            all_paths
        )

        # Build execution tree
        execution_tree = {
            "cookbook": cookbook_name,
            "starting_recipe": starting_recipe,
            "metadata": {
                "generated_at": "2025-11-17",
                "total_recipes": len(self.all_recipes),
                "has_circular_dependencies": len(self.circular_deps) > 0
            },
            "execution_tree": {
                "recipe_path": starting_recipe,
                "recipe_name": f"{cookbook_name}::default",
                "execution_order": execution_order
            },
            "all_recipes": self.all_recipes,
            "circular_dependencies": self.circular_deps,
            "custom_resources_used": self.custom_resources_used
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
        output_file = "execution_tree_output.json"
        with open(output_file, "w") as f:
            json.dump(result, f, indent=2)

        print(f"\n✓ Saved to: {output_file}")

    except Exception as e:
        logger.error(f"Trace failed: {e}", exc_info=True)
        print(f"✗ Error: {e}")


if __name__ == "__main__":
    main()
