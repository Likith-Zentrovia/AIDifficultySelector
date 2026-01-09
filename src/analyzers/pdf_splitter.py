"""PDF Page Splitter - Splits PDFs into simple and complex pages."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PageAnalysis:
    """Analysis result for a single page."""
    page_number: int
    is_complex: bool
    image_count: int = 0
    has_table: bool = False
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

    SIMPLE = Text only (any layout, multi-column OK)
    COMPLEX = Has images OR has tables
    """

    def __init__(self, min_image_size: int = 200):
        """
        Initialize PDF splitter.

        Args:
            min_image_size: Minimum image dimension (width AND height) to count.
                           Images smaller than this are ignored (logos, icons, bullets).
        """
        self.min_image_size = min_image_size

    def analyze_pages(self, file_path: Path) -> List[PageAnalysis]:
        """Analyze each page in a PDF for complexity."""
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
        """
        Analyze a single page.

        Complex if:
        - Has ANY significant image (larger than min_image_size)
        - Has a real table (grid of cells with borders)
        - Is a scanned page (full-page image with no text)

        Simple if:
        - Text only, regardless of layout
        """
        reasons = []

        # === CHECK FOR IMAGES ===
        images = page.get_images(full=True)
        significant_images = 0

        for img in images:
            try:
                xref = img[0]
                base_image = doc.extract_image(xref)
                if base_image:
                    w = base_image.get("width", 0)
                    h = base_image.get("height", 0)
                    # Only count if BOTH dimensions are large enough
                    # This filters out thin lines, small icons, bullets
                    if w >= self.min_image_size and h >= self.min_image_size:
                        significant_images += 1
            except:
                pass  # Don't count if we can't verify size

        # === CHECK FOR TABLES ===
        has_table = self._has_real_table(page)

        # === CHECK IF SCANNED ===
        text = page.get_text().strip()
        is_scanned = False
        # Scanned = has images but almost no extractable text
        if len(images) > 0 and len(text) < 50:
            is_scanned = True

        # === DETERMINE COMPLEXITY ===
        is_complex = False

        if significant_images > 0:
            is_complex = True
            reasons.append(f"{significant_images} image(s)")

        if has_table:
            is_complex = True
            reasons.append("has table")

        if is_scanned:
            is_complex = True
            reasons.append("scanned page")

        return PageAnalysis(
            page_number=page_num + 1,
            is_complex=is_complex,
            image_count=significant_images,
            has_table=has_table,
            is_scanned=is_scanned,
            reasons=reasons,
        )

    def _has_real_table(self, page) -> bool:
        """
        Detect if page has a REAL table (not just multi-column text).

        A real table has:
        - Visible cell borders (rectangles or grid lines)
        - NOT just aligned text columns

        This is conservative - only flags clear tables with borders.
        """
        try:
            # Use PyMuPDF's built-in table finder if available (v1.23.0+)
            tables = page.find_tables()
            if tables and len(tables.tables) > 0:
                # Verify it's a real table with multiple cells
                for table in tables.tables:
                    if table.row_count >= 2 and table.col_count >= 2:
                        return True
        except AttributeError:
            # Fallback for older PyMuPDF versions
            pass
        except Exception:
            pass

        # Fallback: Check for grid-like drawing patterns
        drawings = page.get_drawings()
        if not drawings:
            return False

        # Count horizontal and vertical lines
        h_lines = 0
        v_lines = 0

        for d in drawings:
            items = d.get("items", [])
            for item in items:
                if item[0] == "l" and len(item) >= 3:
                    p1, p2 = item[1], item[2]
                    dx = abs(p1.x - p2.x)
                    dy = abs(p1.y - p2.y)
                    # Horizontal line
                    if dy < 3 and dx > 100:
                        h_lines += 1
                    # Vertical line
                    elif dx < 3 and dy > 30:
                        v_lines += 1

        # Need BOTH horizontal AND vertical lines to form a grid
        # This prevents flagging simple underlines or borders
        if h_lines >= 4 and v_lines >= 3:
            return True

        return False

    def split(
        self,
        file_path: Path,
        output_dir: Optional[Path] = None,
        simple_suffix: str = "_simple",
        complex_suffix: str = "_complex",
    ) -> SplitResult:
        """Split a PDF into simple and complex pages."""
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

        if simple_pages:
            simple_doc = fitz.open()
            for page_num in simple_pages:
                simple_doc.insert_pdf(doc, from_page=page_num-1, to_page=page_num-1)
            simple_path = output_dir / f"{base_name}{simple_suffix}.pdf"
            simple_doc.save(simple_path)
            simple_doc.close()
            result.simple_pdf_path = str(simple_path)
            logger.info(f"Created: {simple_path} ({len(simple_pages)} pages)")

        if complex_pages:
            complex_doc = fitz.open()
            for page_num in complex_pages:
                complex_doc.insert_pdf(doc, from_page=page_num-1, to_page=page_num-1)
            complex_path = output_dir / f"{base_name}{complex_suffix}.pdf"
            complex_doc.save(complex_path)
            complex_doc.close()
            result.complex_pdf_path = str(complex_path)
            logger.info(f"Created: {complex_path} ({len(complex_pages)} pages)")

        doc.close()
        return result

    def analyze_and_report(self, file_path: Path) -> str:
        """Analyze pages and return a human-readable report."""
        analyses = self.analyze_pages(file_path)

        simple = [a for a in analyses if not a.is_complex]
        complex_list = [a for a in analyses if a.is_complex]

        lines = [
            f"PDF Page Analysis: {Path(file_path).name}",
            "=" * 50,
            f"Total Pages: {len(analyses)}",
            f"Simple Pages (text only): {len(simple)}",
            f"Complex Pages (images/tables): {len(complex_list)}",
            "",
        ]

        if complex_list:
            lines.append("Complex Pages:")
            lines.append("-" * 30)
            for a in complex_list:
                reasons = ", ".join(a.reasons) if a.reasons else "unknown"
                lines.append(f"  Page {a.page_number}: {reasons}")

        if simple:
            lines.append("")
            if len(simple) <= 30:
                page_nums = ", ".join(str(a.page_number) for a in simple)
                lines.append(f"Simple Pages: {page_nums}")
            else:
                lines.append(f"Simple Pages: {len(simple)} pages (text only)")

        return "\n".join(lines)
