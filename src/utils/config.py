"""Configuration loading and management."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class ScoringConfig:
    """Scoring configuration."""
    simple_threshold: float = 30.0
    complex_threshold: float = 70.0


@dataclass
class WeightsConfig:
    """Feature weights configuration."""
    image_count: int = 35
    complex_tables: int = 25
    font_variety: int = 15
    is_scanned: int = 15
    has_forms: int = 10

    def to_dict(self) -> Dict[str, int]:
        return {
            "image_count": self.image_count,
            "complex_tables": self.complex_tables,
            "font_variety": self.font_variety,
            "is_scanned": self.is_scanned,
            "has_forms": self.has_forms,
        }


@dataclass
class PDFAnalysisConfig:
    """PDF analysis configuration."""
    min_image_size: int = 100
    sample_pages: int = 0
    detect_scanned_pages: bool = True


@dataclass
class EPUBAnalysisConfig:
    """EPUB analysis configuration."""
    check_media: bool = True
    analyze_css: bool = True


@dataclass
class ToolConfig:
    """Configuration for a single tool."""
    name: str
    description: str = ""
    command: Optional[str] = None
    enabled: bool = True


@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


@dataclass
class Config:
    """Main configuration object."""
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    weights: WeightsConfig = field(default_factory=WeightsConfig)
    pdf_analysis: PDFAnalysisConfig = field(default_factory=PDFAnalysisConfig)
    epub_analysis: EPUBAnalysisConfig = field(default_factory=EPUBAnalysisConfig)
    tools: Dict[str, ToolConfig] = field(default_factory=dict)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Config":
        """Create Config from dictionary."""
        config = cls()

        if "scoring" in data:
            config.scoring = ScoringConfig(**data["scoring"])

        if "weights" in data:
            config.weights = WeightsConfig(**data["weights"])

        if "pdf_analysis" in data:
            config.pdf_analysis = PDFAnalysisConfig(**data["pdf_analysis"])

        if "epub_analysis" in data:
            config.epub_analysis = EPUBAnalysisConfig(**data["epub_analysis"])

        if "tools" in data:
            for tool_type, tool_data in data["tools"].items():
                if isinstance(tool_data, dict):
                    config.tools[tool_type] = ToolConfig(**tool_data)

        if "logging" in data:
            config.logging = LoggingConfig(**data["logging"])

        return config


def load_config(config_path: Optional[Path] = None) -> Config:
    """
    Load configuration from YAML file.

    Args:
        config_path: Path to config file. If None, uses default config.

    Returns:
        Config object
    """
    if config_path is None:
        # Try to find default config
        default_paths = [
            Path("config/default_config.yaml"),
            Path(__file__).parent.parent.parent / "config" / "default_config.yaml",
        ]
        for path in default_paths:
            if path.exists():
                config_path = path
                break

    if config_path is None or not config_path.exists():
        logger.info("Using default configuration")
        return Config()

    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not installed, using default configuration")
        return Config()

    try:
        with open(config_path) as f:
            data = yaml.safe_load(f)
        logger.info(f"Loaded configuration from {config_path}")
        return Config.from_dict(data or {})
    except Exception as e:
        logger.warning(f"Error loading config from {config_path}: {e}")
        return Config()
