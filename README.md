# AI Difficulty Selector

An intelligent document routing system that analyzes PDF and EPUB documents to determine their complexity and routes them to appropriate conversion tools.

## Overview

When converting documents to XML, simpler documents (mostly text, simple formatting) can be processed quickly with non-AI methods, while complex documents (tables, images, multi-column layouts) benefit from AI-powered conversion. This tool automatically analyzes documents and routes them to the appropriate pipeline.

## Features

- **PDF Analysis**: Extracts complexity features including:
  - Image density and count
  - Table detection
  - Layout complexity (multi-column, mixed content)
  - Font variety
  - Scanned document detection

- **EPUB Analysis**: Analyzes:
  - Content structure
  - Embedded images and media
  - CSS complexity
  - Table and form presence

- **Intelligent Scoring**: Weighted scoring system that classifies documents as:
  - **Simple**: Text-heavy, minimal formatting → Fast non-AI conversion
  - **Moderate**: Some complexity → Either pipeline
  - **Complex**: Tables, images, complex layouts → AI-powered conversion

- **Tool Registry**: Plugin system for registering conversion tools
- **Batch Processing**: Process multiple documents in parallel
- **Detailed Reporting**: JSON and text reports with reasoning

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd AIDifficultySelector

# Install dependencies
pip install -r requirements.txt

# Install the package
pip install -e .
```

## Quick Start

### Analyze a Document

```bash
# Analyze a single PDF
aidiff analyze document.pdf

# Analyze with JSON output
aidiff analyze document.pdf --format json

# Analyze a directory of documents
aidiff analyze ./documents/ --recursive
```

### Check Routing Decision

```bash
# See where a document would be routed
aidiff route document.pdf
```

Output:
```
File: document.pdf
Type: pdf
Complexity: simple (score: 25.5)
Confidence: 95%
Recommended Tool: simple_converter
Reasoning:
  - High text coverage (simpler structure)
```

### Process Documents

```bash
# Process with automatic tool selection
aidiff process document.pdf --output ./output/

# Process with a specific tool
aidiff process document.pdf --tool ai_converter

# Batch process
aidiff process ./documents/ --output ./xml/ --recursive --workers 8
```

## Configuration

Create or edit `config/default_config.yaml`:

```yaml
# Complexity thresholds
scoring:
  simple_threshold: 30    # Score ≤ 30 = Simple
  complex_threshold: 70   # Score ≥ 70 = Complex

# Feature weights (must sum to 100)
weights:
  image_density: 25
  table_presence: 20
  layout_complexity: 20
  text_density: 10
  font_variety: 10
  page_count: 5
  has_forms: 10

# Register your conversion tools
tools:
  simple:
    name: "simple_converter"
    description: "Fast non-AI conversion"
    command: "your-simple-tool {input} -o {output}"

  complex:
    name: "ai_converter"
    description: "AI-powered conversion"
    command: "your-ai-tool {input} --output {output}"
```

## Python API

### Basic Usage

```python
from src.agent import DocumentAgent
from src.tools import ToolRegistry, CommandLineTool
from src.scoring import ComplexityLevel

# Create agent
agent = DocumentAgent()

# Analyze a document
result = agent.analyze("document.pdf")
print(f"Complexity: {result.scoring.level.value}")
print(f"Score: {result.scoring.total_score}")

# Get routing decision
routing = agent.route("document.pdf")
print(f"Recommended tool: {routing['recommended_tool']}")
```

### Register Custom Tools

```python
from src.tools import ToolRegistry, CommandLineTool, PythonCallableTool
from src.scoring import ComplexityLevel

registry = ToolRegistry()

# Command-line tool
simple_tool = CommandLineTool(
    name="simple_converter",
    description="Fast non-AI conversion",
    command_template="convert {input} -o {output}",
    supported_levels=[ComplexityLevel.SIMPLE, ComplexityLevel.MODERATE],
    priority=10,  # Higher priority = preferred
)
registry.register(simple_tool)

# Python callable tool
def my_ai_converter(input_path, output_path, **kwargs):
    # Your conversion logic here
    return True  # Return True on success

ai_tool = PythonCallableTool(
    name="ai_converter",
    description="AI-powered conversion",
    callable=my_ai_converter,
    supported_levels=[ComplexityLevel.MODERATE, ComplexityLevel.COMPLEX],
    priority=5,
)
registry.register(ai_tool)

# Create agent with registry
agent = DocumentAgent(tool_registry=registry)
```

### Batch Processing

```python
from pathlib import Path

# Analyze multiple documents
files = list(Path("./documents").glob("*.pdf"))
batch_result = agent.analyze_batch(files, max_workers=8)

print(f"Total: {batch_result.total_documents}")
print(f"By complexity: {batch_result.by_complexity}")

# Process with conversion
batch_result = agent.process_batch(
    files,
    output_dir=Path("./output"),
    max_workers=4,
)
```

### Custom Scoring

```python
from src.scoring import ComplexityScorer

# Custom weights
scorer = ComplexityScorer(
    weights={
        "image_density": 30,      # Prioritize image detection
        "table_presence": 25,
        "layout_complexity": 20,
        "text_density": 10,
        "font_variety": 5,
        "page_count": 5,
        "has_forms": 5,
    },
    simple_threshold=25,  # More aggressive simple classification
    complex_threshold=60,
)

agent = DocumentAgent(scorer=scorer)
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Document Agent                          │
│                    (Orchestrator)                           │
├─────────────────────────────────────────────────────────────┤
│                           │                                 │
│    ┌──────────────────────┼──────────────────────┐         │
│    │                      │                      │         │
│    ▼                      ▼                      ▼         │
│ ┌────────┐          ┌──────────┐          ┌──────────┐     │
│ │  PDF   │          │ Scoring  │          │   Tool   │     │
│ │Analyzer│          │  Engine  │          │ Registry │     │
│ └────────┘          └──────────┘          └──────────┘     │
│                           │                      │         │
│ ┌────────┐                │                      │         │
│ │  EPUB  │                ▼                      ▼         │
│ │Analyzer│          ┌──────────┐          ┌──────────┐     │
│ └────────┘          │ SIMPLE   │          │ Simple   │     │
│                     │ MODERATE │◄────────►│ Tool     │     │
│                     │ COMPLEX  │          │ AI Tool  │     │
│                     └──────────┘          └──────────┘     │
└─────────────────────────────────────────────────────────────┘
```

## Complexity Scoring

Documents are scored 0-100 based on weighted features:

| Feature | Default Weight | Description |
|---------|---------------|-------------|
| Image Density | 25% | Images per page |
| Table Presence | 20% | Detected tables |
| Layout Complexity | 20% | Multi-column, mixed content |
| Text Density | 10% | Text coverage (inverse) |
| Font Variety | 10% | Number of fonts |
| Page Count | 5% | Document length |
| Has Forms | 10% | Interactive elements |

**Classification:**
- **Simple** (≤30): Mostly text, simple formatting
- **Moderate** (31-69): Some complexity, either pipeline works
- **Complex** (≥70): Heavy images, tables, complex layouts

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests: `pytest tests/`
5. Submit a pull request

## License

MIT License
