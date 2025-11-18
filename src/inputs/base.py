"""Shared value objects for all infrastructure analyzers.

This module provides immutable, self-validating value objects used across
all analyzers (Chef, Puppet, Salt).
"""

from pathlib import Path


class FilePath:
    """Value object for file paths with validation.

    Provides type-safe file path operations and ensures file existence checks.
    Immutable once created.
    """

    def __init__(self, path: str | Path):
        self._path = Path(path) if isinstance(path, str) else path

    @property
    def path(self) -> Path:
        """Get the underlying Path object."""
        return self._path

    @property
    def path_str(self) -> str:
        """Get path as string."""
        return str(self._path)

    def exists(self) -> bool:
        """Check if file exists."""
        return self._path.exists()

    def is_file(self) -> bool:
        """Check if path points to a file."""
        return self._path.is_file()

    def read_text(self) -> str:
        """Read file contents.

        Returns:
            File contents as string

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        if not self.exists():
            raise FileNotFoundError(f"File not found: {self._path}")
        return self._path.read_text()

    def parent(self) -> "DirectoryPath":
        """Get parent directory."""
        return DirectoryPath(self._path.parent)

    def name(self) -> str:
        """Get file/directory name."""
        return self._path.name

    def stem(self) -> str:
        """Get filename without extension."""
        return self._path.stem

    def suffix(self) -> str:
        """Get file extension."""
        return self._path.suffix

    def __str__(self) -> str:
        return str(self._path)

    def __repr__(self) -> str:
        return f"FilePath('{self._path}')"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FilePath):
            return False
        return self._path == other._path

    def __hash__(self) -> int:
        return hash(self._path)


class DirectoryPath:
    """Value object for directory paths with validation.

    Provides type-safe directory path operations.
    Immutable once created.
    """

    def __init__(self, path: str | Path):
        self._path = Path(path) if isinstance(path, str) else path

    @property
    def path(self) -> Path:
        """Get the underlying Path object."""
        return self._path

    @property
    def path_str(self) -> str:
        """Get path as string."""
        return str(self._path)

    def exists(self) -> bool:
        """Check if directory exists."""
        return self._path.exists()

    def is_dir(self) -> bool:
        """Check if path points to a directory."""
        return self._path.is_dir()

    def name(self) -> str:
        """Get directory name."""
        return self._path.name

    def parent(self) -> "DirectoryPath":
        """Get parent directory."""
        return DirectoryPath(self._path.parent)

    def join(self, *parts: str) -> FilePath:
        """Join path parts and return FilePath.

        Args:
            *parts: Path parts to join

        Returns:
            New FilePath with joined path
        """
        return FilePath(self._path.joinpath(*parts))

    def iterdir(self) -> list[Path]:
        """List directory contents.

        Returns:
            List of Path objects in directory

        Raises:
            NotADirectoryError: If path is not a directory
        """
        if not self.is_dir():
            raise NotADirectoryError(f"Not a directory: {self._path}")
        return list(self._path.iterdir())

    def __str__(self) -> str:
        return str(self._path)

    def __repr__(self) -> str:
        return f"DirectoryPath('{self._path}')"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DirectoryPath):
            return False
        return self._path == other._path

    def __hash__(self) -> int:
        return hash(self._path)
