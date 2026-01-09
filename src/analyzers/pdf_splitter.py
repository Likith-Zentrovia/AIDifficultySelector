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
    COMPLEX = Has real content images OR has tables
    """

    # Minimum size for an image to be considered "content" (not icon/bullet)
    MIN_IMAGE_WIDTH = 150
    MIN_IMAGE_HEIGHT = 150
    # Minimum area (width * height) for image to count
    MIN_IMAGE_AREA = 30000  # e.g., 150x200 or 200x150

    def __init__(self, min_image_size: int = 150):
        """
        Initialize PDF splitter.

        Args:
            min_image_size: Minimum image dimension (both width AND height must be >= this)
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
        Analyze a single page for complexity.

        COMPLEX if:
        - Has real content images (not tiny icons/bullets)
        - Has a table with borders
        - Is a scanned page

        SIMPLE if:
        - Text only (any layout)
        """
        reasons = []

        # === CHECK FOR REAL IMAGES ===
        image_count = self._count_real_images(doc, page)

        # === CHECK FOR TABLES ===
        has_table = self._detect_table(page)

        # === CHECK IF SCANNED ===
        is_scanned = self._is_scanned_page(page)

        # === DETERMINE COMPLEXITY ===
        is_complex = False

        if image_count > 0:
            is_complex = True
            reasons.append(f"{image_count} image(s)")

        if has_table:
            is_complex = True
            reasons.append("table detected")

        if is_scanned:
            is_complex = True
            reasons.append("scanned page")

        return PageAnalysis(
            page_number=page_num + 1,
            is_complex=is_complex,
            image_count=image_count,
            has_table=has_table,
            is_scanned=is_scanned,
            reasons=reasons,
        )

    def _count_real_images(self, doc, page) -> int:
        """
        Count REAL content images on a page.

        Only counts images that are:
        - Large enough to be content (not icons/bullets)
        - Actually extractable image data
        """
        images = page.get_images(full=True)
        count = 0

        for img in images:
            try:
                xref = img[0]
                base_image = doc.extract_image(xref)

                if not base_image:
                    continue

                width = base_image.get("width", 0)
                height = base_image.get("height", 0)

                # Must be large in BOTH dimensions to be a real content image
                if width >= self.min_image_size and height >= self.min_image_size:
                    # Additional check: area must be significant
                    area = width * height
                    if area >= self.MIN_IMAGE_AREA:
                        count += 1

            except Exception:
                # If we can't extract, don't count it
                continue

        return count

    def _is_scanned_page(self, page) -> bool:
        """
        Detect if page is scanned (full-page image with minimal text).
        """
        text = page.get_text().strip()

        # If page has reasonable text, it's not scanned
        if len(text) > 100:
            return False

        # Check if there's a large image covering most of the page
        images = page.get_images(full=True)
        if not images:
            return False

        page_area = page.rect.width * page.rect.height

        # Look for a full-page or near-full-page image
        for img in images:
            try:
                # Get image placement on page
                img_rects = page.get_image_rects(img)
                for rect in img_rects:
                    img_area = rect.width * rect.height
                    # If image covers >50% of page and there's little text
                    if img_area > page_area * 0.5 and len(text) < 50:
                        return True
            except Exception:
                continue

        return False

    def _detect_table(self, page) -> bool:
        """
        Detect if page has a real table with borders.

        Uses PyMuPDF's find_tables() which is reliable.
        """
        # Method 1: Use PyMuPDF's table finder (most reliable)
        try:
            tables = page.find_tables()
            if tables and len(tables.tables) > 0:
                for table in tables.tables:
                    # Real table has at least 2 rows and 2 columns
                    if table.row_count >= 2 and table.col_count >= 2:
                        return True
        except (AttributeError, Exception):
            pass

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
            "=" * 60,
            f"Total Pages: {len(analyses)}",
            f"Simple Pages (text only): {len(simple)}",
            f"Complex Pages (images/tables): {len(complex_list)}",
            "",
        ]

        if complex_list:
            lines.append("COMPLEX PAGES:")
            lines.append("-" * 40)
            for a in complex_list:
                reasons = ", ".join(a.reasons) if a.reasons else "unknown"
                lines.append(f"  Page {a.page_number}: {reasons}")

        lines.append("")

        if simple:
            lines.append("SIMPLE PAGES:")
            lines.append("-" * 40)
            if len(simple) <= 50:
                page_nums = ", ".join(str(a.page_number) for a in simple)
                lines.append(f"  Pages: {page_nums}")
            else:
                lines.append(f"  {len(simple)} pages (text only)")

        return "\n".join(lines)
