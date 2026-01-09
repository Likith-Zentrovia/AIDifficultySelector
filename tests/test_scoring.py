"""Tests for the complexity scoring engine."""

import pytest
from src.analyzers.base import DocumentFeatures, DocumentType
from src.scoring import ComplexityScorer, ComplexityLevel


class TestComplexityScorer:
    """Tests for ComplexityScorer."""

    def test_simple_document(self):
        """Test scoring of a simple text document."""
        features = DocumentFeatures(
            file_path="test.pdf",
            document_type=DocumentType.PDF,
            page_count=10,
            image_density_score=0.0,
            table_presence_score=0.0,
            layout_complexity_score=0.0,
            text_density_score=10.0,  # High text = low score
            font_variety_score=10.0,
            has_forms_score=0.0,
            image_count=0,
            table_count=0,
            font_count=2,
        )

        scorer = ComplexityScorer()
        result = scorer.score(features)

        assert result.level == ComplexityLevel.SIMPLE
        assert result.total_score < 30
        assert result.confidence >= 0.75

    def test_complex_document(self):
        """Test scoring of a complex document with images and tables."""
        features = DocumentFeatures(
            file_path="test.pdf",
            document_type=DocumentType.PDF,
            page_count=50,
            image_density_score=80.0,
            table_presence_score=70.0,
            layout_complexity_score=90.0,
            text_density_score=60.0,
            font_variety_score=50.0,
            has_forms_score=100.0,
            image_count=100,
            table_count=20,
            font_count=8,
        )

        scorer = ComplexityScorer()
        result = scorer.score(features)

        assert result.level == ComplexityLevel.COMPLEX
        assert result.total_score >= 70
        assert "High image density" in " ".join(result.reasoning)

    def test_moderate_document(self):
        """Test scoring of a moderate complexity document."""
        features = DocumentFeatures(
            file_path="test.pdf",
            document_type=DocumentType.PDF,
            page_count=25,
            image_density_score=40.0,
            table_presence_score=30.0,
            layout_complexity_score=40.0,
            text_density_score=40.0,
            font_variety_score=30.0,
            has_forms_score=0.0,
            image_count=15,
            table_count=5,
            font_count=4,
        )

        scorer = ComplexityScorer()
        result = scorer.score(features)

        assert result.level == ComplexityLevel.MODERATE
        assert 30 < result.total_score < 70

    def test_custom_weights(self):
        """Test scoring with custom weights."""
        features = DocumentFeatures(
            file_path="test.pdf",
            document_type=DocumentType.PDF,
            page_count=10,
            image_density_score=100.0,  # Max images
            table_presence_score=0.0,
            layout_complexity_score=0.0,
            text_density_score=0.0,
            font_variety_score=0.0,
            has_forms_score=0.0,
        )

        # Custom weights that heavily favor images
        scorer = ComplexityScorer(
            weights={
                "image_density": 80,
                "table_presence": 5,
                "layout_complexity": 5,
                "text_density": 5,
                "font_variety": 2,
                "page_count": 2,
                "has_forms": 1,
            }
        )
        result = scorer.score(features)

        # With 80% weight on images at 100%, should be complex
        assert result.total_score >= 70

    def test_custom_thresholds(self):
        """Test scoring with custom thresholds."""
        features = DocumentFeatures(
            file_path="test.pdf",
            document_type=DocumentType.PDF,
            page_count=10,
            image_density_score=50.0,
            table_presence_score=50.0,
            layout_complexity_score=50.0,
            text_density_score=50.0,
            font_variety_score=50.0,
            has_forms_score=50.0,
        )

        # Very low complex threshold
        scorer = ComplexityScorer(
            simple_threshold=20,
            complex_threshold=40,
        )
        result = scorer.score(features)

        # Score around 50 should be complex with threshold at 40
        assert result.level == ComplexityLevel.COMPLEX

    def test_scanned_document_boost(self):
        """Test that scanned documents get boosted scores."""
        features = DocumentFeatures(
            file_path="test.pdf",
            document_type=DocumentType.PDF,
            page_count=10,
            image_density_score=20.0,
            table_presence_score=0.0,
            layout_complexity_score=0.0,
            text_density_score=0.0,
            font_variety_score=0.0,
            has_forms_score=0.0,
            is_scanned=True,
        )

        scorer = ComplexityScorer()
        result = scorer.score(features)

        # Scanned docs should have boosted scores
        assert "scanned" in " ".join(result.reasoning).lower()

    def test_explain_score(self):
        """Test human-readable explanation generation."""
        features = DocumentFeatures(
            file_path="test.pdf",
            document_type=DocumentType.PDF,
            page_count=10,
            image_density_score=50.0,
            table_presence_score=50.0,
        )

        scorer = ComplexityScorer()
        result = scorer.score(features)
        explanation = scorer.explain_score(result)

        assert "Complexity Level:" in explanation
        assert "Total Score:" in explanation
        assert "Component Breakdown:" in explanation
