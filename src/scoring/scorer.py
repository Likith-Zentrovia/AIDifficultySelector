"""Complexity scoring engine that determines document difficulty level."""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional

from ..analyzers.base import DocumentFeatures

logger = logging.getLogger(__name__)


class ComplexityLevel(Enum):
    """Document complexity classification."""
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


@dataclass
class ScoringResult:
    """Result of complexity scoring."""
    # Overall score (0-100)
    total_score: float

    # Classification
    level: ComplexityLevel

    # Individual component scores
    component_scores: Dict[str, float] = field(default_factory=dict)

    # Weights used
    weights_used: Dict[str, float] = field(default_factory=dict)

    # Reasoning for the classification
    reasoning: list = field(default_factory=list)

    # Confidence in the classification (0-1)
    confidence: float = 1.0

    def to_dict(self) -> dict:
        """Convert result to dictionary."""
        return {
            "total_score": round(self.total_score, 2),
            "level": self.level.value,
            "component_scores": {
                k: round(v, 2) for k, v in self.component_scores.items()
            },
            "weights_used": self.weights_used,
            "reasoning": self.reasoning,
            "confidence": round(self.confidence, 2),
        }


class ComplexityScorer:
    """
    Scores document complexity based on extracted features.

    SIMPLE documents (non-AI conversion):
    - Text-heavy PDFs (even multi-column)
    - Few images (0-3)
    - Simple or no tables
    - Standard fonts

    COMPLEX documents (AI conversion needed):
    - Many images (5+)
    - Complex tables (nested, spanning cells)
    - Many different fonts (5+)
    - Scanned documents
    - Interactive forms
    """

    # Default weights - focused on what ACTUALLY makes conversion hard
    DEFAULT_WEIGHTS = {
        "image_count": 35,       # Many images = complex
        "complex_tables": 25,    # Complex tables need AI
        "font_variety": 15,      # Many fonts = complex formatting
        "is_scanned": 15,        # Scanned = needs OCR/AI
        "has_forms": 10,         # Forms are complex
    }

    # Thresholds for what counts as "complex"
    IMAGE_THRESHOLD = 5          # 5+ images per document = complex
    FONT_THRESHOLD = 5           # 5+ different fonts = complex
    TABLE_THRESHOLD = 3          # 3+ tables = complex

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        simple_threshold: float = 25.0,   # More lenient
        complex_threshold: float = 60.0,  # Easier to be simple
    ):
        """
        Initialize complexity scorer.

        Args:
            weights: Custom weights for scoring components (must sum to 100)
            simple_threshold: Score below this = SIMPLE
            complex_threshold: Score above this = COMPLEX
        """
        self.weights = weights or self.DEFAULT_WEIGHTS.copy()
        self.simple_threshold = simple_threshold
        self.complex_threshold = complex_threshold

        # Validate weights
        total_weight = sum(self.weights.values())
        if abs(total_weight - 100) > 0.01:
            logger.warning(
                f"Weights sum to {total_weight}, normalizing to 100"
            )
            factor = 100 / total_weight
            self.weights = {k: v * factor for k, v in self.weights.items()}

    def score(self, features: DocumentFeatures) -> ScoringResult:
        """
        Calculate complexity score for a document.

        Focus on what actually makes PDF-to-XML conversion difficult:
        - Many images that need to be processed
        - Complex tables that need structure recognition
        - Scanned documents that need OCR
        - Many fonts indicating complex formatting
        """
        component_scores = {}
        reasoning = []

        # === IMAGE COUNT ===
        # Only flag if there are MANY images (5+)
        # 1-2 images in a text doc is fine
        images_per_page = features.image_count / max(1, features.page_count)
        if features.image_count >= self.IMAGE_THRESHOLD or images_per_page > 1:
            component_scores["image_count"] = min(100, features.image_count * 10)
            reasoning.append(f"Many images ({features.image_count} total, {images_per_page:.1f}/page)")
        else:
            component_scores["image_count"] = 0
            if features.image_count > 0:
                reasoning.append(f"Few images ({features.image_count}) - OK for simple conversion")

        # === COMPLEX TABLES ===
        # Tables only matter if there are several or they're complex
        if features.table_count >= self.TABLE_THRESHOLD:
            component_scores["complex_tables"] = min(100, features.table_count * 20)
            reasoning.append(f"Multiple tables ({features.table_count}) requiring structure recognition")
        elif features.table_count > 0:
            component_scores["complex_tables"] = features.table_count * 10
        else:
            component_scores["complex_tables"] = 0

        # === FONT VARIETY ===
        # Many different fonts indicate complex formatting
        if features.font_count >= self.FONT_THRESHOLD:
            component_scores["font_variety"] = min(100, features.font_count * 12)
            reasoning.append(f"Many different fonts ({features.font_count}) - complex formatting")
        else:
            component_scores["font_variety"] = 0

        # === SCANNED DOCUMENT ===
        # Scanned docs ALWAYS need AI/OCR
        if features.is_scanned:
            component_scores["is_scanned"] = 100
            reasoning.append("Scanned document - requires OCR/AI processing")
        else:
            component_scores["is_scanned"] = 0

        # === FORMS ===
        # Interactive forms are complex
        if features.has_forms_score > 0:
            component_scores["has_forms"] = 100
            reasoning.append("Contains interactive forms")
        else:
            component_scores["has_forms"] = 0

        # Calculate weighted total
        total_score = 0.0
        for component, score in component_scores.items():
            weight = self.weights.get(component, 0)
            weighted_score = (score * weight) / 100
            total_score += weighted_score

        # Determine level
        if total_score <= self.simple_threshold:
            level = ComplexityLevel.SIMPLE
            if not any("OK" not in r and "Few" not in r for r in reasoning):
                reasoning = ["Simple text document - suitable for fast non-AI conversion"]
        elif total_score >= self.complex_threshold:
            level = ComplexityLevel.COMPLEX
        else:
            level = ComplexityLevel.MODERATE

        # Calculate confidence
        confidence = self._calculate_confidence(total_score)

        return ScoringResult(
            total_score=total_score,
            level=level,
            component_scores=component_scores,
            weights_used=self.weights,
            reasoning=reasoning,
            confidence=confidence,
        )

    def _calculate_confidence(self, score: float) -> float:
        """Calculate confidence in classification."""
        dist_to_simple = abs(score - self.simple_threshold)
        dist_to_complex = abs(score - self.complex_threshold)
        min_distance = min(dist_to_simple, dist_to_complex)

        if min_distance >= 20:
            return 0.95
        elif min_distance >= 10:
            return 0.85
        elif min_distance >= 5:
            return 0.75
        else:
            return 0.65

    def explain_score(self, result: ScoringResult) -> str:
        """Generate human-readable explanation of scoring."""
        lines = [
            f"Complexity Level: {result.level.value.upper()}",
            f"Total Score: {result.total_score:.1f}/100",
            f"Confidence: {result.confidence:.0%}",
            "",
            "Scoring (only non-zero factors):",
        ]

        for component, score in sorted(
            result.component_scores.items(),
            key=lambda x: x[1],
            reverse=True
        ):
            if score > 0:
                weight = result.weights_used.get(component, 0)
                contribution = (score * weight) / 100
                lines.append(
                    f"  {component}: {score:.0f} "
                    f"(weight: {weight}%, adds: {contribution:.1f})"
                )

        if result.reasoning:
            lines.extend(["", "Analysis:"])
            for reason in result.reasoning:
                lines.append(f"  • {reason}")

        return "\n".join(lines)
