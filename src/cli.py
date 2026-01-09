#!/usr/bin/env python3
"""
AI Difficulty Selector - Command Line Interface

Intelligent document routing system for PDF/EPUB to XML conversion.
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Optional

from .agent import DocumentAgent, ProcessingResult, BatchResult
from .analyzers import PDFAnalyzer, EPUBAnalyzer
from .scoring import ComplexityScorer, ComplexityLevel
from .tools import ToolRegistry, CommandLineTool, PythonCallableTool
from .utils import load_config, Config


def setup_logging(level: str = "INFO", format: str = None):
    """Configure logging."""
    log_format = format or "%(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=log_format,
    )


def create_agent_from_config(
    config: Config,
    output_dir: Optional[Path] = None,
    dry_run: bool = False,
) -> DocumentAgent:
    """Create DocumentAgent from configuration."""
    # Create analyzers
    pdf_analyzer = PDFAnalyzer(
        min_image_size=config.pdf_analysis.min_image_size,
        sample_pages=config.pdf_analysis.sample_pages,
        detect_scanned=config.pdf_analysis.detect_scanned_pages,
    )

    epub_analyzer = EPUBAnalyzer(
        check_media=config.epub_analysis.check_media,
        analyze_css=config.epub_analysis.analyze_css,
    )

    # Create scorer
    scorer = ComplexityScorer(
        weights=config.weights.to_dict(),
        simple_threshold=config.scoring.simple_threshold,
        complex_threshold=config.scoring.complex_threshold,
    )

    # Create tool registry
    registry = ToolRegistry()

    # Register tools from config
    for tool_type, tool_config in config.tools.items():
        if not tool_config.enabled or not tool_config.command:
            continue

        if tool_type == "simple":
            levels = [ComplexityLevel.SIMPLE, ComplexityLevel.MODERATE]
            priority = 10
        elif tool_type == "complex":
            levels = [ComplexityLevel.MODERATE, ComplexityLevel.COMPLEX]
            priority = 5
        else:
            levels = list(ComplexityLevel)
            priority = 0

        tool = CommandLineTool(
            name=tool_config.name,
            description=tool_config.description,
            command_template=tool_config.command,
            supported_levels=levels,
            priority=priority,
        )
        registry.register(tool)

    return DocumentAgent(
        tool_registry=registry,
        scorer=scorer,
        pdf_analyzer=pdf_analyzer,
        epub_analyzer=epub_analyzer,
        output_dir=output_dir,
        dry_run=dry_run,
    )


def cmd_analyze(args):
    """Handle analyze command."""
    config = load_config(Path(args.config) if args.config else None)
    setup_logging(config.logging.level if not args.verbose else "DEBUG")

    agent = create_agent_from_config(config, dry_run=True)

    files = collect_files(args.files, args.recursive)
    if not files:
        print("No files to analyze")
        return 1

    if len(files) == 1:
        result = agent.analyze(files[0])
        print(agent.generate_report(result, format=args.format))
    else:
        result = agent.analyze_batch(files, max_workers=args.workers)
        print(agent.generate_report(result, format=args.format))

    return 0 if result.success if isinstance(result, ProcessingResult) else result.failed == 0 else 1


def cmd_route(args):
    """Handle route command - show routing decision without conversion."""
    config = load_config(Path(args.config) if args.config else None)
    setup_logging(config.logging.level if not args.verbose else "DEBUG")

    agent = create_agent_from_config(config, dry_run=True)

    files = collect_files(args.files, recursive=False)
    if not files:
        print("No files specified")
        return 1

    for file_path in files:
        routing = agent.route(file_path)

        if args.format == "json":
            print(json.dumps(routing, indent=2))
        else:
            print(f"\nFile: {routing['file']}")
            print(f"Type: {routing['document_type']}")
            print(f"Complexity: {routing['complexity_level']} (score: {routing['complexity_score']})")
            print(f"Confidence: {routing['confidence']:.0%}")
            print(f"Recommended Tool: {routing['recommended_tool'] or 'None registered'}")
            if routing['reasoning']:
                print("Reasoning:")
                for reason in routing['reasoning']:
                    print(f"  - {reason}")

    return 0


def cmd_process(args):
    """Handle process command - analyze and convert."""
    config = load_config(Path(args.config) if args.config else None)
    setup_logging(config.logging.level if not args.verbose else "DEBUG")

    output_dir = Path(args.output) if args.output else None
    agent = create_agent_from_config(config, output_dir=output_dir, dry_run=args.dry_run)

    files = collect_files(args.files, args.recursive)
    if not files:
        print("No files to process")
        return 1

    if len(files) == 1:
        result = agent.process(files[0], force_tool=args.tool)
        print(agent.generate_report(result, format=args.format))
        return 0 if result.success else 1
    else:
        result = agent.process_batch(files, output_dir=output_dir, max_workers=args.workers)
        print(agent.generate_report(result, format=args.format))
        return 0 if result.failed == 0 else 1


def cmd_list_tools(args):
    """Handle list-tools command."""
    config = load_config(Path(args.config) if args.config else None)
    agent = create_agent_from_config(config)

    tools = agent.tool_registry.list_tools()

    if args.format == "json":
        print(json.dumps(tools, indent=2))
    else:
        if not tools:
            print("No tools registered. Configure tools in config file.")
            return 0

        print("\nRegistered Conversion Tools:")
        print("-" * 50)
        for tool in tools:
            print(f"\n  Name: {tool['name']}")
            print(f"  Type: {tool['type']}")
            print(f"  Levels: {', '.join(tool['supported_levels'])}")
            print(f"  Priority: {tool['priority']}")
            if tool['description']:
                print(f"  Description: {tool['description']}")

    return 0


def collect_files(paths: List[str], recursive: bool = False) -> List[Path]:
    """Collect files from paths (handles directories)."""
    files = []
    supported_extensions = {".pdf", ".epub"}

    for path_str in paths:
        path = Path(path_str)

        if path.is_file():
            if path.suffix.lower() in supported_extensions:
                files.append(path)
        elif path.is_dir():
            pattern = "**/*" if recursive else "*"
            for ext in supported_extensions:
                files.extend(path.glob(f"{pattern}{ext}"))

    return sorted(set(files))


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        prog="aidiff",
        description="AI Difficulty Selector - Intelligent document routing for conversion",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze a single document
  aidiff analyze document.pdf

  # Analyze multiple documents and get JSON output
  aidiff analyze *.pdf --format json

  # Check where a document would be routed
  aidiff route document.pdf

  # Process documents (requires tools configured)
  aidiff process --output ./xml_output/ documents/

  # Process with a specific tool
  aidiff process document.pdf --tool simple_converter
        """,
    )

    parser.add_argument(
        "--config", "-c",
        help="Path to configuration file",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Analyze command
    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Analyze documents without conversion",
    )
    analyze_parser.add_argument(
        "files",
        nargs="+",
        help="Files or directories to analyze",
    )
    analyze_parser.add_argument(
        "--recursive", "-r",
        action="store_true",
        help="Recursively process directories",
    )
    analyze_parser.add_argument(
        "--workers", "-w",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)",
    )

    # Route command
    route_parser = subparsers.add_parser(
        "route",
        help="Show routing decision for documents",
    )
    route_parser.add_argument(
        "files",
        nargs="+",
        help="Files to check routing for",
    )

    # Process command
    process_parser = subparsers.add_parser(
        "process",
        help="Analyze and convert documents",
    )
    process_parser.add_argument(
        "files",
        nargs="+",
        help="Files or directories to process",
    )
    process_parser.add_argument(
        "--output", "-o",
        help="Output directory for converted files",
    )
    process_parser.add_argument(
        "--tool", "-t",
        help="Force use of specific tool",
    )
    process_parser.add_argument(
        "--recursive", "-r",
        action="store_true",
        help="Recursively process directories",
    )
    process_parser.add_argument(
        "--workers", "-w",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)",
    )
    process_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze only, don't convert",
    )

    # List tools command
    tools_parser = subparsers.add_parser(
        "list-tools",
        help="List registered conversion tools",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    # Dispatch to command handlers
    commands = {
        "analyze": cmd_analyze,
        "route": cmd_route,
        "process": cmd_process,
        "list-tools": cmd_list_tools,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
