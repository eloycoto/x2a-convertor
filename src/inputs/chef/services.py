"""Chef analysis services.

This module provides services for analyzing Chef files using LLM.
Each service has a single responsibility (SRP).
"""

from src.inputs.base import FilePath
from src.model import get_runnable_config
from src.utils.logging import get_logger

from .models import (
    DefaultAttributesOutput,
    ProviderAnalysisOutput,
    RecipeExecutionAnalysis,
)
from .prompts import ChefPromptFactory

logger = get_logger(__name__)


class RecipeAnalysisService:
    """Service for analyzing Chef recipe files using LLM.

    Responsibility: Extract execution order from recipe files.
    """

    def __init__(self, model, prompt_factory: ChefPromptFactory):
        self._model = model
        self._prompt_factory = prompt_factory

    def analyze(self, file_path: FilePath) -> RecipeExecutionAnalysis:
        """Analyze recipe and extract execution order.

        Args:
            file_path: Path to recipe file

        Returns:
            RecipeExecutionAnalysis with execution_order
        """
        if not file_path.exists():
            logger.warning(f"File not found: {file_path}")
            return RecipeExecutionAnalysis(execution_order=[])

        file_content = file_path.read_text()
        prompt = self._prompt_factory.create_recipe_analysis_prompt(
            file_path.path_str, file_content
        )

        try:
            structured_model = self._model.with_structured_output(
                RecipeExecutionAnalysis
            )
            result = structured_model.invoke(prompt, config=get_runnable_config())
            logger.info(f"✓ Extracted {len(result.execution_order)} execution items")
            return result
        except Exception as e:
            logger.error(f"Failed to analyze {file_path}: {e}")
            return RecipeExecutionAnalysis(execution_order=[])


class ProviderAnalysisService:
    """Service for analyzing Chef provider files using LLM.

    Responsibility: Extract templates and resources created by providers.
    """

    def __init__(self, model, prompt_factory: ChefPromptFactory):
        self._model = model
        self._prompt_factory = prompt_factory

    def analyze(self, file_path: FilePath) -> ProviderAnalysisOutput:
        """Analyze provider and extract templates/resources created.

        Args:
            file_path: Path to provider file

        Returns:
            ProviderAnalysisOutput with templates and conditionals
        """
        if not file_path.exists():
            logger.warning(f"Provider not found: {file_path}")
            return ProviderAnalysisOutput()

        file_content = file_path.read_text()
        prompt = self._prompt_factory.create_provider_analysis_prompt(
            file_path.path_str, file_content
        )

        try:
            structured_model = self._model.with_structured_output(
                ProviderAnalysisOutput
            )
            result = structured_model.invoke(prompt, config=get_runnable_config())
            logger.info(
                f"✓ Provider has {len(result.unconditional_templates)} unconditional templates, "
                f"{len(result.conditionals)} conditional branches"
            )
            return result
        except Exception as e:
            logger.error(f"Failed to analyze provider {file_path}: {e}")
            return ProviderAnalysisOutput()


class AttributeAnalysisService:
    """Service for analyzing Chef attributes files using LLM.

    Responsibility: Extract default attribute values from attributes/default.rb.
    """

    def __init__(self, model, prompt_factory: ChefPromptFactory):
        self._model = model
        self._prompt_factory = prompt_factory

    def analyze(self, file_path: FilePath) -> DefaultAttributesOutput:
        """Analyze attributes file and extract default values.

        Args:
            file_path: Path to attributes/default.rb file

        Returns:
            DefaultAttributesOutput with extracted attributes
        """
        if not file_path.exists():
            logger.warning(f"Attributes file not found: {file_path}")
            return DefaultAttributesOutput()

        file_content = file_path.read_text()
        prompt = self._prompt_factory.create_attributes_extraction_prompt(
            file_path.path_str, file_content
        )

        try:
            structured_model = self._model.with_structured_output(
                DefaultAttributesOutput
            )
            result = structured_model.invoke(prompt, config=get_runnable_config())

            if result.platform_specific_notes:
                logger.info("Platform-specific attributes found:")
                for note in result.platform_specific_notes:
                    logger.info(f"  - {note}")

            logger.info(
                f"✓ Extracted {len(result.attributes)} top-level default attributes"
            )
            return result
        except Exception as e:
            logger.error(f"Failed to analyze attributes {file_path}: {e}")
            return DefaultAttributesOutput()
