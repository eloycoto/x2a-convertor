"""Chef infrastructure analyzer.

This module implements the main ChefSubagent that orchestrates all Chef analysis.
It maintains backward compatibility with the original implementation while using
clean SOLID/DDD architecture internally.
"""

from dataclasses import dataclass
from pathlib import Path
from langchain_community.tools.file_management.file_search import FileSearchTool
from langchain_community.tools.file_management.list_dir import ListDirectoryTool
from langchain_community.tools.file_management.read import ReadFileTool
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import create_react_agent

from prompts.get_prompt import get_prompt
from src.inputs.base import FilePath
from src.inputs.tree_analysis import TreeSitterAnalyzer
from src.model import get_last_ai_message, get_model, get_runnable_config
from src.utils.logging import get_logger

from .dependency_fetcher import ChefDependencyManager
from .execution_tree_builder import ExecutionTreeBuilder
from .models import (
    AttributesAnalysisResult,
    ProviderAnalysisResult,
    RecipeAnalysisResult,
    StructuredAnalysis,
)
from .path_resolver import ChefPathResolver
from .prompts import ChefPromptFactory
from .services import (
    AttributeAnalysisService,
    ProviderAnalysisService,
    RecipeAnalysisService,
)

logger = get_logger(__name__)


class ChefAgentError(Exception):
    """Raised when Chef agent returns invalid response."""


@dataclass
class ChefState:
    """State object for Chef analysis workflow."""

    path: str
    user_message: str
    specification: str
    dependency_paths: list[str]
    export_path: str | None
    structured_analysis: StructuredAnalysis | None = None


class ChefSubagent:
    """Main Chef analyzer - implements InfrastructureAnalyzer protocol.

    This class orchestrates all Chef analysis using a LangGraph workflow.
    It composes services following Dependency Injection pattern.

    Workflow phases:
    1. fetch_dependencies - Fetch cookbook dependencies
    2. analyze_structure - Use analysis services to analyze all files
    3. write_report - Generate migration plan using structured analysis
    4. validate_with_analysis - Validate plan against analysis
    5. cleanup_specification - Clean up the specification
    6. cleanup_temp_files - Cleanup temporary files
    """

    def __init__(self, model=None) -> None:
        self.model = model or get_model()

        # Compose services (Dependency Injection)
        self._prompt_factory = ChefPromptFactory()
        self._path_resolver = ChefPathResolver()
        self._recipe_service = RecipeAnalysisService(self.model, self._prompt_factory)
        self._provider_service = ProviderAnalysisService(
            self.model, self._prompt_factory
        )
        self._attribute_service = AttributeAnalysisService(
            self.model, self._prompt_factory
        )

        # Existing LangGraph components
        self.agent = self._create_agent()
        self._workflow = self._create_workflow()
        self._dependency_fetcher: ChefDependencyManager | None = None

        logger.debug(self._workflow.get_graph().draw_mermaid())

    def _create_agent(self):
        """Create a LangGraph agent with file management tools."""
        logger.info("Creating chef agent")

        tools = [
            FileSearchTool(),
            ListDirectoryTool(),
            ReadFileTool(),
        ]

        agent = create_react_agent(
            model=self.model,
            tools=tools,
        )
        return agent

    def _create_workflow(self):
        """Create LangGraph workflow.

        Workflow phases:
        1. fetch_dependencies - Fetch cookbook dependencies
        2. analyze_structure - Use analysis services to analyze all files
        3. write_report - Generate migration plan using structured analysis
        4. validate_with_analysis - Validate plan against analysis
        5. cleanup_specification - Clean up the specification
        6. cleanup_temp_files - Cleanup temporary files
        """
        workflow = StateGraph(ChefState)

        workflow.add_node(
            "fetch_dependencies", lambda state: self._prepare_dependencies(state)
        )
        workflow.add_node(
            "analyze_structure", lambda state: self._analyze_structure(state)
        )
        workflow.add_node("write_report", lambda state: self._write_report(state))
        workflow.add_node(
            "validate_with_analysis", lambda state: self._validate_with_analysis(state)
        )
        workflow.add_node(
            "cleanup_specification", lambda state: self._cleanup_specification(state)
        )
        workflow.add_node(
            "cleanup_temp_files", lambda state: self._cleanup_temp_files(state)
        )

        workflow.set_entry_point("fetch_dependencies")
        workflow.add_edge("fetch_dependencies", "analyze_structure")
        workflow.add_edge("analyze_structure", "write_report")
        workflow.add_edge("write_report", "validate_with_analysis")
        workflow.add_edge("validate_with_analysis", "cleanup_specification")
        workflow.add_edge("cleanup_specification", "cleanup_temp_files")
        workflow.add_edge("cleanup_temp_files", END)

        return workflow.compile()

    def list_files(self, paths: list[str]) -> list[str]:
        """Search multiple paths for cookbook files."""
        search_tool = FileSearchTool()
        all_files = []

        for path in paths:
            try:
                files = search_tool.run({"dir_path": path, "pattern": "*"}).splitlines()
                all_files.extend([f"{path}/{x}" for x in files])
            except Exception as e:
                logger.warning(f"Error listing files in {path}: {e}")
                continue

        return all_files

    def _prepare_dependencies(self, state: ChefState) -> ChefState:
        """Fetch external dependencies using chef-cli."""
        slog = logger.bind(phase="prepare_dependencies")
        slog.info(f"Checking for external dependencies for {state.path}")
        self._dependency_fetcher = ChefDependencyManager(state.path)

        has_deps, deps = self._dependency_fetcher.has_dependencies()
        if not has_deps:
            slog.info("No external dependencies found, using local cookbooks only")
            state.dependency_paths = [f"{state.path}/cookbooks"]
            state.export_path = None
            return state

        slog.info("Found external dependencies, fetching with chef-cli...")
        self._dependency_fetcher.fetch_dependencies()
        try:
            dependency_paths = self._dependency_fetcher.get_dependencies_paths(deps)
            if dependency_paths:
                state.dependency_paths = dependency_paths
                state.export_path = str(self._dependency_fetcher.export_path)
        except RuntimeError:
            slog.warning(
                "PolicyLock has not been found, so there is no dependency path"
            )
            state.dependency_paths = []
            state.export_path = None

        return state

    def _cleanup_temp_files(self, state: ChefState) -> ChefState:
        """Cleanup temporary dependency files."""
        if self._dependency_fetcher:
            self._dependency_fetcher.cleanup()

        return state

    def _analyze_structure(self, state: ChefState) -> ChefState:
        """Analyze cookbook structure using analysis services.

        This phase uses RecipeAnalysisService, ProviderAnalysisService, and
        AttributeAnalysisService to create structured analysis of all Chef files.
        """
        slog = logger.bind(phase="analyze_structure")
        slog.info("Starting structured analysis of cookbook files")

        all_paths = [Path(x) for x in [state.path, *state.dependency_paths]]
        recipes: list[RecipeAnalysisResult] = []
        providers: list[ProviderAnalysisResult] = []
        attributes: list[AttributesAnalysisResult] = []

        # STEP 1: Analyze attributes FIRST to build collection map
        slog.info("Step 1: Analyzing attributes to build iteration map")
        attribute_collections = {}  # Map of collection names to their keys

        for path in all_paths:
            if not path.exists():
                continue

            # Find attributes files
            for attr_file in path.glob("**/attributes/default.rb"):
                try:
                    file_path = FilePath(attr_file)
                    slog.debug(f"Analyzing attributes: {attr_file}")
                    analysis = self._attribute_service.analyze(file_path)
                    attributes.append(
                        AttributesAnalysisResult(
                            file_path=str(attr_file), analysis=analysis
                        )
                    )

                    # Build collection map for iteration expansion
                    # Look for nested dicts that look like collections (all values are dicts)
                    def find_collections(attrs_dict, path=""):
                        """Recursively find collection attributes."""
                        for key, value in attrs_dict.items():
                            current_path = f"{path}.{key}" if path else key

                            if isinstance(value, dict) and len(value) > 1:
                                # Check if all values are dicts (collection pattern)
                                # e.g., sites: {site1: {...}, site2: {...}}
                                all_dict_values = all(isinstance(v, dict) for v in value.values())
                                slog.debug(f"Checking '{current_path}': all_dict_values={all_dict_values}, keys={list(value.keys())[:5]}")

                                if all_dict_values:
                                    # Check if this is a deep collection by recursing first
                                    # This ensures we find nginx.sites instead of nginx
                                    collections_before = len(attribute_collections)
                                    slog.debug(f"Recursing into '{current_path}' (collections_before={collections_before})")
                                    find_collections(value, current_path)
                                    collections_added = len(attribute_collections) - collections_before
                                    slog.debug(f"After recursing '{current_path}': collections_added={collections_added}")

                                    # Only mark as collection if no deeper collections were found
                                    if collections_added == 0:
                                        # This is a leaf collection
                                        attribute_collections[current_path] = list(value.keys())
                                        slog.info(f"✓ Found LEAF collection '{current_path}' with {len(value)} items: {list(value.keys())}")
                                else:
                                    # This is just a namespace, recurse deeper
                                    slog.debug(f"Namespace '{current_path}', recursing")
                                    find_collections(value, current_path)

                    find_collections(analysis.attributes)
                except Exception as e:
                    slog.warning(f"Failed to analyze attributes {attr_file}: {e}")

        slog.info(f"Built iteration map with {len(attribute_collections)} collections")

        # STEP 2: Analyze recipes and providers with iteration context
        slog.info("Step 2: Analyzing recipes and providers")

        # Scan all paths for Chef files
        for path in all_paths:
            if not path.exists():
                slog.warning(f"Path does not exist: {path_str}")
                continue

            # Find all recipe files (cookbooks/*/recipes/*.rb)
            for recipe_file in path.glob("**/recipes/*.rb"):
                try:
                    file_path = FilePath(recipe_file)
                    slog.debug(f"Analyzing recipe: {recipe_file}")
                    analysis = self._recipe_service.analyze(file_path)
                    recipes.append(
                        RecipeAnalysisResult(
                            file_path=str(recipe_file), analysis=analysis
                        )
                    )
                except Exception as e:
                    slog.warning(f"Failed to analyze recipe {recipe_file}: {e}")

            # Find all provider files (cookbooks/*/providers/*.rb)
            for provider_file in path.glob("**/providers/*.rb"):
                try:
                    file_path = FilePath(provider_file)
                    slog.debug(f"Analyzing provider: {provider_file}")
                    analysis = self._provider_service.analyze(file_path)
                    providers.append(
                        ProviderAnalysisResult(
                            file_path=str(provider_file), analysis=analysis
                        )
                    )
                except Exception as e:
                    slog.warning(f"Failed to analyze provider {provider_file}: {e}")

        # Create structured analysis aggregate
        state.structured_analysis = StructuredAnalysis(
            recipes=recipes,
            providers=providers,
            attributes=attributes,
            attribute_collections=attribute_collections,
        )

        slog.info(
            f"✓ Analyzed {len(recipes)} recipes, {len(providers)} providers, "
            f"{len(attributes)} attributes files with {len(attribute_collections)} iterable collections"
        )

        return state

    def _check_files(self, state: ChefState) -> ChefState:
        """Validate and improve migration plan by analyzing each file."""
        files = self.list_files([state.path, *state.dependency_paths])
        read_tool = ReadFileTool()
        slog = logger.bind(phase="check_files")
        slog.info(f"Validating migration plan against {len(files)} files")

        # TODO: Rethink following.
        # Maybe run this in parallel, there can be many files and it takes forever
        for fp in files:
            try:
                # Read the file content
                file_content = read_tool.run({"file_path": fp})

                # Skip empty files or binary files
                if not file_content or not isinstance(file_content, str):
                    continue

                # Prepare validation prompts
                system_message = get_prompt("chef_analysis_file_validation_system")
                user_prompt = get_prompt("chef_analysis_file_validation_task").format(
                    current_specification=state.specification,
                    file_path=fp,
                    file_content=file_content,
                )

                # Execute validation agent
                result = self.agent.invoke(
                    {
                        "messages": [
                            {"role": "system", "content": system_message},
                            {"role": "user", "content": user_prompt},
                        ]
                    },
                    config=get_runnable_config(),
                )
                message = get_last_ai_message(result)
                if not message:
                    slog.info(f"There is no response from AI on file '{fp}'")
                    continue
                validation_response = message.content
                if validation_response.startswith("VALIDATED:"):
                    slog.debug(f"File validated: {fp} - {validation_response}")
                    continue
                if validation_response.startswith("SKIP:"):
                    slog.debug(f"File skipped: {fp} - {validation_response}")
                    continue

                slog.info(f"Updating specification based on file: {fp}")
                state.specification = self._merge_specification_update(
                    state.specification, validation_response
                )
            except Exception as e:
                slog.warning(f"Error processing file {fp}: {e}")
                continue

        slog.info("File validation completed")
        return state

    def _validate_with_analysis(self, state: ChefState) -> ChefState:
        """Validate migration plan against structured analysis.

        This phase ensures the migration plan is consistent with the
        structured analysis from recipes, providers, and attributes.
        """
        slog = logger.bind(phase="validate_with_analysis")
        slog.info("Validating migration plan against structured analysis")

        if not state.structured_analysis:
            slog.warning("No structured analysis available, skipping validation")
            return state

        # Prepare execution tree summary for validation
        analysis_summary = self._build_execution_tree_summary(
            state.structured_analysis, state.path, state.dependency_paths
        )

        # Create validation prompt
        system_message = get_prompt("chef_analysis_validation_system")
        user_prompt = get_prompt("chef_analysis_validation_task").format(
            specification=state.specification,
            analysis_summary=analysis_summary,
        )

        # Execute validation agent
        agent = create_react_agent(model=self.model, tools=[])
        result = agent.invoke(
            {
                "messages": [
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_prompt},
                ]
            },
            config=get_runnable_config(),
        )

        message = get_last_ai_message(result)
        if not message:
            slog.warning("No response from validation agent")
            return state

        validation_response = message.content

        # If validation found issues, append them to specification
        if not validation_response.startswith("VALIDATED:"):
            slog.info("Validation found issues, updating specification")
            state.specification = f"{state.specification}\n\n## VALIDATION NOTES ##\n{validation_response}"
        else:
            slog.info("✓ Specification validated successfully")

        return state

    def _build_execution_tree_summary(
        self, analysis: StructuredAnalysis, cookbook_path: str, dependency_paths: list[str]
    ) -> str:
        """Build and format the execution tree showing complete recipe flow."""
        lines = []

        lines.append("=" * 80)
        lines.append("CHEF RECIPE EXECUTION TREE")
        lines.append("=" * 80)
        lines.append("")
        lines.append(f"Total files analyzed: {analysis.get_total_files_analyzed()}")
        lines.append("")

        # Find the entry recipe (usually default.rb in the main cookbook)
        entry_recipe = None
        for recipe_result in analysis.recipes:
            if "default.rb" in recipe_result.file_path and cookbook_path in recipe_result.file_path:
                entry_recipe = recipe_result.file_path
                break

        if not entry_recipe and analysis.recipes:
            # Fallback to first recipe if no default.rb found
            entry_recipe = analysis.recipes[0].file_path

        if entry_recipe:
            # Build execution tree
            tree_builder = ExecutionTreeBuilder(
                structured_analysis=analysis,
                path_resolver=self._path_resolver,
                dependency_paths=dependency_paths,
            )

            tree_root = tree_builder.build_tree(entry_recipe)
            tree_formatted = tree_builder.format_tree(tree_root)

            lines.append("Execution flow starting from entry recipe:")
            lines.append("")
            lines.append(tree_formatted)
        else:
            lines.append("No entry recipe found (expected default.rb)")

        lines.append("")
        lines.append("=" * 80)
        lines.append("")

        # Still show iteration collections summary at the bottom
        if analysis.attribute_collections:
            lines.append("ITERATION COLLECTIONS DETECTED:")
            lines.append("")
            for collection_name, items in analysis.attribute_collections.items():
                lines.append(f"  {collection_name}: {len(items)} items")
                lines.append(f"    → {', '.join(items)}")
            lines.append("")
            lines.append("=" * 80)
            lines.append("")

        return "\n".join(lines)

    def _format_analysis_summary_OLD(self, analysis: StructuredAnalysis) -> str:
        """OLD FORMAT - kept for reference, use _build_execution_tree_summary instead."""
        lines = []

        lines.append(f"Total files analyzed: {analysis.get_total_files_analyzed()}")
        lines.append("")

        # Recipe analysis with detailed execution items
        if analysis.recipes:
            lines.append(f"## Recipes Analyzed ({len(analysis.recipes)})")
            lines.append("")
            for recipe_result in analysis.recipes:
                recipe_name = recipe_result.file_path
                exec_items = recipe_result.analysis.execution_order
                lines.append(f"### {recipe_name}")
                lines.append(f"Execution order ({len(exec_items)} items):")

                # Show each execution item type
                for item in exec_items:
                    item_type = item.get("type", "unknown")
                    if item_type == "resource":
                        resource_type = item.get("resource_type", "?")
                        name = item.get("name", "?")
                        lines.append(f"  - [{item_type}] {resource_type}[{name}]")
                    elif item_type == "custom_resource":
                        resource_type = item.get("resource_type", "?")
                        name = item.get("name", "?")
                        provider_path = item.get("provider_path", "not found")
                        lines.append(
                            f"  - [CUSTOM] {resource_type}[{name}] → provider: {provider_path}"
                        )
                    elif item_type == "include_recipe":
                        recipe_name_inc = item.get("recipe_name", "?")
                        lines.append(f"  - [include_recipe] {recipe_name_inc}")
                    elif item_type == "conditional":
                        condition = item.get("condition", "?")
                        lines.append(f"  - [conditional] {condition}")
                    elif item_type == "attribute_assignment":
                        attr_path = item.get("attribute_path", "?")
                        value = item.get("value", "?")
                        lines.append(f"  - [attribute] {attr_path} = {value}")
                    else:
                        lines.append(f"  - [{item_type}]")

                lines.append("")

        # Provider analysis with templates
        if analysis.providers:
            lines.append(f"## Providers Analyzed ({len(analysis.providers)})")
            lines.append("")
            for provider_result in analysis.providers:
                provider_name = provider_result.file_path
                provider_analysis = provider_result.analysis
                lines.append(f"### {provider_name}")

                # Unconditional templates
                if provider_analysis.unconditional_templates:
                    lines.append(
                        f"Unconditional templates ({len(provider_analysis.unconditional_templates)}):"
                    )
                    for tmpl in provider_analysis.unconditional_templates:
                        source = tmpl.get("source", "?")
                        path = tmpl.get("path", "?")
                        lines.append(f"  - {source} → {path}")

                # Conditional templates
                if provider_analysis.conditionals:
                    lines.append(
                        f"Conditional branches ({len(provider_analysis.conditionals)}):"
                    )
                    for cond in provider_analysis.conditionals:
                        condition = cond.get("condition", "?")
                        templates = cond.get("templates", [])
                        lines.append(f"  - Condition: {condition}")
                        for tmpl in templates:
                            source = tmpl.get("source", "?")
                            path = tmpl.get("path", "?")
                            lines.append(f"    → {source} → {path}")

                if not provider_analysis.unconditional_templates and not provider_analysis.conditionals:
                    lines.append("  (No templates rendered by this provider)")

                lines.append("")

        # Attributes analysis with values
        if analysis.attributes:
            lines.append(f"## Attributes Analyzed ({len(analysis.attributes)})")
            lines.append("")
            for attr_result in analysis.attributes:
                attr_name = attr_result.file_path
                attrs = attr_result.analysis.attributes
                notes = attr_result.analysis.platform_specific_notes

                lines.append(f"### {attr_name}")
                lines.append(f"Default attributes ({len(attrs)} top-level):")

                # Show attribute structure
                import json

                for key, value in attrs.items():
                    if isinstance(value, dict):
                        # Show nested dict with keys for iteration expansion
                        dict_keys = list(value.keys())
                        if len(dict_keys) <= 10:  # Show all keys if reasonable
                            lines.append(
                                f"  - {key}: dict with {len(dict_keys)} keys: {dict_keys}"
                            )
                        else:
                            lines.append(
                                f"  - {key}: dict with {len(dict_keys)} keys (showing first 10): {dict_keys[:10]}..."
                            )
                    else:
                        lines.append(f"  - {key}: {json.dumps(value)}")

                # Platform-specific notes
                if notes:
                    lines.append("Platform-specific notes:")
                    for note in notes:
                        lines.append(f"  - {note}")

                lines.append("")

        return "\n".join(lines)

    def _build_iteration_tree(self, analysis: StructuredAnalysis) -> list[str]:
        """Build a visual tree showing expanded iterations with attribute values."""
        tree_lines = []

        # Get stored collections
        attribute_collections = analysis.attribute_collections
        if not attribute_collections:
            return []

        # Get actual attribute values for detail - need to handle nested paths
        def get_nested_value(attrs_dict, path):
            """Get value from nested path like 'nginx.sites'."""
            parts = path.split('.')
            current = attrs_dict
            for part in parts:
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return None
            return current

        # Build tree for each collection
        for collection_name, items in attribute_collections.items():
            tree_lines.append(f"Collection: {collection_name}")
            tree_lines.append(f"Total items: {len(items)}")
            tree_lines.append("")

            # Get attribute values for this collection using nested path
            collection_values = {}
            for attr_result in analysis.attributes:
                nested_val = get_nested_value(attr_result.analysis.attributes, collection_name)
                if nested_val:
                    collection_values = nested_val
                    break

            for idx, item in enumerate(items):
                is_last = idx == len(items) - 1
                prefix = "└──" if is_last else "├──"
                tree_lines.append(f"{prefix} {item}")

                # Show attribute values for this item if available
                if item in collection_values:
                    item_attrs = collection_values[item]
                    if isinstance(item_attrs, dict):
                        attr_items = list(item_attrs.items())
                        for attr_idx, (attr_key, attr_val) in enumerate(attr_items):
                            is_last_attr = attr_idx == len(attr_items) - 1
                            connector = "    " if is_last else "│   "
                            attr_prefix = "└──" if is_last_attr else "├──"

                            # Format the value nicely
                            if isinstance(attr_val, str):
                                formatted_val = f"'{attr_val}'"
                            elif isinstance(attr_val, bool):
                                formatted_val = str(attr_val).lower()
                            else:
                                formatted_val = str(attr_val)

                            tree_lines.append(f"{connector}{attr_prefix} {attr_key}: {formatted_val}")

            tree_lines.append("")

        return tree_lines

    def _detect_iterations(self, analysis: StructuredAnalysis) -> list[str]:
        """Detect collection attributes that need iteration expansion."""
        warnings = []

        # Use stored attribute_collections if available
        attribute_collections = getattr(analysis, 'attribute_collections', {})

        if attribute_collections:
            for key, keys_list in attribute_collections.items():
                warning = (
                    f"⚠ Collection '{key}' has {len(keys_list)} items that MUST be listed explicitly:\n"
                    f"   Items: {keys_list}\n"
                    f"   → In your migration plan, write:\n"
                    f"   → \"Iterations: Runs {len(keys_list)} times for: {', '.join(f'**{k}**' for k in keys_list)}\"\n"
                    f"   → Then describe each item individually:\n"
                )
                for item in keys_list:
                    warning += f"   →   - **{item}**: [description]\n"
                warnings.append(warning)
                warnings.append("")
        else:
            # Fallback to old method
            for attr_result in analysis.attributes:
                attrs = attr_result.analysis.attributes

                for key, value in attrs.items():
                    if isinstance(value, dict) and len(value) > 1:
                        keys_list = list(value.keys())
                        warning = (
                            f"⚠ Attribute '{key}' contains {len(keys_list)} items: {keys_list}\n"
                            f"   → When recipes iterate over this collection, you MUST list all {len(keys_list)} items explicitly:\n"
                            f"   → {', '.join(f'**{k}**' for k in keys_list)}"
                        )
                        warnings.append(warning)
                        warnings.append("")

        return warnings

    def _merge_specification_update(self, current_spec: str, update: str) -> str:
        """Merge updated section into the current specification."""
        if not current_spec:
            return update

        return f"{current_spec}\n\n## VALIDATION UPDATE ##\n{update}"

    def _cleanup_specification(self, state: ChefState) -> ChefState:
        """Clean up the messy specification with validation updates."""
        slog = logger.bind(phase="cleanup_specification")
        slog.info("Cleaning up migration specification")

        # Prepare cleanup prompts
        system_message = get_prompt("chef_analysis_cleanup_system")
        user_prompt = get_prompt("chef_analysis_cleanup_task").format(
            messy_specification=state.specification
        )

        agent = create_react_agent(
            model=self.model,
            tools=[],
        )
        # Execute cleanup agent
        result = agent.invoke(
            {
                "messages": [
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_prompt},
                ]
            },
            config=get_runnable_config(),
        )

        message = get_last_ai_message(result)
        if not message:
            slog.warning("No valid response from cleanup agent")
            return state

        state.specification = message.content

        return state

    def _write_report(self, state: ChefState) -> ChefState:
        """Generate migration specification using structured analysis."""
        slog = logger.bind(phase="write_report")
        slog.info("Generating migration specification")
        data_list = "\n".join(self.list_files([state.path, *state.dependency_paths]))

        # Generate tree-sitter analysis report
        analyzer = TreeSitterAnalyzer()
        try:
            tree_sitter_report = analyzer.report_directory(state.path)
        except Exception as e:
            slog.warning(f"Failed to generate tree-sitter report: {e}")
            tree_sitter_report = "Tree-sitter analysis not available"

        # Build execution tree if available
        execution_tree_summary = ""
        if state.structured_analysis:
            execution_tree_summary = self._build_execution_tree_summary(
                state.structured_analysis, state.path, state.dependency_paths
            )
            slog.info(
                f"Built execution tree from {state.structured_analysis.get_total_files_analyzed()} analyzed files"
            )
        else:
            slog.warning("No structured analysis available")

        # Prepare system and user messages for chef agent
        system_message = get_prompt("chef_analysis_system")
        user_prompt = get_prompt("chef_analysis_task").format(
            path=state.path,
            user_message=state.user_message,
            directory_listing=data_list,
            tree_sitter_report=tree_sitter_report,
            execution_tree=execution_tree_summary,
        )

        # DEBUG: Save execution tree for inspection
        with open("debug_execution_tree.txt", "w") as f:
            f.write(execution_tree_summary)
        slog.debug("Saved execution tree to debug_execution_tree.txt")

        # Execute chef agent with both system and user messages
        result = self.agent.invoke(
            {
                "messages": [
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_prompt},
                ]
            },
            config=get_runnable_config(),
        )
        messages = result.get("messages", [])
        if len(messages) < 2:
            raise ChefAgentError("Invalid response from Chef agent")

        state.specification = messages[-1].content
        slog.info("✓ Migration specification generated")
        return state

    def invoke(self, path: str, user_message: str) -> str:
        """Analyze a Chef cookbook and return migration plan.

        This method satisfies the InfrastructureAnalyzer protocol.

        Args:
            path: Path to Chef cookbook
            user_message: User's migration requirements

        Returns:
            Migration specification as markdown string
        """
        logger.info("Using Chef agent for migration analysis...")

        initial_state = ChefState(
            path=path,
            user_message=user_message,
            specification="",
            dependency_paths=[],
            export_path=None,
        )

        result = self._workflow.invoke(initial_state, config=get_runnable_config())
        return result["specification"]
