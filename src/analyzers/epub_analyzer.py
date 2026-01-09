"""EPUB document analyzer for extracting complexity features."""

import logging
import re
import zipfile
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

from .base import DocumentAnalyzer, DocumentFeatures, DocumentType

logger = logging.getLogger(__name__)


class EPUBAnalyzer(DocumentAnalyzer):
    """
    Analyzes EPUB documents to extract complexity features.

    EPUBs are essentially ZIP files containing XHTML, CSS, and media files.
    """

    # Common image extensions in EPUBs
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp"}

    # EPUB namespaces
    NAMESPACES = {
        "opf": "http://www.idpf.org/2007/opf",
        "dc": "http://purl.org/dc/elements/1.1/",
        "xhtml": "http://www.w3.org/1999/xhtml",
    }

    def __init__(self, check_media: bool = True, analyze_css: bool = True):
        """
        Initialize EPUB analyzer.

        Args:
            check_media: Whether to check for embedded media (audio/video)
            analyze_css: Whether to analyze CSS complexity
        """
        self.check_media = check_media
        self.analyze_css = analyze_css

    @property
    def supported_type(self) -> DocumentType:
        return DocumentType.EPUB

    def analyze(self, file_path: Path) -> DocumentFeatures:
        """
        Analyze an EPUB document and extract features.

        Args:
            file_path: Path to the EPUB file

        Returns:
            DocumentFeatures with extracted metrics
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"EPUB file not found: {file_path}")

        features = DocumentFeatures(
            file_path=str(file_path),
            document_type=DocumentType.EPUB,
            file_size_bytes=file_path.stat().st_size,
        )

        try:
            with zipfile.ZipFile(file_path, "r") as epub:
                # Get list of all files
                file_list = epub.namelist()

                # Analyze structure
                self._analyze_structure(epub, file_list, features)

                # Analyze content files
                self._analyze_content(epub, file_list, features)

                # Analyze images
                self._analyze_images(epub, file_list, features)

                # Analyze CSS if enabled
                if self.analyze_css:
                    self._analyze_css(epub, file_list, features)

                # Check for media if enabled
                if self.check_media:
                    self._check_media(file_list, features)

                # Extract metadata
                self._extract_metadata(epub, file_list, features)

        except zipfile.BadZipFile:
            features.warnings.append("Invalid EPUB file (not a valid ZIP)")
        except Exception as e:
            logger.error(f"Error analyzing EPUB: {e}")
            features.warnings.append(f"Analysis error: {e}")

        return features

    def _analyze_structure(
        self, epub: zipfile.ZipFile, file_list: list, features: DocumentFeatures
    ):
        """Analyze EPUB structure and count chapters/sections."""
        # Count content files (XHTML/HTML)
        content_files = [
            f for f in file_list
            if f.endswith((".xhtml", ".html", ".htm"))
            and not f.startswith("__MACOSX")
        ]
        features.page_count = len(content_files)

    def _analyze_content(
        self, epub: zipfile.ZipFile, file_list: list, features: DocumentFeatures
    ):
        """Analyze XHTML content for complexity indicators."""
        content_files = [
            f for f in file_list
            if f.endswith((".xhtml", ".html", ".htm"))
            and not f.startswith("__MACOSX")
        ]

        total_tables = 0
        total_images_in_content = 0
        complex_elements = 0
        total_text_length = 0

        for content_file in content_files:
            try:
                content = epub.read(content_file).decode("utf-8", errors="ignore")

                # Count tables
                tables = len(re.findall(r"<table[^>]*>", content, re.IGNORECASE))
                total_tables += tables

                # Count image references
                img_tags = len(re.findall(r"<img[^>]*>", content, re.IGNORECASE))
                svg_tags = len(re.findall(r"<svg[^>]*>", content, re.IGNORECASE))
                total_images_in_content += img_tags + svg_tags

                # Check for complex elements
                # Math/MathML
                if re.search(r"<math[^>]*>", content, re.IGNORECASE):
                    complex_elements += 1

                # Nested lists
                nested_lists = len(re.findall(
                    r"<[ou]l[^>]*>.*?<[ou]l[^>]*>",
                    content,
                    re.IGNORECASE | re.DOTALL
                ))
                complex_elements += nested_lists

                # Forms
                if re.search(r"<form[^>]*>", content, re.IGNORECASE):
                    features.has_forms_score = 100.0

                # Calculate text length (strip tags)
                text_only = re.sub(r"<[^>]+>", "", content)
                total_text_length += len(text_only.strip())

            except Exception as e:
                logger.debug(f"Error reading {content_file}: {e}")

        # Calculate scores
        if features.page_count > 0:
            avg_tables = total_tables / features.page_count
            features.table_presence_score = self.normalize_score(
                avg_tables, max_value=2.0
            )
            features.table_count = total_tables

            avg_images = total_images_in_content / features.page_count
            features.image_density_score = self.normalize_score(
                avg_images, max_value=5.0
            )

            # Layout complexity from complex elements
            complexity_ratio = complex_elements / features.page_count
            features.layout_complexity_score = self.normalize_score(
                complexity_ratio, max_value=1.0
            )

            # Text density (inverse - more text per page = simpler)
            avg_text_per_page = total_text_length / features.page_count
            # Normalize: 5000+ chars per page = high text density
            text_density = min(1.0, avg_text_per_page / 5000)
            features.text_density_score = self.normalize_score(
                text_density, max_value=1.0, inverse=True
            )

    def _analyze_images(
        self, epub: zipfile.ZipFile, file_list: list, features: DocumentFeatures
    ):
        """Count and analyze images in the EPUB."""
        image_files = [
            f for f in file_list
            if Path(f).suffix.lower() in self.IMAGE_EXTENSIONS
            and not f.startswith("__MACOSX")
        ]

        features.image_count = len(image_files)

        # Check for large images (potential full-page graphics)
        large_images = 0
        for img_file in image_files[:20]:  # Sample first 20
            try:
                info = epub.getinfo(img_file)
                # Images larger than 100KB might be full-page
                if info.file_size > 100 * 1024:
                    large_images += 1
            except Exception:
                pass

        # Adjust image density score based on large images
        if large_images > 5:
            features.image_density_score = min(
                100.0, features.image_density_score + 20
            )

    def _analyze_css(
        self, epub: zipfile.ZipFile, file_list: list, features: DocumentFeatures
    ):
        """Analyze CSS complexity."""
        css_files = [f for f in file_list if f.endswith(".css")]

        if not css_files:
            return

        total_rules = 0
        fonts_declared = set()

        for css_file in css_files:
            try:
                css_content = epub.read(css_file).decode("utf-8", errors="ignore")

                # Count CSS rules (approximate)
                rules = len(re.findall(r"\{[^}]*\}", css_content))
                total_rules += rules

                # Find font declarations
                font_families = re.findall(
                    r"font-family\s*:\s*([^;]+)",
                    css_content,
                    re.IGNORECASE
                )
                for ff in font_families:
                    # Extract font names
                    fonts = re.findall(r"['\"]?([^'\"]+)['\"]?", ff)
                    fonts_declared.update(fonts)

                # Check for complex CSS features
                if re.search(r"@media", css_content):
                    features.layout_complexity_score = min(
                        100.0, features.layout_complexity_score + 10
                    )

            except Exception as e:
                logger.debug(f"Error reading CSS {css_file}: {e}")

        features.font_count = len(fonts_declared)
        features.font_variety_score = self.normalize_score(
            len(fonts_declared), max_value=10.0
        )

    def _check_media(self, file_list: list, features: DocumentFeatures):
        """Check for embedded audio/video media."""
        media_extensions = {".mp3", ".mp4", ".ogg", ".wav", ".webm", ".m4a", ".m4v"}

        media_files = [
            f for f in file_list
            if Path(f).suffix.lower() in media_extensions
        ]

        if media_files:
            # Embedded media adds significant complexity
            features.layout_complexity_score = min(
                100.0, features.layout_complexity_score + 30
            )
            features.metadata["has_media"] = True
            features.metadata["media_count"] = len(media_files)

    def _extract_metadata(
        self, epub: zipfile.ZipFile, file_list: list, features: DocumentFeatures
    ):
        """Extract EPUB metadata from OPF file."""
        # Find OPF file
        opf_files = [f for f in file_list if f.endswith(".opf")]

        if not opf_files:
            # Try to find from container.xml
            try:
                container = epub.read("META-INF/container.xml").decode("utf-8")
                root = ET.fromstring(container)
                rootfile = root.find(".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile")
                if rootfile is not None:
                    opf_path = rootfile.get("full-path")
                    if opf_path:
                        opf_files = [opf_path]
            except Exception:
                pass

        if not opf_files:
            return

        try:
            opf_content = epub.read(opf_files[0]).decode("utf-8")
            root = ET.fromstring(opf_content)

            # Extract DC metadata
            metadata_elem = root.find(".//{http://www.idpf.org/2007/opf}metadata")
            if metadata_elem is not None:
                for elem in metadata_elem:
                    tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                    if elem.text:
                        features.metadata[tag] = elem.text

        except Exception as e:
            logger.debug(f"Error extracting metadata: {e}")
