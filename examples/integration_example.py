#!/usr/bin/env python3
"""
Example: Integrating AI Difficulty Selector with your conversion tools.

This example shows how to:
1. Create custom conversion tools
2. Register them with the agent
3. Process documents with automatic routing
"""

import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agent import DocumentAgent
from src.tools import ToolRegistry, CommandLineTool, PythonCallableTool
from src.scoring import ComplexityScorer, ComplexityLevel


# =============================================================================
# Example 1: Command-line tools (wrap your existing CLI tools)
# =============================================================================

def setup_cli_tools() -> ToolRegistry:
    """Setup conversion tools that wrap command-line programs."""
    registry = ToolRegistry()

    # Simple/fast converter for text-heavy documents
    # Replace the command with your actual tool
    simple_tool = CommandLineTool(
        name="simple_xml_converter",
        description="Fast non-AI conversion for simple documents",
        # {input} and {output} are replaced with actual paths
        command_template="pdftotext {input} - | text2xml > {output}",
        supported_levels=[ComplexityLevel.SIMPLE],
        priority=10,  # Higher priority = preferred
        timeout=60,   # 60 second timeout
    )
    registry.register(simple_tool)

    # Moderate complexity converter
    moderate_tool = CommandLineTool(
        name="structured_converter",
        description="Handles tables and basic formatting",
        command_template="pdf2xml --preserve-structure {input} -o {output}",
        supported_levels=[ComplexityLevel.MODERATE],
        priority=5,
    )
    registry.register(moderate_tool)

    # AI-powered converter for complex documents
    ai_tool = CommandLineTool(
        name="ai_xml_converter",
        description="AI-powered conversion for complex layouts",
        command_template="ai-pdf-converter --model gpt4 {input} --output {output}",
        supported_levels=[ComplexityLevel.COMPLEX],
        priority=1,
        timeout=300,  # 5 minute timeout for AI processing
    )
    registry.register(ai_tool)

    return registry


# =============================================================================
# Example 2: Python callable tools (integrate Python libraries directly)
# =============================================================================

def simple_converter(input_path: Path, output_path: Path, **kwargs) -> bool:
    """
    Simple converter using Python libraries.

    Replace this with your actual conversion logic.
    """
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(input_path)
        xml_content = ['<?xml version="1.0" encoding="UTF-8"?>', '<document>']

        for page_num, page in enumerate(doc):
            text = page.get_text()
            xml_content.append(f'  <page number="{page_num + 1}">')
            xml_content.append(f'    <content>{text}</content>')
            xml_content.append('  </page>')

        xml_content.append('</document>')
        doc.close()

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(xml_content))

        return True

    except Exception as e:
        print(f"Conversion error: {e}")
        return False


def ai_converter(input_path: Path, output_path: Path, **kwargs) -> dict:
    """
    AI-powered converter.

    Replace this with your actual AI conversion logic.
    Returns a dict with 'success' key and optional metadata.
    """
    try:
        # Example: Using an AI service for conversion
        # This is a placeholder - replace with your actual AI integration

        # Option 1: OpenAI Vision API
        # from openai import OpenAI
        # client = OpenAI()
        # ... process each page as image ...

        # Option 2: Local AI model
        # from your_ai_module import process_document
        # result = process_document(input_path)

        # Option 3: Cloud service
        # import requests
        # response = requests.post('https://your-ai-service/convert', ...)

        # Placeholder: Just do basic conversion for demo
        import fitz
        doc = fitz.open(input_path)

        xml_content = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<document ai_processed="true">',
        ]

        for page_num, page in enumerate(doc):
            # In real implementation, you'd render page to image
            # and send to AI for structure recognition
            text = page.get_text("dict")

            xml_content.append(f'  <page number="{page_num + 1}">')

            # Process blocks (simplified)
            for block in text.get("blocks", []):
                if block.get("type") == 0:  # Text block
                    xml_content.append('    <text-block>')
                    for line in block.get("lines", []):
                        line_text = " ".join(
                            span.get("text", "") for span in line.get("spans", [])
                        )
                        xml_content.append(f'      <line>{line_text}</line>')
                    xml_content.append('    </text-block>')
                elif block.get("type") == 1:  # Image block
                    xml_content.append('    <image-block/>')

            xml_content.append('  </page>')

        xml_content.append('</document>')
        doc.close()

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(xml_content))

        return {
            "success": True,
            "pages_processed": doc.page_count,
            "ai_model": "placeholder",
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def setup_python_tools() -> ToolRegistry:
    """Setup conversion tools using Python callables."""
    registry = ToolRegistry()

    # Simple converter
    simple_tool = PythonCallableTool(
        name="simple_python_converter",
        description="Basic Python-based conversion",
        callable=simple_converter,
        supported_levels=[ComplexityLevel.SIMPLE, ComplexityLevel.MODERATE],
        priority=10,
    )
    registry.register(simple_tool)

    # AI converter
    ai_tool = PythonCallableTool(
        name="ai_python_converter",
        description="AI-powered Python conversion",
        callable=ai_converter,
        supported_levels=[ComplexityLevel.MODERATE, ComplexityLevel.COMPLEX],
        priority=5,
    )
    registry.register(ai_tool)

    return registry


# =============================================================================
# Example 3: Full integration with custom scoring
# =============================================================================

def main():
    """Main example demonstrating full integration."""

    # Setup tool registry (choose one approach)
    # registry = setup_cli_tools()      # Use CLI tools
    registry = setup_python_tools()     # Use Python tools

    # Custom scoring configuration
    # Adjust these based on your experience with your documents
    scorer = ComplexityScorer(
        weights={
            "image_density": 30,      # Higher weight for images
            "table_presence": 25,     # Tables are important
            "layout_complexity": 15,
            "text_density": 10,
            "font_variety": 10,
            "page_count": 5,
            "has_forms": 5,
        },
        simple_threshold=25,   # More aggressive simple classification
        complex_threshold=65,  # Lower threshold for complex
    )

    # Create agent
    agent = DocumentAgent(
        tool_registry=registry,
        scorer=scorer,
        output_dir=Path("./output"),
    )

    # Example: Analyze a document
    print("=" * 60)
    print("Document Analysis Example")
    print("=" * 60)

    # Create a sample PDF for testing (if you have one)
    sample_files = list(Path(".").glob("*.pdf"))[:1]

    if sample_files:
        pdf_path = sample_files[0]

        # Just analyze (no conversion)
        result = agent.analyze(pdf_path)
        print(f"\nFile: {pdf_path}")
        print(f"Complexity Level: {result.complexity_level}")
        print(f"Score: {result.scoring.total_score:.1f}")
        print(f"Reasoning: {result.scoring.reasoning}")

        # Get routing decision
        routing = agent.route(pdf_path)
        print(f"\nRouting Decision:")
        print(f"  Recommended Tool: {routing['recommended_tool']}")
        print(f"  Available Tools: {routing['available_tools']}")

        # Full processing (analyze + convert)
        # result = agent.process(pdf_path)
        # print(f"\nConversion: {'Success' if result.success else 'Failed'}")
    else:
        print("\nNo PDF files found for testing.")
        print("Place a PDF file in the current directory to test.")

    # List registered tools
    print("\n" + "=" * 60)
    print("Registered Tools")
    print("=" * 60)
    for tool in registry.list_tools():
        print(f"\n  {tool['name']}:")
        print(f"    Type: {tool['type']}")
        print(f"    Levels: {', '.join(tool['supported_levels'])}")
        print(f"    Priority: {tool['priority']}")


if __name__ == "__main__":
    main()
