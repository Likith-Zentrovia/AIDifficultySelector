"""PDF Page Splitter - Splits PDFs into simple and complex pages."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


@dataclass
class PageAnalysis:
    """Analysis result for a single page."""
    page_number: int
    is_complex: bool
    image_count: int = 0
    table_count: int = 0
    has_forms: bool = False
    is_scanned: bool = False
    reasons: List[str] = field(default_factory=list)


@dataclass
class SplitResult:
    """Result of splitting a PDF."""
    original_file: str
    total_pages: int
    simple_pages: List[int]
    complex_pages: List[int]
    simple_pdf_path: Optional[str] = None
    complex_pdf_path: Optional[str] = None
    page_analyses: List[PageAnalysis] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "original_file": self.original_file,
            "total_pages": self.total_pages,
            "simple_pages": {
                "count": len(self.simple_pages),
                "pages": self.simple_pages,
                "output_file": self.simple_pdf_path,
            },
            "complex_pages": {
                "count": len(self.complex_pages),
                "pages": self.complex_pages,
                "output_file": self.complex_pdf_path,
            },
        }


class PDFSplitter:
    """
    Splits PDFs into simple and complex pages.

    Simple pages: Text-only or minimal images
    Complex pages: Many images, tables, scanned content
    """

    def __init__(
        self,
        min_image_size: int = 100,
        images_threshold: int = 2,      # 2+ images = complex page
        tables_threshold: int = 1,       # 1+ tables = complex page
    ):
        """
        Initialize PDF splitter.

        Args:
            min_image_size: Minimum image dimension to count
            images_threshold: Images per page to mark as complex
            tables_threshold: Tables per page to mark as complex
        """
        self.min_image_size = min_image_size
        self.images_threshold = images_threshold
        self.tables_threshold = tables_threshold

    def analyze_pages(self, file_path: Path) -> List[PageAnalysis]:
        """
        Analyze each page in a PDF for complexity.

        Args:
            file_path: Path to PDF file

        Returns:
            List of PageAnalysis for each page
        """
        try:
            import fitz
        except ImportError:
            raise ImportError("PyMuPDF required: pip install PyMuPDF")

        file_path = Path(file_path)
        analyses = []

        doc = fitz.open(file_path)

        for page_num in range(len(doc)):
            page = doc[page_num]
            analysis = self._analyze_page(doc, page, page_num)
            analyses.append(analysis)

        doc.close()
        return analyses

    def _analyze_page(self, doc, page, page_num: int) -> PageAnalysis:
        """Analyze a single page for complexity."""
        reasons = []

        # Count significant images
        images = page.get_images(full=True)
        significant_images = 0
        for img in images:
            try:
                xref = img[0]
                base_image = doc.extract_image(xref)
                if base_image:
                    w = base_image.get("width", 0)
                    h = base_image.get("height", 0)
                    if w >= self.min_image_size and h >= self.min_image_size:
                        significant_images += 1
            except:
                significant_images += 1

        # Detect tables (heuristic)
        table_count = self._detect_tables(page)

        # Check if scanned (image with little text)
        text = page.get_text().strip()
        is_scanned = len(images) > 0 and len(text) < 100

        # Check for forms
        has_forms = False
        widgets = page.widgets()
        if widgets:
            has_forms = len(list(widgets)) > 0

        # Determine if complex
        is_complex = False

        if significant_images >= self.images_threshold:
            is_complex = True
            reasons.append(f"{significant_images} images")

        if table_count >= self.tables_threshold:
            is_complex = True
            reasons.append(f"{table_count} table(s)")

        if is_scanned:
            is_complex = True
            reasons.append("scanned page")

        if has_forms:
            is_complex = True
            reasons.append("has form fields")

        return PageAnalysis(
            page_number=page_num + 1,  # 1-indexed for user display
            is_complex=is_complex,
            image_count=significant_images,
            table_count=table_count,
            has_forms=has_forms,
            is_scanned=is_scanned,
            reasons=reasons,
        )

    def _detect_tables(self, page) -> int:
        """Detect tables on a page using drawing heuristics."""
        drawings = page.get_drawings()

        # Count rectangles and lines
        rect_count = sum(1 for d in drawings if d.get("type") == "re")
        line_count = sum(1 for d in drawings if d.get("type") in ("l", "s"))

        # Heuristic: many rectangles or lines = likely table
        if rect_count > 10 or line_count > 20:
            return 1

        # Check for grid patterns in text alignment
        text_dict = page.get_text("dict", flags=0)
        if "blocks" in text_dict:
            text_blocks = [b for b in text_dict["blocks"] if b.get("type") == 0]
            if len(text_blocks) > 5:
                # Check column alignment
                x_positions = [round(b["bbox"][0], -1) for b in text_blocks]
                from collections import Counter
                x_counts = Counter(x_positions)
                aligned_cols = sum(1 for c in x_counts.values() if c >= 3)
                if aligned_cols >= 3:
                    return 1

        return 0

    def split(
        self,
        file_path: Path,
        output_dir: Optional[Path] = None,
        simple_suffix: str = "_simple",
        complex_suffix: str = "_complex",
    ) -> SplitResult:
        """
        Split a PDF into simple and complex pages.

        Args:
            file_path: Path to input PDF
            output_dir: Directory for output files (default: same as input)
            simple_suffix: Suffix for simple pages PDF
            complex_suffix: Suffix for complex pages PDF

        Returns:
            SplitResult with paths to output files
        """
        try:
            import fitz
        except ImportError:
            raise ImportError("PyMuPDF required: pip install PyMuPDF")

        file_path = Path(file_path)
        if output_dir is None:
            output_dir = file_path.parent
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Analyze all pages
        analyses = self.analyze_pages(file_path)

        simple_pages = [a.page_number for a in analyses if not a.is_complex]
        complex_pages = [a.page_number for a in analyses if a.is_complex]

        result = SplitResult(
            original_file=str(file_path),
            total_pages=len(analyses),
            simple_pages=simple_pages,
            complex_pages=complex_pages,
            page_analyses=analyses,
        )

        # Create output PDFs
        doc = fitz.open(file_path)
        base_name = file_path.stem

        # Simple pages PDF
        if simple_pages:
            simple_doc = fitz.open()
            for page_num in simple_pages:
                simple_doc.insert_pdf(doc, from_page=page_num-1, to_page=page_num-1)
            simple_path = output_dir / f"{base_name}{simple_suffix}.pdf"
            simple_doc.save(simple_path)
            simple_doc.close()
            result.simple_pdf_path = str(simple_path)
            logger.info(f"Created simple PDF: {simple_path} ({len(simple_pages)} pages)")

        # Complex pages PDF
        if complex_pages:
            complex_doc = fitz.open()
            for page_num in complex_pages:
                complex_doc.insert_pdf(doc, from_page=page_num-1, to_page=page_num-1)
            complex_path = output_dir / f"{base_name}{complex_suffix}.pdf"
            complex_doc.save(complex_path)
            complex_doc.close()
            result.complex_pdf_path = str(complex_path)
            logger.info(f"Created complex PDF: {complex_path} ({len(complex_pages)} pages)")

        doc.close()
        return result

    def analyze_and_report(self, file_path: Path) -> str:
        """
        Analyze pages and return a human-readable report.

        Args:
            file_path: Path to PDF

        Returns:
            Formatted report string
        """
        analyses = self.analyze_pages(file_path)

        simple = [a for a in analyses if not a.is_complex]
        complex = [a for a in analyses if a.is_complex]

        lines = [
            f"PDF Page Analysis: {file_path.name}",
            "=" * 50,
            f"Total Pages: {len(analyses)}",
            f"Simple Pages: {len(simple)} ({len(simple)/len(analyses)*100:.0f}%)",
            f"Complex Pages: {len(complex)} ({len(complex)/len(analyses)*100:.0f}%)",
            "",
        ]

        if complex:
            lines.append("Complex Pages Detail:")
            lines.append("-" * 30)
            for a in complex:
                reasons = ", ".join(a.reasons) if a.reasons else "unknown"
                lines.append(f"  Page {a.page_number}: {reasons}")

        if simple and len(simple) <= 20:
            lines.append("")
            lines.append(f"Simple Pages: {', '.join(map(str, [a.page_number for a in simple]))}")
        elif simple:
            lines.append("")
            lines.append(f"Simple Pages: {simple[0].page_number}-{simple[-1].page_number} (and others)")

        return "\n".join(lines)
