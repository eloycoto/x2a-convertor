"""Build hierarchical execution tree from Chef structured analysis.

This module builds a visual tree showing the complete recipe execution flow
with loops expanded and attribute values inline.
"""

from pathlib import Path

from src.utils.logging import get_logger

from .models import ExecutionNode, RecipeAnalysisResult, StructuredAnalysis
from .path_resolver import ChefPathResolver

logger = get_logger(__name__)


class ExecutionTreeBuilder:
    """Builds hierarchical execution tree from structured analysis."""

    def __init__(
        self,
        structured_analysis: StructuredAnalysis,
        path_resolver: ChefPathResolver,
        dependency_paths: list[str],
    ):
        self.analysis = structured_analysis
        self.path_resolver = path_resolver
        self.dependency_paths = dependency_paths
        self.visited_recipes = set()  # Prevent circular includes

        # Build recipe lookup map
        self.recipe_map = {}
        for recipe_result in structured_analysis.recipes:
            self.recipe_map[recipe_result.file_path] = recipe_result

    def build_tree(self, entry_recipe_path: str) -> ExecutionNode:
        """Build execution tree starting from entry recipe."""
        logger.info(f"Building execution tree from {entry_recipe_path}")

        # Find the entry recipe in analyzed recipes
        if entry_recipe_path not in self.recipe_map:
            logger.warning(f"Entry recipe not found in analysis: {entry_recipe_path}")
            return ExecutionNode(
                node_type="recipe",
                name=entry_recipe_path,
                details="Recipe not found in analysis",
            )

        return self._expand_recipe(entry_recipe_path, depth=0)

    def _expand_recipe(self, recipe_path: str, depth: int) -> ExecutionNode:
        """Recursively expand a recipe and its includes."""
        # Prevent circular includes
        if recipe_path in self.visited_recipes:
            return ExecutionNode(
                node_type="recipe",
                name=Path(recipe_path).stem,
                file_path=recipe_path,
                details="[CIRCULAR DEPENDENCY - already visited]",
            )

        self.visited_recipes.add(recipe_path)

        recipe_result = self.recipe_map.get(recipe_path)
        if not recipe_result:
            return ExecutionNode(
                node_type="recipe",
                name=Path(recipe_path).stem,
                file_path=recipe_path,
                details="Recipe not analyzed",
            )

        # Create recipe node
        recipe_node = ExecutionNode(
            node_type="recipe",
            name=Path(recipe_path).stem,
            file_path=recipe_path,
        )

        # Process execution order items
        for item in recipe_result.analysis.execution_order:
            item_type = item.get("type")

            if item_type == "include_recipe":
                # Recursively expand included recipe
                included_recipe_name = item.get("recipe_name", "")
                included_recipe_path = self._resolve_recipe_path(included_recipe_name)

                if included_recipe_path:
                    child_node = self._expand_recipe(included_recipe_path, depth + 1)
                    recipe_node.children.append(child_node)
                else:
                    # Recipe not found, add a placeholder
                    recipe_node.children.append(
                        ExecutionNode(
                            node_type="recipe",
                            name=included_recipe_name,
                            details="Recipe file not found",
                        )
                    )

            elif item_type == "resource":
                # Standard Chef resource
                resource_type = item.get("resource_type", "?")
                name = item.get("name", "?")
                attrs = item.get("attributes", {})

                details_parts = []
                if attrs:
                    # Show important attributes
                    for key in ["source", "action", "command", "path"]:
                        if key in attrs:
                            details_parts.append(f"{key}: {attrs[key]}")

                recipe_node.children.append(
                    ExecutionNode(
                        node_type="resource",
                        name=f"{resource_type}[{name}]",
                        resource_type=resource_type,
                        details=", ".join(details_parts) if details_parts else None,
                    )
                )

            elif item_type == "custom_resource":
                # Custom resource (LWRP)
                resource_type = item.get("resource_type", "?")
                name = item.get("name", "?")
                provider_path = item.get("provider_path")

                recipe_node.children.append(
                    ExecutionNode(
                        node_type="custom_resource",
                        name=f"{resource_type}[{name}]",
                        resource_type=resource_type,
                        provider_path=provider_path,
                        details=f"provider: {provider_path}" if provider_path else None,
                    )
                )

            elif item_type == "conditional":
                # Conditional block - could expand this later
                condition = item.get("condition", "?")
                recipe_node.children.append(
                    ExecutionNode(
                        node_type="conditional",
                        name=f"if {condition}",
                        details="Conditional execution",
                    )
                )

            elif item_type == "attribute_assignment":
                # Skip attribute assignments in tree for now
                pass

        # Check if this recipe has loops to expand
        recipe_node = self._expand_loops_in_recipe(recipe_node, recipe_result)

        return recipe_node

    def _expand_loops_in_recipe(
        self, recipe_node: ExecutionNode, recipe_result: RecipeAnalysisResult
    ) -> ExecutionNode:
        """Detect and expand loops in the recipe using attribute collections."""
        # If no attribute collections, no loops to expand
        if not self.analysis.attribute_collections:
            logger.debug(f"No attribute collections to expand in {recipe_node.name}")
            return recipe_node

        logger.debug(f"Checking {recipe_node.name} for loops. Available collections: {list(self.analysis.attribute_collections.keys())}")

        # Look for conditional nodes with .each patterns in execution order
        new_children = []
        for child in recipe_node.children:
            # Check if this is a conditional with .each (loop pattern)
            if (
                child.node_type == "conditional"
                and child.name
                and ".each" in child.name
            ):
                logger.info(f"Found .each loop in {recipe_node.name}: {child.name}")
                # This looks like a loop - try to expand it
                expanded = self._try_expand_loop(child)
                new_children.append(expanded)
            else:
                new_children.append(child)

        recipe_node.children = new_children
        return recipe_node

    def _try_expand_loop(self, conditional_node: ExecutionNode) -> ExecutionNode:
        """Try to expand a .each loop into explicit items."""
        # Extract collection name from conditional like "node['nginx']['sites'].each"
        # or "redis_instances.each"
        condition = conditional_node.name
        logger.debug(f"Trying to expand loop with condition: {condition}")

        # Find matching collection in attribute_collections
        for collection_name, items in self.analysis.attribute_collections.items():
            # Match patterns like:
            # - "node['nginx']['sites'].each" -> nginx.sites
            # - "sites.each" -> sites
            # Simple heuristic: if collection_name appears in condition
            collection_parts = collection_name.split(".")
            logger.debug(f"Checking collection '{collection_name}' (parts: {collection_parts}) against condition")

            if any(part in condition for part in collection_parts):
                logger.info(f"✓ Matched collection '{collection_name}' with {len(items)} items: {items}")
                # Found matching collection - create LOOP node
                loop_node = ExecutionNode(
                    node_type="loop",
                    name=collection_name,
                    details=f"{len(items)} items",
                )

                # Get attribute values for each item
                item_attributes = self._get_collection_attributes(collection_name)
                logger.debug(f"Extracted attributes for {len(item_attributes)} items")

                # Create loop_item nodes for each item
                for item_name in items:
                    item_attrs = item_attributes.get(item_name, {})
                    loop_item = ExecutionNode(
                        node_type="loop_item",
                        name=item_name,
                        attributes=item_attrs,
                        # Include the original resources from the loop body
                        children=conditional_node.children,
                    )
                    loop_node.children.append(loop_item)

                logger.info(f"✓ Expanded loop into {len(loop_node.children)} items")
                return loop_node

        # No matching collection found, return as-is
        logger.warning(f"No matching collection found for condition: {condition}")
        return conditional_node

    def _get_collection_attributes(self, collection_path: str) -> dict:
        """Get attribute values for a collection path like 'nginx.sites'."""
        result = {}

        # Navigate through attribute files to find the collection values
        for attr_result in self.analysis.attributes:
            attrs = attr_result.analysis.attributes

            # Split path like "nginx.sites" into ["nginx", "sites"]
            parts = collection_path.split(".")
            current = attrs

            # Navigate nested dict
            for part in parts:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    current = None
                    break

            # If we found the collection, return it
            if isinstance(current, dict):
                result = current
                break

        return result

    def _resolve_recipe_path(self, recipe_name: str) -> str | None:
        """Resolve recipe name to file path."""
        # recipe_name format: "cookbook::recipe" or just "recipe"
        # Search in recipe_map for matching file
        for path in self.recipe_map:
            if recipe_name in path or Path(path).stem == recipe_name:
                return path
        return None

    def format_tree(self, node: ExecutionNode, prefix: str = "", is_last: bool = True) -> str:
        """Format execution tree as visual ASCII tree."""
        lines = []

        # Format current node
        connector = "└── " if is_last else "├── "
        if not prefix:  # Root node
            connector = ""

        # Build node label
        if node.node_type == "recipe":
            label = f"{node.name}.rb"
            if node.details:
                label += f" {node.details}"
        elif node.node_type in ["resource", "custom_resource"]:
            label = f"[{node.node_type}] {node.name}"
            if node.details:
                label += f" ({node.details})"
        elif node.node_type == "loop":
            label = f"LOOP over {node.name} ({len(node.children)} items)"
        elif node.node_type == "loop_item":
            label = node.name
            if node.attributes:
                # Format attributes inline
                attrs_str = ", ".join(
                    f"{k}: {v!r}" for k, v in list(node.attributes.items())[:3]
                )
                label += f" {{{attrs_str}}}"
        else:
            label = f"{node.name}"
            if node.details:
                label += f" ({node.details})"

        lines.append(f"{prefix}{connector}{label}")

        # Format children
        if node.children:
            for idx, child in enumerate(node.children):
                is_last_child = idx == len(node.children) - 1

                # Build child prefix based on current node position
                extension = "    " if is_last else "│   "
                child_prefix = prefix + extension

                child_lines = self.format_tree(child, child_prefix, is_last_child)
                lines.append(child_lines)

        return "\n".join(lines)
