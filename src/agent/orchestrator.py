"""
Document Agent Orchestrator

The main agentic component that:
1. Analyzes documents to determine complexity
2. Routes documents to appropriate conversion tools
3. Manages the conversion pipeline
4. Provides reporting and logging
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..analyzers import PDFAnalyzer, EPUBAnalyzer, DocumentFeatures
from ..analyzers.base import DocumentType
from ..scoring import ComplexityScorer, ComplexityLevel, ScoringResult
from ..tools import ToolRegistry, ConversionTool, ToolResult

logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    """Result of processing a single document."""
    file_path: str
    document_type: str
    features: Optional[DocumentFeatures] = None
    scoring: Optional[ScoringResult] = None
    tool_used: Optional[str] = None
    tool_result: Optional[ToolResult] = None
    error: Optional[str] = None
    processing_time: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def success(self) -> bool:
        return self.error is None and (
            self.tool_result is None or self.tool_result.success
        )

    @property
    def complexity_level(self) -> Optional[str]:
        return self.scoring.level.value if self.scoring else None

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "document_type": self.document_type,
            "complexity_level": self.complexity_level,
            "complexity_score": round(self.scoring.total_score, 2) if self.scoring else None,
            "tool_used": self.tool_used,
            "success": self.success,
            "error": self.error,
            "processing_time": round(self.processing_time, 2),
            "timestamp": self.timestamp,
            "features": self.features.to_dict() if self.features else None,
            "scoring": self.scoring.to_dict() if self.scoring else None,
            "tool_result": self.tool_result.to_dict() if self.tool_result else None,
        }


@dataclass
class BatchResult:
    """Result of processing multiple documents."""
    total_documents: int
    successful: int
    failed: int
    by_complexity: Dict[str, int] = field(default_factory=dict)
    by_tool: Dict[str, int] = field(default_factory=dict)
    results: List[ProcessingResult] = field(default_factory=list)
    total_time: float = 0.0

    def to_dict(self) -> dict:
        return {
            "summary": {
                "total": self.total_documents,
                "successful": self.successful,
                "failed": self.failed,
                "total_time": round(self.total_time, 2),
            },
            "by_complexity": self.by_complexity,
            "by_tool": self.by_tool,
            "results": [r.to_dict() for r in self.results],
        }


class DocumentAgent:
    """
    Intelligent document processing agent.

    This agent:
    1. Analyzes documents to extract features
    2. Scores complexity based on features
    3. Routes to appropriate conversion tool
    4. Executes conversion and reports results
    """

    def __init__(
        self,
        tool_registry: Optional[ToolRegistry] = None,
        scorer: Optional[ComplexityScorer] = None,
        pdf_analyzer: Optional[PDFAnalyzer] = None,
        epub_analyzer: Optional[EPUBAnalyzer] = None,
        output_dir: Optional[Path] = None,
        dry_run: bool = False,
    ):
        """
        Initialize the document agent.

        Args:
            tool_registry: Registry of conversion tools
            scorer: Complexity scorer instance
            pdf_analyzer: PDF analyzer instance
            epub_analyzer: EPUB analyzer instance
            output_dir: Default output directory for conversions
            dry_run: If True, analyze only without conversion
        """
        self.tool_registry = tool_registry or ToolRegistry()
        self.scorer = scorer or ComplexityScorer()
        self.pdf_analyzer = pdf_analyzer or PDFAnalyzer()
        self.epub_analyzer = epub_analyzer or EPUBAnalyzer()
        self.output_dir = Path(output_dir) if output_dir else None
        self.dry_run = dry_run

        # Map document types to analyzers
        self._analyzers = {
            DocumentType.PDF: self.pdf_analyzer,
            DocumentType.EPUB: self.epub_analyzer,
        }

    def analyze(self, file_path: Union[str, Path]) -> ProcessingResult:
        """
        Analyze a single document without conversion.

        Args:
            file_path: Path to document

        Returns:
            ProcessingResult with analysis data
        """
        import time
        start_time = time.time()

        file_path = Path(file_path)
        result = ProcessingResult(
            file_path=str(file_path),
            document_type="unknown",
        )

        try:
            # Detect document type
            doc_type = self._detect_type(file_path)
            result.document_type = doc_type.value

            if doc_type == DocumentType.UNKNOWN:
                result.error = f"Unsupported file type: {file_path.suffix}"
                return result

            # Get appropriate analyzer
            analyzer = self._analyzers.get(doc_type)
            if not analyzer:
                result.error = f"No analyzer available for {doc_type.value}"
                return result

            # Extract features
            logger.info(f"Analyzing: {file_path}")
            features = analyzer.analyze(file_path)
            result.features = features

            # Score complexity
            scoring = self.scorer.score(features)
            result.scoring = scoring

            logger.info(
                f"Document: {file_path.name} | "
                f"Complexity: {scoring.level.value} ({scoring.total_score:.1f})"
            )

        except Exception as e:
            logger.error(f"Analysis error for {file_path}: {e}")
            result.error = str(e)

        result.processing_time = time.time() - start_time
        return result

    def process(
        self,
        file_path: Union[str, Path],
        output_path: Optional[Union[str, Path]] = None,
        force_tool: Optional[str] = None,
        **tool_kwargs
    ) -> ProcessingResult:
        """
        Analyze and convert a single document.

        Args:
            file_path: Path to input document
            output_path: Path for output XML (auto-generated if not provided)
            force_tool: Force use of specific tool (bypass routing)
            **tool_kwargs: Additional arguments for conversion tool

        Returns:
            ProcessingResult with full processing data
        """
        import time
        start_time = time.time()

        # First analyze
        result = self.analyze(file_path)
        if result.error:
            result.processing_time = time.time() - start_time
            return result

        # Skip conversion if dry run
        if self.dry_run:
            logger.info("Dry run - skipping conversion")
            result.processing_time = time.time() - start_time
            return result

        file_path = Path(file_path)

        # Determine output path
        if output_path:
            output_path = Path(output_path)
        elif self.output_dir:
            output_path = self.output_dir / f"{file_path.stem}.xml"
        else:
            output_path = file_path.with_suffix(".xml")

        # Get tool
        if force_tool:
            tool = self.tool_registry.get_tool(force_tool)
            if not tool:
                result.error = f"Tool not found: {force_tool}"
                result.processing_time = time.time() - start_time
                return result
        else:
            tool = self.tool_registry.get_best_tool(result.scoring.level)
            if not tool:
                result.error = f"No tool registered for level: {result.scoring.level.value}"
                result.processing_time = time.time() - start_time
                return result

        # Execute conversion
        logger.info(f"Converting with tool: {tool.name}")
        result.tool_used = tool.name

        try:
            tool_result = tool.convert(file_path, output_path, **tool_kwargs)
            result.tool_result = tool_result

            if tool_result.success:
                logger.info(f"Conversion successful: {output_path}")
            else:
                logger.warning(f"Conversion failed: {tool_result.stderr}")

        except Exception as e:
            logger.error(f"Conversion error: {e}")
            result.error = str(e)

        result.processing_time = time.time() - start_time
        return result

    def process_batch(
        self,
        file_paths: List[Union[str, Path]],
        output_dir: Optional[Path] = None,
        max_workers: int = 4,
        **tool_kwargs
    ) -> BatchResult:
        """
        Process multiple documents in parallel.

        Args:
            file_paths: List of document paths
            output_dir: Directory for output files
            max_workers: Maximum parallel workers
            **tool_kwargs: Additional arguments for tools

        Returns:
            BatchResult with all processing results
        """
        import time
        start_time = time.time()

        if output_dir:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)

        batch_result = BatchResult(
            total_documents=len(file_paths),
            successful=0,
            failed=0,
        )

        def process_single(fp):
            out_path = None
            if output_dir:
                out_path = output_dir / f"{Path(fp).stem}.xml"
            return self.process(fp, output_path=out_path, **tool_kwargs)

        # Process in parallel
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(process_single, fp): fp
                for fp in file_paths
            }

            for future in as_completed(futures):
                result = future.result()
                batch_result.results.append(result)

                if result.success:
                    batch_result.successful += 1
                else:
                    batch_result.failed += 1

                # Track by complexity
                if result.complexity_level:
                    level = result.complexity_level
                    batch_result.by_complexity[level] = \
                        batch_result.by_complexity.get(level, 0) + 1

                # Track by tool
                if result.tool_used:
                    tool = result.tool_used
                    batch_result.by_tool[tool] = \
                        batch_result.by_tool.get(tool, 0) + 1

        batch_result.total_time = time.time() - start_time
        return batch_result

    def analyze_batch(
        self,
        file_paths: List[Union[str, Path]],
        max_workers: int = 4,
    ) -> BatchResult:
        """
        Analyze multiple documents without conversion.

        Args:
            file_paths: List of document paths
            max_workers: Maximum parallel workers

        Returns:
            BatchResult with analysis results
        """
        # Temporarily set dry_run
        original_dry_run = self.dry_run
        self.dry_run = True

        try:
            result = self.process_batch(file_paths, max_workers=max_workers)
        finally:
            self.dry_run = original_dry_run

        return result

    def route(self, file_path: Union[str, Path]) -> Dict:
        """
        Analyze document and return routing decision without conversion.

        Useful for checking where a document would be routed.

        Args:
            file_path: Path to document

        Returns:
            Dict with routing information
        """
        result = self.analyze(file_path)

        routing = {
            "file": str(file_path),
            "document_type": result.document_type,
            "complexity_level": result.complexity_level,
            "complexity_score": round(result.scoring.total_score, 2) if result.scoring else None,
            "confidence": round(result.scoring.confidence, 2) if result.scoring else None,
            "recommended_tool": None,
            "available_tools": [],
            "reasoning": result.scoring.reasoning if result.scoring else [],
        }

        if result.scoring:
            best_tool = self.tool_registry.get_best_tool(result.scoring.level)
            if best_tool:
                routing["recommended_tool"] = best_tool.name

            available = self.tool_registry.get_tools_for_level(result.scoring.level)
            routing["available_tools"] = [t.name for t in available]

        return routing

    def generate_report(
        self,
        result: Union[ProcessingResult, BatchResult],
        format: str = "text"
    ) -> str:
        """
        Generate a human-readable report.

        Args:
            result: Processing result to report on
            format: Output format ('text', 'json')

        Returns:
            Formatted report string
        """
        if format == "json":
            return json.dumps(result.to_dict(), indent=2)

        if isinstance(result, ProcessingResult):
            return self._format_single_report(result)
        else:
            return self._format_batch_report(result)

    def _format_single_report(self, result: ProcessingResult) -> str:
        """Format report for single document."""
        lines = [
            "=" * 60,
            "DOCUMENT ANALYSIS REPORT",
            "=" * 60,
            f"File: {result.file_path}",
            f"Type: {result.document_type.upper()}",
            f"Status: {'SUCCESS' if result.success else 'FAILED'}",
        ]

        if result.error:
            lines.append(f"Error: {result.error}")

        if result.scoring:
            lines.extend([
                "",
                "-" * 40,
                "COMPLEXITY ANALYSIS",
                "-" * 40,
                self.scorer.explain_score(result.scoring),
            ])

        if result.tool_used:
            lines.extend([
                "",
                "-" * 40,
                "CONVERSION",
                "-" * 40,
                f"Tool Used: {result.tool_used}",
            ])
            if result.tool_result:
                lines.append(f"Status: {result.tool_result.status.value}")
                if result.tool_result.output_path:
                    lines.append(f"Output: {result.tool_result.output_path}")

        lines.extend([
            "",
            f"Processing Time: {result.processing_time:.2f}s",
            "=" * 60,
        ])

        return "\n".join(lines)

    def _format_batch_report(self, result: BatchResult) -> str:
        """Format report for batch processing."""
        lines = [
            "=" * 60,
            "BATCH PROCESSING REPORT",
            "=" * 60,
            f"Total Documents: {result.total_documents}",
            f"Successful: {result.successful}",
            f"Failed: {result.failed}",
            f"Total Time: {result.total_time:.2f}s",
            "",
            "-" * 40,
            "BY COMPLEXITY LEVEL",
            "-" * 40,
        ]

        for level, count in sorted(result.by_complexity.items()):
            pct = (count / result.total_documents) * 100
            lines.append(f"  {level.upper()}: {count} ({pct:.1f}%)")

        if result.by_tool:
            lines.extend([
                "",
                "-" * 40,
                "BY TOOL USED",
                "-" * 40,
            ])
            for tool, count in sorted(result.by_tool.items()):
                lines.append(f"  {tool}: {count}")

        # List failures
        failures = [r for r in result.results if not r.success]
        if failures:
            lines.extend([
                "",
                "-" * 40,
                "FAILED DOCUMENTS",
                "-" * 40,
            ])
            for r in failures[:10]:  # Limit to first 10
                lines.append(f"  {r.file_path}: {r.error}")
            if len(failures) > 10:
                lines.append(f"  ... and {len(failures) - 10} more")

        lines.append("=" * 60)
        return "\n".join(lines)

    def _detect_type(self, file_path: Path) -> DocumentType:
        """Detect document type from file extension."""
        suffix = file_path.suffix.lower().lstrip(".")
        try:
            return DocumentType(suffix)
        except ValueError:
            return DocumentType.UNKNOWN
