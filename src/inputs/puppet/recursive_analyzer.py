"""Recursive manifest analyzer for Puppet dependencies.

This module provides on-demand recursive analysis of external Puppet classes
during execution tree building.
"""

from pathlib import Path

from src.utils.logging import get_logger

from .models import ManifestAnalysisResult, ManifestExecutionAnalysis
from .path_resolver import PuppetPathResolver
from .services import ManifestAnalysisService

logger = get_logger(__name__)


class RecursiveManifestAnalyzer:
    """Orchestrates on-demand manifest analysis for external class dependencies.

    Maintains a cache of analyzed manifests to prevent duplicate analysis
    and enables lazy resolution during execution tree building.
    """

    def __init__(
        self,
        manifest_service: ManifestAnalysisService,
        path_resolver: PuppetPathResolver,
        initial_manifests: list[ManifestAnalysisResult],
        max_depth: int = 50,
    ):
        self._service = manifest_service
        self._resolver = path_resolver
        self._max_depth = max_depth
        self._depth_counter = 0

        self._cache_by_class: dict[str, ManifestAnalysisResult] = {}
        self._cache_by_path: dict[str, ManifestAnalysisResult] = {}
        self._analyzed_paths: set[str] = set()

        self._initialize_cache(initial_manifests)

    def _initialize_cache(self, manifests: list[ManifestAnalysisResult]) -> None:
        """Populate cache with initial manifests."""
        for manifest in manifests:
            self._cache_manifest(manifest)
            self._analyzed_paths.add(manifest.file_path)

    def _cache_manifest(self, manifest: ManifestAnalysisResult) -> None:
        """Add manifest to cache by class name and file path."""
        class_name = manifest.analysis.class_name
        if class_name:
            self._cache_by_class[class_name] = manifest

        self._cache_by_path[manifest.file_path] = manifest

    def get_or_analyze_class(self, class_name: str) -> ManifestAnalysisResult | None:
        """Get manifest from cache or analyze on-demand.

        Returns None if:
        - Class cannot be resolved to a file path
        - Analysis fails
        - Max depth limit exceeded
        """
        if not class_name:
            return None

        if self._depth_counter >= self._max_depth:
            logger.warning(
                f"Max depth ({self._max_depth}) reached, skipping analysis of {class_name}"
            )
            return None

        cached = self._cache_by_class.get(class_name)
        if cached:
            return cached

        file_path = self._resolver.resolve_class(class_name)
        if not file_path:
            logger.debug(f"Cannot resolve class {class_name} to file path")
            return None

        file_path_str = str(file_path)

        if file_path_str in self._analyzed_paths:
            return self._cache_by_path.get(file_path_str)

        return self._analyze_manifest(class_name, file_path)

    def _analyze_manifest(
        self, class_name: str, file_path: Path
    ) -> ManifestAnalysisResult | None:
        """Analyze a manifest file on-demand."""
        self._depth_counter += 1
        file_path_str = str(file_path)

        try:
            logger.info(
                f"Analyzing external class {class_name} from {file_path.relative_to(Path.cwd())}"
            )
        except ValueError:
            logger.info(f"Analyzing external class {class_name} from {file_path}")

        self._analyzed_paths.add(file_path_str)

        analysis_result = self._run_analysis(file_path_str)
        if not analysis_result:
            return None

        result = ManifestAnalysisResult(
            file_path=file_path_str,
            file_type="manifest",
            analysis=analysis_result,
        )

        self._cache_manifest(result)
        return result

    def _run_analysis(self, file_path_str: str) -> ManifestExecutionAnalysis | None:
        """Execute manifest analysis service."""
        from src.types.file_analysis_state import FileAnalysisState

        try:
            initial_state = FileAnalysisState(user_message="", path=file_path_str)
            final_state = self._service.execute(initial_state, metrics=None)
            return final_state.result
        except Exception as e:
            logger.error(f"Failed to analyze manifest {file_path_str}: {e}")
            return None

    def get_all_manifests(self) -> list[ManifestAnalysisResult]:
        """Return complete list of manifests including discovered dependencies."""
        return list(self._cache_by_path.values())
