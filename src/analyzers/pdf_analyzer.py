"""PDF document analyzer for extracting complexity features."""

import logging
from pathlib import Path
from typing import Optional

from .base import DocumentAnalyzer, DocumentFeatures, DocumentType

logger = logging.getLogger(__name__)


class PDFAnalyzer(DocumentAnalyzer):
    """
    Analyzes PDF documents to extract complexity features.

    Uses PyMuPDF (fitz) for PDF parsing and analysis.
    """

    def __init__(
        self,
        min_image_size: int = 100,
        sample_pages: int = 0,
        detect_scanned: bool = True,
    ):
        """
        Initialize PDF analyzer.

        Args:
            min_image_size: Minimum image dimension to count as significant
            sample_pages: Number of pages to sample (0 = all pages)
            detect_scanned: Whether to detect scanned/image-only pages
        """
        self.min_image_size = min_image_size
        self.sample_pages = sample_pages
        self.detect_scanned = detect_scanned

    @property
    def supported_type(self) -> DocumentType:
        return DocumentType.PDF

    def analyze(self, file_path: Path) -> DocumentFeatures:
        """
        Analyze a PDF document and extract features.

        Args:
            file_path: Path to the PDF file

        Returns:
            DocumentFeatures with extracted metrics
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise ImportError(
                "PyMuPDF (fitz) is required for PDF analysis. "
                "Install with: pip install PyMuPDF"
            )

        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"PDF file not found: {file_path}")

        features = DocumentFeatures(
            file_path=str(file_path),
            document_type=DocumentType.PDF,
            file_size_bytes=file_path.stat().st_size,
        )

        try:
            doc = fitz.open(file_path)
        except Exception as e:
            features.warnings.append(f"Failed to open PDF: {e}")
            return features

        try:
            features.page_count = len(doc)
            features.metadata = dict(doc.metadata) if doc.metadata else {}

            # Determine which pages to analyze
            pages_to_analyze = self._get_pages_to_analyze(doc)

            # Collect metrics across pages
            total_images = 0
            total_tables = 0
            fonts_seen = set()
            scanned_pages = 0
            pages_with_complex_layout = 0
            total_text_coverage = 0.0
            has_forms = False
            has_annotations = False

            for page_num in pages_to_analyze:
                page = doc[page_num]

                # Analyze images
                images = page.get_images(full=True)
                significant_images = self._count_significant_images(
                    doc, images, page
                )
                total_images += significant_images

                # Analyze text and detect if scanned
                text = page.get_text()
                text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

                # Check for scanned page (has images but little/no extractable text)
                if self.detect_scanned:
                    if len(images) > 0 and len(text.strip()) < 50:
                        scanned_pages += 1

                # Collect fonts
                if "blocks" in text_dict:
                    for block in text_dict["blocks"]:
                        if block.get("type") == 0:  # Text block
                            for line in block.get("lines", []):
                                for span in line.get("spans", []):
                                    font = span.get("font", "")
                                    if font:
                                        fonts_seen.add(font)

                # Detect tables (heuristic: look for structured blocks)
                tables_on_page = self._detect_tables(page, text_dict)
                total_tables += tables_on_page

                # Analyze layout complexity
                if self._has_complex_layout(page, text_dict):
                    pages_with_complex_layout += 1

                # Calculate text coverage
                text_coverage = self._calculate_text_coverage(page, text_dict)
                total_text_coverage += text_coverage

                # Check for annotations
                if page.annots():
                    has_annotations = True

            # Check for forms
            if doc.is_form_pdf:
                has_forms = True

            # Calculate normalized scores
            analyzed_pages = len(pages_to_analyze)
            if analyzed_pages > 0:
                # Image density: images per page
                avg_images_per_page = total_images / analyzed_pages
                features.image_density_score = self.normalize_score(
                    avg_images_per_page, max_value=5.0  # 5+ images/page = max complexity
                )
                features.image_count = total_images

                # Table presence
                avg_tables_per_page = total_tables / analyzed_pages
                features.table_presence_score = self.normalize_score(
                    avg_tables_per_page, max_value=2.0  # 2+ tables/page = max
                )
                features.table_count = total_tables

                # Layout complexity
                complex_layout_ratio = pages_with_complex_layout / analyzed_pages
                features.layout_complexity_score = complex_layout_ratio * 100

                # Text density (inverse - more text = simpler)
                avg_text_coverage = total_text_coverage / analyzed_pages
                # High text coverage with low images = simpler document
                features.text_density_score = self.normalize_score(
                    avg_text_coverage, max_value=0.8, inverse=True
                )

                # Font variety
                features.font_count = len(fonts_seen)
                features.font_variety_score = self.normalize_score(
                    len(fonts_seen), max_value=10.0  # 10+ fonts = max complexity
                )

                # Scanned document detection
                if analyzed_pages > 0:
                    scanned_ratio = scanned_pages / analyzed_pages
                    features.is_scanned = scanned_ratio > 0.5

                # Forms
                features.has_forms_score = 100.0 if has_forms else 0.0
                features.has_annotations = has_annotations

            # Check for embedded fonts
            features.has_embedded_fonts = self._has_embedded_fonts(doc)

            doc.close()

        except Exception as e:
            logger.error(f"Error analyzing PDF: {e}")
            features.warnings.append(f"Analysis error: {e}")

        return features

    def _get_pages_to_analyze(self, doc) -> list:
        """Determine which pages to analyze based on sampling settings."""
        total_pages = len(doc)
        if self.sample_pages <= 0 or self.sample_pages >= total_pages:
            return list(range(total_pages))

        # Sample pages evenly distributed
        step = total_pages / self.sample_pages
        return [int(i * step) for i in range(self.sample_pages)]

    def _count_significant_images(self, doc, images: list, page) -> int:
        """Count images that are significant (not tiny icons)."""
        count = 0
        for img in images:
            try:
                xref = img[0]
                base_image = doc.extract_image(xref)
                if base_image:
                    width = base_image.get("width", 0)
                    height = base_image.get("height", 0)
                    if width >= self.min_image_size and height >= self.min_image_size:
                        count += 1
            except Exception:
                # Count image even if we can't extract details
                count += 1
        return count

    def _detect_tables(self, page, text_dict: dict) -> int:
        """
        Detect tables in a page using heuristics.

        This uses a simple heuristic based on:
        - Drawing rectangles/lines (table borders)
        - Aligned text blocks
        """
        tables = 0

        # Check for rectangular drawings that might be table borders
        drawings = page.get_drawings()
        rect_count = sum(1 for d in drawings if d.get("type") == "re")

        # Many rectangles often indicate tables
        if rect_count > 10:
            tables += 1

        # Check for grid-like line patterns
        lines = [d for d in drawings if d.get("type") in ("l", "s")]
        if len(lines) > 20:
            # Likely has table structure
            tables += 1

        # Check text alignment patterns (columns of aligned text)
        if "blocks" in text_dict:
            text_blocks = [b for b in text_dict["blocks"] if b.get("type") == 0]
            if len(text_blocks) > 5:
                # Check for column alignment
                x_positions = []
                for block in text_blocks:
                    x_positions.append(round(block["bbox"][0], -1))  # Round to 10px

                # If many blocks share x positions, likely tabular
                from collections import Counter
                x_counts = Counter(x_positions)
                aligned_columns = sum(1 for c in x_counts.values() if c >= 3)
                if aligned_columns >= 3:
                    tables += 1

        return min(tables, 3)  # Cap at 3 tables per page for scoring

    def _has_complex_layout(self, page, text_dict: dict) -> bool:
        """Detect if page has complex layout (multi-column, mixed content)."""
        if "blocks" not in text_dict:
            return False

        blocks = text_dict["blocks"]
        if len(blocks) < 3:
            return False

        # Check for multi-column layout
        text_blocks = [b for b in blocks if b.get("type") == 0]
        if len(text_blocks) < 2:
            return False

        # Get x-coordinates of block starts
        x_starts = [b["bbox"][0] for b in text_blocks]

        # Check for distinct columns (blocks starting at different x positions)
        unique_columns = len(set(round(x, -1) for x in x_starts))

        # Check for mixed content (text and images interspersed)
        image_blocks = [b for b in blocks if b.get("type") == 1]
        has_mixed_content = len(image_blocks) > 0 and len(text_blocks) > 0

        # Complex if multi-column OR heavily mixed content
        return unique_columns >= 2 or (has_mixed_content and len(blocks) > 10)

    def _calculate_text_coverage(self, page, text_dict: dict) -> float:
        """Calculate what percentage of the page is covered by text."""
        page_rect = page.rect
        page_area = page_rect.width * page_rect.height

        if page_area <= 0:
            return 0.0

        text_area = 0.0
        if "blocks" in text_dict:
            for block in text_dict["blocks"]:
                if block.get("type") == 0:  # Text block
                    bbox = block["bbox"]
                    block_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
                    text_area += block_area

        return min(1.0, text_area / page_area)

    def _has_embedded_fonts(self, doc) -> bool:
        """Check if document has embedded fonts."""
        try:
            for page in doc:
                fonts = page.get_fonts()
                for font in fonts:
                    # Font tuple: (xref, ext, type, basefont, name, encoding, ...)
                    if len(font) > 2 and font[2]:  # Has type info
                        return True
        except Exception:
            pass
        return False
