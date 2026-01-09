"""Tool registry for managing conversion tools."""

import logging
import subprocess
import shlex
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Any
from enum import Enum

from ..scoring.scorer import ComplexityLevel

logger = logging.getLogger(__name__)


class ToolStatus(Enum):
    """Status of tool execution."""
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


@dataclass
class ToolResult:
    """Result from tool execution."""
    status: ToolStatus
    output_path: Optional[str] = None
    stdout: str = ""
    stderr: str = ""
    return_code: int = 0
    execution_time: float = 0.0
    metadata: dict = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status == ToolStatus.SUCCESS

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "output_path": self.output_path,
            "return_code": self.return_code,
            "execution_time": round(self.execution_time, 2),
            "metadata": self.metadata,
        }


class ConversionTool(ABC):
    """Base class for conversion tools."""

    def __init__(
        self,
        name: str,
        description: str,
        supported_levels: List[ComplexityLevel],
        priority: int = 0,
    ):
        """
        Initialize conversion tool.

        Args:
            name: Tool identifier
            description: Human-readable description
            supported_levels: Complexity levels this tool handles
            priority: Higher priority tools are preferred (default: 0)
        """
        self.name = name
        self.description = description
        self.supported_levels = supported_levels
        self.priority = priority

    @abstractmethod
    def convert(
        self,
        input_path: Path,
        output_path: Path,
        **kwargs
    ) -> ToolResult:
        """
        Execute the conversion.

        Args:
            input_path: Path to input document
            output_path: Path for output XML
            **kwargs: Additional tool-specific options

        Returns:
            ToolResult with execution status
        """
        pass

    def supports_level(self, level: ComplexityLevel) -> bool:
        """Check if tool supports the given complexity level."""
        return level in self.supported_levels

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"


class CommandLineTool(ConversionTool):
    """
    Conversion tool that wraps a command-line program.

    Use placeholders in command template:
    - {input}: Input file path
    - {output}: Output file path
    - {options}: Additional options
    """

    def __init__(
        self,
        name: str,
        description: str,
        command_template: str,
        supported_levels: List[ComplexityLevel],
        priority: int = 0,
        timeout: int = 300,
        working_dir: Optional[Path] = None,
    ):
        super().__init__(name, description, supported_levels, priority)
        self.command_template = command_template
        self.timeout = timeout
        self.working_dir = working_dir

    def convert(
        self,
        input_path: Path,
        output_path: Path,
        **kwargs
    ) -> ToolResult:
        """Execute command-line tool for conversion."""
        import time

        # Build command
        options = kwargs.get("options", "")
        command = self.command_template.format(
            input=shlex.quote(str(input_path)),
            output=shlex.quote(str(output_path)),
            options=options,
        )

        logger.info(f"Executing: {command}")
        start_time = time.time()

        try:
            process = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=self.working_dir,
            )

            execution_time = time.time() - start_time

            if process.returncode == 0:
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    output_path=str(output_path),
                    stdout=process.stdout,
                    stderr=process.stderr,
                    return_code=process.returncode,
                    execution_time=execution_time,
                )
            else:
                return ToolResult(
                    status=ToolStatus.FAILED,
                    stdout=process.stdout,
                    stderr=process.stderr,
                    return_code=process.returncode,
                    execution_time=execution_time,
                )

        except subprocess.TimeoutExpired:
            return ToolResult(
                status=ToolStatus.TIMEOUT,
                execution_time=self.timeout,
                metadata={"timeout_seconds": self.timeout},
            )
        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            return ToolResult(
                status=ToolStatus.FAILED,
                stderr=str(e),
                execution_time=time.time() - start_time,
            )


class PythonCallableTool(ConversionTool):
    """
    Conversion tool that wraps a Python callable.

    The callable should have signature:
        def convert(input_path: Path, output_path: Path, **kwargs) -> bool
    """

    def __init__(
        self,
        name: str,
        description: str,
        callable: Callable,
        supported_levels: List[ComplexityLevel],
        priority: int = 0,
    ):
        super().__init__(name, description, supported_levels, priority)
        self.callable = callable

    def convert(
        self,
        input_path: Path,
        output_path: Path,
        **kwargs
    ) -> ToolResult:
        """Execute Python callable for conversion."""
        import time

        start_time = time.time()

        try:
            result = self.callable(input_path, output_path, **kwargs)
            execution_time = time.time() - start_time

            if result is True or (isinstance(result, dict) and result.get("success")):
                metadata = result if isinstance(result, dict) else {}
                return ToolResult(
                    status=ToolStatus.SUCCESS,
                    output_path=str(output_path),
                    execution_time=execution_time,
                    metadata=metadata,
                )
            else:
                return ToolResult(
                    status=ToolStatus.FAILED,
                    execution_time=execution_time,
                    metadata=result if isinstance(result, dict) else {},
                )

        except Exception as e:
            logger.error(f"Python tool error: {e}")
            return ToolResult(
                status=ToolStatus.FAILED,
                stderr=str(e),
                execution_time=time.time() - start_time,
            )


class ToolRegistry:
    """
    Registry for managing conversion tools.

    Allows registering tools and routing documents based on complexity.
    """

    def __init__(self):
        self._tools: Dict[str, ConversionTool] = {}
        self._level_mapping: Dict[ComplexityLevel, List[str]] = {
            level: [] for level in ComplexityLevel
        }

    def register(self, tool: ConversionTool) -> None:
        """
        Register a conversion tool.

        Args:
            tool: ConversionTool to register
        """
        if tool.name in self._tools:
            logger.warning(f"Overwriting existing tool: {tool.name}")

        self._tools[tool.name] = tool

        # Update level mappings
        for level in tool.supported_levels:
            if tool.name not in self._level_mapping[level]:
                self._level_mapping[level].append(tool.name)
                # Sort by priority (highest first)
                self._level_mapping[level].sort(
                    key=lambda n: self._tools[n].priority,
                    reverse=True
                )

        logger.info(f"Registered tool: {tool.name} for levels {tool.supported_levels}")

    def unregister(self, name: str) -> bool:
        """
        Remove a tool from the registry.

        Args:
            name: Tool name to remove

        Returns:
            True if tool was removed, False if not found
        """
        if name not in self._tools:
            return False

        tool = self._tools.pop(name)
        for level in tool.supported_levels:
            if name in self._level_mapping[level]:
                self._level_mapping[level].remove(name)

        return True

    def get_tool(self, name: str) -> Optional[ConversionTool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_tools_for_level(self, level: ComplexityLevel) -> List[ConversionTool]:
        """
        Get tools that support a complexity level, sorted by priority.

        Args:
            level: Complexity level

        Returns:
            List of tools, highest priority first
        """
        tool_names = self._level_mapping.get(level, [])
        return [self._tools[name] for name in tool_names]

    def get_best_tool(self, level: ComplexityLevel) -> Optional[ConversionTool]:
        """
        Get the highest priority tool for a complexity level.

        Args:
            level: Complexity level

        Returns:
            Best tool or None if no tools registered for level
        """
        tools = self.get_tools_for_level(level)
        return tools[0] if tools else None

    def list_tools(self) -> List[Dict[str, Any]]:
        """List all registered tools with their details."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "supported_levels": [l.value for l in tool.supported_levels],
                "priority": tool.priority,
                "type": tool.__class__.__name__,
            }
            for tool in self._tools.values()
        ]

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
