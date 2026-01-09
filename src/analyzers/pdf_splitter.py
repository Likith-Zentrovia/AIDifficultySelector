"""PDF Page Splitter - Splits PDFs into simple and complex pages."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

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

    def __init__(self, min_image_size: int = 100):
        """
        Initialize PDF splitter.

        Args:
            min_image_size: Minimum image dimension to count as significant.
                           Default 100px filters tiny icons/bullets.
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
        - Has ANY significant image
        - Has a table (detected via find_tables or grid lines)
        - Is scanned (image with no text)

        SIMPLE if:
        - Text only (any layout/columns)
        """
        reasons = []

        # === METHOD 1: Check for images using get_images ===
        image_count = self._count_images_method1(doc, page)

        # === METHOD 2: Check for images using image blocks in page dict ===
        if image_count == 0:
            image_count = self._count_images_method2(page)

        # === METHOD 3: Check for XObjects (embedded images) ===
        if image_count == 0:
            image_count = self._count_images_method3(page)

        # === CHECK FOR TABLES ===
        has_table = self._detect_table(page)

        # === CHECK IF SCANNED ===
        text = page.get_text().strip()
        all_images = page.get_images(full=True)
        is_scanned = len(all_images) > 0 and len(text) < 50

        # === DETERMINE COMPLEXITY ===
        is_complex = False

        if image_count > 0:
            is_complex = True
            reasons.append(f"{image_count} image(s)")

        if has_table:
            is_complex = True
            reasons.append("table detected")

        if is_scanned and not is_complex:
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

    def _count_images_method1(self, doc, page) -> int:
        """Count images using get_images() - most reliable method."""
        images = page.get_images(full=True)
        count = 0

        for img in images:
            try:
                xref = img[0]
                # Try to get image info
                base_image = doc.extract_image(xref)
                if base_image:
                    w = base_image.get("width", 0)
                    h = base_image.get("height", 0)
                    # Count if either dimension is significant
                    if w >= self.min_image_size or h >= self.min_image_size:
                        count += 1
                else:
                    # Can't extract but image exists - count it
                    count += 1
            except Exception:
                # If extraction fails, still count the image
                count += 1

        return count

    def _count_images_method2(self, page) -> int:
        """Count images using page text dict - catches some missed images."""
        try:
            page_dict = page.get_text("dict", flags=0)
            count = 0

            for block in page_dict.get("blocks", []):
                # Type 1 = image block
                if block.get("type") == 1:
                    # Check size from bbox
                    bbox = block.get("bbox", (0, 0, 0, 0))
                    width = bbox[2] - bbox[0]
                    height = bbox[3] - bbox[1]
                    if width >= self.min_image_size or height >= self.min_image_size:
                        count += 1

            return count
        except Exception:
            return 0

    def _count_images_method3(self, page) -> int:
        """Count XObject images on the page."""
        try:
            xobjects = page.get_xobjects()
            count = 0

            for xobj in xobjects:
                # xobj is (xref, name, invoker, bbox)
                if len(xobj) >= 4:
                    bbox = xobj[3]
                    if bbox:
                        width = abs(bbox[2] - bbox[0])
                        height = abs(bbox[3] - bbox[1])
                        if width >= self.min_image_size or height >= self.min_image_size:
                            count += 1

            return count
        except Exception:
            return 0

    def _detect_table(self, page) -> bool:
        """
        Detect if page has a real table.

        Uses multiple methods:
        1. PyMuPDF's find_tables() (best, requires v1.23.0+)
        2. Grid line detection (fallback)
        """
        # Method 1: Use PyMuPDF's table finder
        try:
            tables = page.find_tables()
            if tables and len(tables.tables) > 0:
                for table in tables.tables:
                    # Real table has at least 2 rows and 2 columns
                    if table.row_count >= 2 and table.col_count >= 2:
                        return True
        except (AttributeError, Exception):
            pass

        # Method 2: Detect grid pattern from drawings
        try:
            drawings = page.get_drawings()
            if not drawings:
                return False

            h_lines = 0
            v_lines = 0

            for d in drawings:
                items = d.get("items", [])
                for item in items:
                    if len(item) >= 3 and item[0] == "l":
                        p1, p2 = item[1], item[2]
                        dx = abs(p1.x - p2.x)
                        dy = abs(p1.y - p2.y)

                        # Horizontal line (long, flat)
                        if dy < 5 and dx > 80:
                            h_lines += 1
                        # Vertical line (tall, thin)
                        elif dx < 5 and dy > 25:
                            v_lines += 1

            # Need both horizontal AND vertical lines for a table grid
            if h_lines >= 3 and v_lines >= 2:
                return True

        except Exception:
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
