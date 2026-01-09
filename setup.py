#!/usr/bin/env python3
"""Setup script for AI Difficulty Selector."""

from setuptools import setup, find_packages
from pathlib import Path

# Read README
readme_path = Path(__file__).parent / "README.md"
long_description = readme_path.read_text() if readme_path.exists() else ""

setup(
    name="ai-difficulty-selector",
    version="0.1.0",
    description="Intelligent document routing system for PDF/EPUB to XML conversion",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Your Organization",
    python_requires=">=3.8",
    packages=find_packages(),
    package_dir={"": "."},
    include_package_data=True,
    install_requires=[
        "PyMuPDF>=1.23.0",
        "PyYAML>=6.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-cov>=4.0",
            "black>=23.0",
            "mypy>=1.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "aidiff=src.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
