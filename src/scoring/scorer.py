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

    Uses weighted scoring across multiple dimensions to determine
    overall complexity level.
    """

    # Default weights (must sum to 100)
    DEFAULT_WEIGHTS = {
        "image_density": 25,
        "table_presence": 20,
        "layout_complexity": 20,
        "text_density": 10,
        "font_variety": 10,
        "page_count": 5,
        "has_forms": 10,
    }

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        simple_threshold: float = 30.0,
        complex_threshold: float = 70.0,
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

        Args:
            features: Extracted document features

        Returns:
            ScoringResult with score and classification
        """
        component_scores = {}
        reasoning = []

        # Image density
        component_scores["image_density"] = features.image_density_score
        if features.image_density_score > 50:
            reasoning.append(
                f"High image density ({features.image_count} images)"
            )

        # Table presence
        component_scores["table_presence"] = features.table_presence_score
        if features.table_presence_score > 50:
            reasoning.append(
                f"Contains tables ({features.table_count} detected)"
            )

        # Layout complexity
        component_scores["layout_complexity"] = features.layout_complexity_score
        if features.layout_complexity_score > 50:
            reasoning.append("Complex layout detected (multi-column or mixed content)")

        # Text density (inverse scoring handled in analyzer)
        component_scores["text_density"] = features.text_density_score
        if features.text_density_score < 30:
            reasoning.append("High text coverage (simpler structure)")

        # Font variety
        component_scores["font_variety"] = features.font_variety_score
        if features.font_variety_score > 50:
            reasoning.append(f"Multiple fonts used ({features.font_count})")

        # Page count factor
        page_score = self._score_page_count(features.page_count)
        component_scores["page_count"] = page_score

        # Forms
        component_scores["has_forms"] = features.has_forms_score
        if features.has_forms_score > 0:
            reasoning.append("Contains interactive forms")

        # Check for scanned document (big complexity factor)
        if features.is_scanned:
            reasoning.append("Appears to be scanned document (requires OCR)")
            # Boost all scores for scanned docs
            for key in component_scores:
                component_scores[key] = min(100, component_scores[key] + 30)

        # Calculate weighted total
        total_score = 0.0
        for component, score in component_scores.items():
            weight = self.weights.get(component, 0)
            weighted_score = (score * weight) / 100
            total_score += weighted_score

        # Determine level
        if total_score <= self.simple_threshold:
            level = ComplexityLevel.SIMPLE
            if not reasoning:
                reasoning.append("Simple text-based document with minimal formatting")
        elif total_score >= self.complex_threshold:
            level = ComplexityLevel.COMPLEX
        else:
            level = ComplexityLevel.MODERATE
            if not reasoning:
                reasoning.append("Moderate complexity with some formatting elements")

        # Calculate confidence based on how clearly it falls into a category
        confidence = self._calculate_confidence(total_score)

        return ScoringResult(
            total_score=total_score,
            level=level,
            component_scores=component_scores,
            weights_used=self.weights,
            reasoning=reasoning,
            confidence=confidence,
        )

    def _score_page_count(self, page_count: int) -> float:
        """
        Score based on page count.

        Longer documents are slightly more complex due to potential
        for varied layouts throughout.
        """
        if page_count <= 10:
            return 10.0
        elif page_count <= 50:
            return 30.0
        elif page_count <= 100:
            return 50.0
        elif page_count <= 500:
            return 70.0
        else:
            return 90.0

    def _calculate_confidence(self, score: float) -> float:
        """
        Calculate confidence in classification.

        Higher confidence when score is clearly in one category.
        Lower confidence when score is near thresholds.
        """
        # Distance from nearest threshold
        dist_to_simple = abs(score - self.simple_threshold)
        dist_to_complex = abs(score - self.complex_threshold)
        min_distance = min(dist_to_simple, dist_to_complex)

        # Confidence based on distance from thresholds
        # If score is far from thresholds, high confidence
        # If score is near thresholds, lower confidence
        if min_distance >= 20:
            return 0.95
        elif min_distance >= 10:
            return 0.85
        elif min_distance >= 5:
            return 0.75
        else:
            return 0.65

    def explain_score(self, result: ScoringResult) -> str:
        """
        Generate human-readable explanation of scoring.

        Args:
            result: ScoringResult to explain

        Returns:
            Formatted explanation string
        """
        lines = [
            f"Complexity Level: {result.level.value.upper()}",
            f"Total Score: {result.total_score:.1f}/100",
            f"Confidence: {result.confidence:.0%}",
            "",
            "Component Breakdown:",
        ]

        for component, score in sorted(
            result.component_scores.items(),
            key=lambda x: x[1],
            reverse=True
        ):
            weight = result.weights_used.get(component, 0)
            contribution = (score * weight) / 100
            lines.append(
                f"  {component}: {score:.1f} "
                f"(weight: {weight}%, contribution: {contribution:.1f})"
            )

        if result.reasoning:
            lines.extend(["", "Key Factors:"])
            for reason in result.reasoning:
                lines.append(f"  • {reason}")

        return "\n".join(lines)
