"""Base classes for document analysis."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class DocumentType(Enum):
    """Supported document types."""
    PDF = "pdf"
    EPUB = "epub"
    UNKNOWN = "unknown"


@dataclass
class DocumentFeatures:
    """
    Features extracted from a document for complexity analysis.

    All scores are normalized to 0-100 range where:
    - 0 = simplest (e.g., no images, single column)
    - 100 = most complex (e.g., many images, complex layout)
    """
    # Basic info
    file_path: str
    document_type: DocumentType
    page_count: int = 0
    file_size_bytes: int = 0

    # Content metrics (0-100 normalized scores)
    image_density_score: float = 0.0      # Images per page, normalized
    table_presence_score: float = 0.0     # Table complexity
    layout_complexity_score: float = 0.0  # Multi-column, mixed layouts
    text_density_score: float = 0.0       # Text coverage
    font_variety_score: float = 0.0       # Number of different fonts
    has_forms_score: float = 0.0          # Interactive elements

    # Raw counts for reporting
    image_count: int = 0
    table_count: int = 0
    font_count: int = 0

    # Flags
    is_scanned: bool = False              # Appears to be scanned document
    has_embedded_fonts: bool = False
    has_transparency: bool = False
    has_annotations: bool = False

    # Additional metadata
    metadata: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert features to dictionary for serialization."""
        return {
            "file_path": self.file_path,
            "document_type": self.document_type.value,
            "page_count": self.page_count,
            "file_size_bytes": self.file_size_bytes,
            "scores": {
                "image_density": self.image_density_score,
                "table_presence": self.table_presence_score,
                "layout_complexity": self.layout_complexity_score,
                "text_density": self.text_density_score,
                "font_variety": self.font_variety_score,
                "has_forms": self.has_forms_score,
            },
            "counts": {
                "images": self.image_count,
                "tables": self.table_count,
                "fonts": self.font_count,
            },
            "flags": {
                "is_scanned": self.is_scanned,
                "has_embedded_fonts": self.has_embedded_fonts,
                "has_transparency": self.has_transparency,
                "has_annotations": self.has_annotations,
            },
            "metadata": self.metadata,
            "warnings": self.warnings,
        }


class DocumentAnalyzer(ABC):
    """Abstract base class for document analyzers."""

    @property
    @abstractmethod
    def supported_type(self) -> DocumentType:
        """Return the document type this analyzer supports."""
        pass

    @abstractmethod
    def analyze(self, file_path: Path) -> DocumentFeatures:
        """
        Analyze a document and extract features.

        Args:
            file_path: Path to the document file

        Returns:
            DocumentFeatures containing extracted metrics

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file type is not supported
        """
        pass

    def can_analyze(self, file_path: Path) -> bool:
        """Check if this analyzer can handle the given file."""
        suffix = file_path.suffix.lower().lstrip(".")
        return suffix == self.supported_type.value

    @staticmethod
    def normalize_score(value: float, max_value: float, inverse: bool = False) -> float:
        """
        Normalize a value to 0-100 range.

        Args:
            value: The raw value
            max_value: The maximum expected value (maps to 100)
            inverse: If True, higher values map to lower scores

        Returns:
            Normalized score between 0 and 100
        """
        if max_value <= 0:
            return 0.0
        normalized = min(100.0, (value / max_value) * 100)
        return 100.0 - normalized if inverse else normalized
